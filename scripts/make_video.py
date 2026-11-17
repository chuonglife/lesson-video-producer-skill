#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
MAKE THE LESSON VIDEO with ONE COMMAND from an existing deck (slides/<course>/<lesson>/slides.json + .pptx + _preview/slide-NN.png).

Usage:
  python make_video.py <slides.json> [--lang en|vi|...] [--engine kokoro|vieneu|edge|files] [--voice NAME or folder]
                       [--no-music] [--music-db -22] [--no-sfx] [--extend] [--skip-review]
                       [--from-step N] [--workers 2] [--crf 18] [--full-render]

Steps (everything is written to videos/<course>/<lesson>/):
  1. storyboard.py     slides.json + pptx -> narration.txt, storyboard.json, storyboard.md   (reads video.json if present)
  2. make_voice.py     narration.txt -> <name>.voice.mp3 + timeline.json   (en: Kokoro am_michael; vi: VieNeu; through gpu_lock)
  3. review_voice.py   Whisper listens back; suspect lines are regenerated (the engines sample, so a second take usually
                       reads right) and checked again, up to 3 rounds; still wrong = STOP with the list (--skip-review to bypass)
  4. render.mjs plan   -> events.json (slide times + sound events)
     (--extend: a slide whose screen recording runs longer than its narration gets a "hold" in video.json, then steps 1-4 again)
  5. mix_audio.py      voice + sound effects + music -> audio.mp3
  6. render.mjs video  -> <name>.base.mp4 (picture + sound), rendered incrementally slide by slide
  7. composite_clips.py -> <name>.mp4 (screen recordings from video.json; otherwise a copy)
  8. make_subtitles.py -> <name>.<lang>.srt / .vtt
  9. check_video.py    -> _check/<name>.report.md + contact sheets _check/contact-NN.png; FAIL = exit code 1
Restart from a step with --from-step N (1 storyboard, 2 voice, 3 review, 4 plan...): the voice is cached line by line,
so step 2 is fast on a re-run. Your own recordings: --engine files --voice <folder with 001.wav, 002.wav, ...>.

Python for the voice engines: set KOKORO_PYTHON / VIENEU_PYTHON when the engine lives in its own virtual environment;
otherwise the current Python is used.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent / "assets" / "engine"


def run(cmd, step):
    print(f"\n=== {step} · {time.strftime('%H:%M:%S')} ===")
    print("+", " ".join(f'"{c}"' if " " in str(c) else str(c) for c in cmd), flush=True)
    if subprocess.run([str(c) for c in cmd]).returncode:
        raise SystemExit(f"STOPPED at {step}")


