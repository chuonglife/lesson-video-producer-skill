#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Generate the NARRATION from narration.txt, ONE LINE AT A TIME, then join the lines, so timeline.json holds the exact
start and end of every line (no forced alignment needed).

Usage (run it with the Python that has the TTS engine installed):
  python make_voice.py <narration.txt> <out.mp3> <timeline.json> [--engine kokoro|vieneu|edge] [--voice NAME] [--pace natural|slow|even]

Engines (all local except edge):
  kokoro  Kokoro-82M, Apache 2.0, runs on CPU or GPU. Default voice am_michael (US male); af_heart is a strong female voice.
          The first letter of the voice picks the language: a US English, b UK English, e Spanish, f French, h Hindi,
          i Italian, j Japanese, p Brazilian Portuguese, z Mandarin. pip install kokoro soundfile (Python 3.10-3.12).
  vieneu  VieNeu-TTS v3 Turbo, Apache 2.0, Vietnamese. Default voice "Hải Đăng". Always --pace slow: this model must
          not be time-stretched (atempo makes it sound like a slowed-down tape); slow pace keeps the model's own speed
          and leaves longer pauses between lines instead.
  files   your own recordings: --voice <folder> holding one file per narration line, named by line number
          (001.wav, 002.mp3, ... in the order of narration.txt; silent "." lines need no file). Natural pauses are added.
  edge    edge-tts (Microsoft online voices). Only for a quick test of the pipeline: its terms for commercial use are
          unclear, so do not publish courses with it.

narration.txt: one spoken beat per line, ending in . , or ?. "Line text. |20" means 20 extra seconds of silence after
the line (a pause for the learner). A line that is only "." is a silent slide (1.2 s).
Every generated line is cached in <out.mp3>.cache, named by a hash of its text and voice: editing one line regenerates
that line only. Delete the cache after changing voice settings you want to hear on every line.
Run it through gpu_lock.py when other jobs share the GPU.
"""
import argparse
import asyncio
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

LEAD = 0.6      # silence before the first line
TAIL = 1.2      # silence after the last line
GAP_PERIOD = 0.34
GAP_COMMA = 0.14

# Pronunciation fixes FOR THE VOICE ONLY (subtitles keep the original spelling). Add a pair only after you heard the
# engine get the word wrong AND heard the new spelling come out right. Keep it short: modern engines read most loan
# words and product names well, and a "phonetic" respelling can make things worse.
PRONUNCIATION = {
    "kokoro": {},
    "vieneu": {},
    "edge": {},
}

EMPHASIS = re.compile(r"\b(remember|important|key|never|always|mistake|secret|most)\b|nhớ|quan trọng|đừng|luôn|không bao giờ|lỗi", re.I)
TURN = ("but ", "now", "so ", "and here", "here is", "that is", "however", "remember", "nhưng", "bây giờ", "vậy", "và đây")
COUNT = ("one,", "two,", "three,", "four,", "five,", "six,", "first,", "second,", "third,", "một,", "hai,", "ba,", "bốn,", "năm,", "sáu,")


def _jitter(text, span):
    """A fixed pseudo-random number in -span..+span derived from the text (re-runs give identical audio)."""
    h = int(hashlib.md5(text.encode("utf-8")).hexdigest()[:6], 16) / 0xFFFFFF
    return (h * 2 - 1) * span


def line_speed(text, i):
    """Speaking rate by the role of the line (1.0 = normal): a brisk opening, slower questions and key points, flowing long lines."""
    n = len(text.split())
    s = 1.02
    if n <= 6:
        s = 0.96
    elif n >= 24:
        s = 1.07
    if text.lower().startswith(COUNT):
        s = 1.05
    if i <= 1:
        s = max(s, 1.05)
    if text.endswith("?"):
        s = min(s, 0.96)
    if EMPHASIS.search(text):
        s = min(s, 0.92)
    return round(max(0.88, min(1.1, s + _jitter(text, 0.03))), 2)


def gap_natural(text, nxt):
    """Pause after a line, like a person: longer after a question and before a turn, short inside a 1-2-3 list."""
    n = len(text.split())
    nl = (nxt or "").lower()
    if text.endswith("?"):
        g = 0.9 if not (nxt and nxt.endswith("?")) else 0.42
    elif text.endswith(":"):
        g = 0.6
    elif text.endswith("!"):
        g = 0.55
    elif text.endswith("."):
        g = 0.28 + min(0.34, n * 0.009)
    else:
        g = 0.16
    if nxt:
        if text.lower().startswith(COUNT) and nl.startswith(COUNT):
            g = 0.2
        elif nl.startswith(TURN):
            g = max(g, 0.72 if n <= 6 else 0.58)
    return round(g * (1 + _jitter(text + "#", 0.15)), 2)


def gap_slow(text, nxt):
    """Slow pace: the model keeps its own speed, the pauses get longer, with a small jitter so it never sounds mechanical."""
    if text.endswith("?"):
        g = 1.3
    elif text.endswith((".", ":", "!")):
        g = 0.85
    else:
        g = 0.4
    if nxt and nxt.lower().startswith(TURN):
        g = max(g, 1.0)
    return round(g * (1 + _jitter(text + "#", 0.12)), 2)


def duration(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def ff(*a):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *a], check=True)


async def tts_edge(text, voice, out):
    import edge_tts
    for attempt in range(8):
        try:
            await edge_tts.Communicate(text, voice, rate="+0%").save(str(out))
            await asyncio.sleep(0.6)
            return
        except Exception as e:
            if attempt == 7:
                raise RuntimeError(f"edge-tts failed 8 times: {text}") from e
            await asyncio.sleep(3 + 3 * attempt)


_VIENEU = None
_KOKORO = {}


def tts_vieneu(text, voice, out):
    global _VIENEU
    if _VIENEU is None:
        from vieneu import Vieneu
        try:
            import torch
            dev = "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            dev = "cpu"
        _VIENEU = Vieneu(device=dev)
    audio = _VIENEU.infer(text, voice=voice, temperature=0.6, top_k=25, top_p=0.9,
                          repetition_penalty=1.2, silence_p=0.15, max_chars=256, denoise=True)
    _VIENEU.save(audio, str(out))


def tts_kokoro(text, voice, out, speed=1.0):
    import numpy as np
    import soundfile as sf
    lang = voice[0] if voice and voice[0] in "abefhijpz" else "a"
    if lang not in _KOKORO:
        from kokoro import KPipeline
        try:
            import torch
            dev = "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            dev = "cpu"
        _KOKORO[lang] = KPipeline(lang_code=lang, device=dev)
    parts = [a.cpu().numpy() if hasattr(a, "cpu") else np.asarray(a) for _, _, a in _KOKORO[lang](text, voice=voice, speed=speed)]
    if not parts:
        raise RuntimeError(f"Kokoro produced no audio for: {text}")
    sf.write(str(out), np.concatenate(parts), 24000)


def spoken(text, engine):
    for k, v in PRONUNCIATION.get(engine, {}).items():
        text = re.sub(rf"(?<![\w-]){re.escape(k)}(?![\w-])", v, text)
    return text


async def main(a):
    lines, extra = [], []
    for raw in Path(a.narration).read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        m = re.search(r"\s*\|\s*(\d+(?:[.,]\d+)?)\s*$", raw)
        lines.append((raw[:m.start()] if m else raw).strip())
        extra.append(float(m.group(1).replace(",", ".")) if m else 0.0)
    out_mp3 = Path(a.out_mp3)
    cache = Path(str(out_mp3) + ".cache"); cache.mkdir(parents=True, exist_ok=True)
    voice = a.voice or {"edge": "en-US-AndrewNeural", "vieneu": "Hải Đăng", "kokoro": "am_michael", "files": "recordings"}[a.engine]
    if a.engine in ("vieneu", "files") and a.pace == "natural":
        print("This voice must not be time-stretched: using --pace slow")
        a.pace = "slow"
    natural = a.pace == "natural"
    ext = "mp3" if a.engine == "edge" else "wav"
    if a.engine == "files" and not Path(voice).is_dir():
        raise SystemExit("--engine files needs --voice <folder with 001.wav, 002.wav, ...>")
    speed = [line_speed(t, i) if natural else 1.0 for i, t in enumerate(lines)]
    tag = lambda i: "_" + hashlib.md5((spoken(lines[i], a.engine) + voice).encode("utf-8")).hexdigest()[:8] + (f"_s{round(speed[i] * 100)}" if natural else "")
    for i, text in enumerate(lines):
        if text in (".", "..", "…"):
            continue
        f = cache / f"l{i:03d}{tag(i)}.{ext}"
        if f.exists() and f.stat().st_size > 1000:
            continue
        t2 = spoken(text, a.engine)
        if a.engine == "files":
            rec = next((p for p in sorted(Path(voice).glob(f"{i + 1:03d}.*"))), None)
            if rec is None:
                raise SystemExit(f"missing recording for line {i + 1}: {Path(voice) / f'{i + 1:03d}.wav'}  ({text})")
            ff("-i", str(rec), "-ar", "24000", "-ac", "1", str(f))
        elif a.engine == "edge":
            await tts_edge(t2, voice, f)
        elif a.engine == "vieneu":
            tts_vieneu(t2, voice, f)
        else:
            tts_kokoro(t2, voice, f, speed[i])
        print(f"  line {i + 1}/{len(lines)}", flush=True)

    def silence(sec, name):
        p = cache / name
        ff("-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", f"{max(0.05, sec):.3f}", str(p))
        return p

    parts, timeline, t = [silence(LEAD, "lead.wav")], [], LEAD
    for i, text in enumerate(lines):
        if text in (".", "..", "…"):
            d = 1.2
            parts.append(silence(d, f"e{i:03d}.wav"))
            timeline.append({"n": i + 1, "start": round(t, 3), "end": round(t + d, 3), "text": ""})
            t += d
        else:
            w = cache / f"w{i:03d}.wav"
            af = ["-af", f"atempo={speed[i]}"] if natural and a.engine == "edge" else []
            ff("-i", str(cache / f"l{i:03d}{tag(i)}.{ext}"), *af, "-ar", "24000", "-ac", "1", str(w))
            d = duration(w)
            timeline.append({"n": i + 1, "start": round(t, 3), "end": round(t + d, 3), "text": text})
            parts.append(w); t += d
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        g = gap_natural(text, nxt) if natural else gap_slow(text, nxt) if a.pace == "slow" else (GAP_PERIOD if text.endswith(".") else GAP_COMMA)
        g += extra[i]
        parts.append(silence(g, f"g{i:03d}.wav")); t += g
    parts.append(silence(TAIL, "tail.wav"))
    lst = cache / "list.txt"
    lst.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in parts), encoding="utf-8")
    ff("-f", "concat", "-safe", "0", "-i", str(lst), "-c:a", "libmp3lame", "-q:a", "2", str(out_mp3))
    real = duration(out_mp3)
    words = sum(len(x.split()) for x in lines)
    Path(a.timeline).write_text(json.dumps({"duration": round(real, 3), "engine": a.engine, "voice": voice, "pace": a.pace,
                                            "lines": timeline}, ensure_ascii=False, indent=1), encoding="utf-8")
    talk = sum(l["end"] - l["start"] for l in timeline)
    print(f"{len(lines)} lines, {real:.1f} s ({int(real // 60)} min {int(real % 60)} s), {a.engine}/{voice}, "
          f"{words / max(talk, 1):.1f} words/s while speaking, {words / real * 60:.0f} words/min overall")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("narration"); p.add_argument("out_mp3"); p.add_argument("timeline")
    p.add_argument("--engine", default="kokoro", choices=["kokoro", "vieneu", "edge", "files"])
    p.add_argument("--pace", default=None, choices=["natural", "slow", "even"])
    p.add_argument("--voice")
    a = p.parse_args()
    if a.pace is None:
        a.pace = "slow" if a.engine in ("vieneu", "files") else "natural"
    asyncio.run(main(a))