def duration(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)], capture_output=True, text=True)
    return float(r.stdout.strip() or 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slides")
    ap.add_argument("--lang")
    ap.add_argument("--engine", choices=["kokoro", "vieneu", "edge", "files"])
    ap.add_argument("--voice")
    ap.add_argument("--no-music", action="store_true")
    ap.add_argument("--music-db", type=float, default=-22)
    ap.add_argument("--no-sfx", action="store_true")
    ap.add_argument("--extend", action="store_true")
    ap.add_argument("--skip-review", action="store_true")
    ap.add_argument("--from-step", type=int, default=1)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--crf", type=int, default=18)
    ap.add_argument("--full-render", action="store_true")
    a = ap.parse_args()
    if not (ENGINE / "node_modules" / "puppeteer-core").is_dir():
        raise SystemExit(f"Install the renderer once: npm install --prefix \"{ENGINE}\"")
    src = Path(a.slides).resolve()
    spec = json.loads(src.read_text(encoding="utf-8"))
    name = spec.get("file_name") or spec.get("ten_tep") or src.stem
    lang = a.lang or spec.get("language") or "en"
    parts = list(src.parent.parts)
    out = Path(*[("videos" if p == "slides" else p) for p in parts]) if "slides" in parts else src.parent / "video"
    out.mkdir(parents=True, exist_ok=True)
    engine = a.engine or ("vieneu" if lang == "vi" else "kokoro")
    py = sys.executable
    py_tts = {"kokoro": os.environ.get("KOKORO_PYTHON", py), "vieneu": os.environ.get("VIENEU_PYTHON", py), "edge": py, "files": py}[engine]
    if not Path(py_tts).is_file():
        raise SystemExit(f"Python for {engine} not found: {py_tts}")
    f = lambda ext: out / f"{name}{ext}"
    narration, board, voice, tl, events, audio, base, final = (f(".narration.txt"), f(".storyboard.json"), f(".voice.mp3"), f(".timeline.json"),
                                                              f(".events.json"), f(".audio.mp3"), f(".base.mp4"), f(".mp4"))
    overrides = out / "video.json"
    check = out / "_check"; check.mkdir(exist_ok=True)
    gpu = [py, HERE / "gpu_lock.py", "--"]

    def steps_1_to_4(start=1):
        run([py, HERE / "storyboard.py", src], "1/9 storyboard")
        tts = gpu + [py_tts, HERE / "make_voice.py", narration, voice, tl, "--engine", engine] + (["--voice", a.voice] if a.voice else [])
        if start <= 2:
            run(tts, "2/9 narration")
        if start <= 3 and not a.skip_review and engine not in ("edge", "files"):
            review = gpu + [py, HERE / "review_voice.py", voice, narration, "--lang", lang, "--out", check / "voice-review.txt",
                            "--exceptions", check / "voice-exceptions.txt", "--timeline", tl]
            r = subprocess.run([str(c) for c in review])
            suspects = check / "suspect-lines.json"
            for round_ in range(3):
                if r.returncode not in (0, 3):
                    raise SystemExit(f"STOPPED at 3/9: the voice review itself failed (exit code {r.returncode}); see the error above. "
                                     "Fix faster-whisper (pip install faster-whisper; on Windows the CUDA libraries, or set WHISPER_DEVICE=cpu) "
                                     "or rerun with --skip-review and say so in the report.")
                if r.returncode == 0:
                    break
                bad = json.loads(suspects.read_text(encoding="utf-8")) if suspects.is_file() else []
                if not bad:
                    break
                cache = Path(str(voice) + ".cache")
                for p in [p for n in bad for p in cache.glob(f"l{n - 1:03d}_*")]:
                    p.unlink()
                print(f"round {round_ + 1}: regenerating suspect lines {bad}")
                run(tts, f"2/9 narration (lines {bad})")
                r = subprocess.run([str(c) for c in review + ["--only-lines", ",".join(map(str, bad))]])
            if r.returncode not in (0, 3):
                raise SystemExit(f"STOPPED at 3/9: the voice review failed (exit code {r.returncode}).")
            if r.returncode:
                raise SystemExit(f"STOPPED at 3/9: the voice still misreads something after 3 takes, see {check / 'voice-review.txt'}. "
                                 f"Listen to it. If the voice is wrong, change the word in slides.json or add a respelling to PRONUNCIATION in "
                                 f"make_voice.py; if Whisper misheard, add the word to {check / 'voice-exceptions.txt'}; then --from-step 2.")
        run(["node", ENGINE / "render.mjs", "plan", board, tl, events], "4/9 render plan")

    if a.from_step <= 4:
        steps_1_to_4(a.from_step)
        if a.extend and overrides.is_file():
            ov = json.loads(overrides.read_text(encoding="utf-8"))
            plan = json.loads(events.read_text(encoding="utf-8"))
            changed = False
            for s in plan["slides"]:
                c = (ov.get(s["id"]) or {}).get("clip")
                if not c:
                    continue
                cf = Path(c["file"]); cf = cf if cf.is_absolute() else out / cf
                if not cf.is_file():
                    continue
                length = float(c.get("length") or max(0.1, duration(cf) - float(c.get("start", 0))))
                length *= float(c["speed"]) if isinstance(c.get("speed"), (int, float)) else 1.0
                missing = length + 1.0 - (s["t1"] - s["t0"]) + float(ov[s["id"]].get("hold", 0))
                if missing > 0.3:
                    ov[s["id"]]["hold"] = round(float(ov[s["id"]].get("hold", 0)) + missing, 1)
                    print(f"{s['id']}: the recording is longer than the narration, adding {missing:.1f} s (hold = {ov[s['id']]['hold']})")
                    changed = True
            if changed:
                overrides.write_text(json.dumps(ov, ensure_ascii=False, indent=1), encoding="utf-8")
                steps_1_to_4()
    if a.from_step <= 5:
        run([py, HERE / "mix_audio.py", voice, events, audio, "--music-db", a.music_db] + (["--no-music"] if a.no_music else []) +
            (["--no-sfx"] if a.no_sfx else []), "5/9 sound mix")
    if a.from_step <= 6:
        run(["node", ENGINE / "render.mjs", "video", board, tl, audio, base, "--fps", 30, "--workers", a.workers, "--crf", a.crf] +
            (["--full"] if a.full_render else []), "6/9 picture")
    if a.from_step <= 7:
        run([py, HERE / "composite_clips.py", board, tl, overrides, base, final], "7/9 screen recordings")
    if a.from_step <= 8:
        run([py, HERE / "make_subtitles.py", tl, out / f"{name}.{lang}"], "8/9 subtitles")
    run([py, HERE / "check_video.py", final, "--timeline", tl, "--events", events], "9/9 final check")
    print(f"\nDONE: {final}\nLook at {check}/contact-*.png, report: {check}/{name}.report.md")


if __name__ == "__main__":
    main()
