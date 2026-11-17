#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
REVIEW THE SYNTHETIC VOICE with Whisper: transcribe the narration audio and compare it with the script, then list the
places where the voice probably misread a word (and, for Vietnamese, the wrong tone), each with its mm:ss.

Usage:  python review_voice.py <voice.mp3> <narration.txt> [--lang en|vi|...] [--out <voice-review.txt>]
                               [--exceptions <file>] [--timeline <timeline.json>] [--only-lines 5,9]
  Needs faster-whisper. Model large-v3 by default (int8_float16 on a 4 GB GPU, int8 on CPU); set WHISPER_MODEL to change it.
  --exceptions   one word or phrase per line that you listened to and found correct (Whisper misheard it); also "said>heard".
  --timeline     enables the second listen on the exact line and writes suspect-lines.json (1-based line numbers).
  --only-lines   listen again to these lines only (cut by the timeline) instead of the whole file.

Filtered automatically (listed at the end of the report): Whisper mishearing a short word (one word of 4 letters or
fewer, not a term or a name); text Whisper invents over music or silence outside every narration line ("thanks for
watching", "subscribe"); places where a second listen (beam 10, primed with the line) hears the script correctly.
It only stops on long words, terms, names or several words in a row. Exit code 3 when anything is left (1 = the review itself failed).
Numbers written as words in the script and digits in the transcript are treated as equal. In English, the same words
spelled two ways ("lesson two" / "lesson 2", "mac os" / "macos") are equal too, and the pairs in
assets/whisper-homophones-en.txt (shared by every lesson, "said>heard", for example "claude>clawed") are exceptions.
"""
import argparse
import difflib
import json
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _cuda_dlls():
    """On Windows, CTranslate2 needs cuBLAS/cuDNN DLLs; reuse the ones shipped with PyTorch or the nvidia-* pip wheels."""
    if sys.platform != "win32":
        return
    import site
    dirs = []
    try:
        import importlib.util
        spec = importlib.util.find_spec("torch")
        if spec and spec.origin:
            dirs.append(os.path.join(os.path.dirname(spec.origin), "lib"))
    except Exception:
        pass
    for sp in site.getsitepackages():
        dirs += [str(p) for p in Path(sp, "nvidia").glob("*/bin")]
    dirs += [d for d in os.environ.get("CUDA_DLL_DIRS", "").split(os.pathsep) if d]
    for d in dirs:
        if os.path.isdir(d):
            try:
                os.add_dll_directory(d)
                os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]
            except OSError:
                pass


_cuda_dlls()
EXIT_SUSPECTS = 3   # exit code when suspect places remain (a crash exits with 1)

# ---------- number words, so "20%" and "twenty percent" compare equal ----------
EN_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
EN_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def en_number(n):
    if n < 20:
        return EN_ONES[n]
    if n < 100:
        return EN_TENS[n // 10] + ("" if n % 10 == 0 else " " + EN_ONES[n % 10])
    if n < 1000:
        return EN_ONES[n // 100] + " hundred" + ("" if n % 100 == 0 else " " + en_number(n % 100))
    if n < 1000000:
        return en_number(n // 1000) + " thousand" + ("" if n % 1000 == 0 else " " + en_number(n % 1000))
    return str(n)


VI_DIGITS = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín", "mười"]


def vi_number(n):
    if n <= 10:
        return VI_DIGITS[n]
    if n < 20:
        return "mười " + ("lăm" if n == 15 else VI_DIGITS[n - 10])
    if n < 100:
        unit = {0: "", 1: "mốt", 5: "lăm"}.get(n % 10, VI_DIGITS[n % 10])
        return VI_DIGITS[n // 10] + " mươi " + unit
    return str(n)


def strip_marks(t):
    t = t.replace("đ", "d")
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")


def northern(w):
    # a northern Vietnamese voice says tr/ch, s/x, d/gi/r alike; Whisper may spell either, which is not a voice error
    return re.sub(r"^(tr|x|gi|r)", lambda m: {"tr": "ch", "x": "s", "gi": "d", "r": "d"}[m.group(1)], w)


def norm(t, lang, keep_marks=False):
    t = unicodedata.normalize("NFC", t.lower())
    if lang == "vi":
        t = re.sub(r"(\d)\s*%", r"\1 phần trăm ", t)
        t = re.sub(r"(\d)\s*[-–]\s*(\d)", r"\1 đến \2", t)
        t = re.sub(r"\d+", lambda m: " " + vi_number(int(m.group(0))) + " ", t)
    elif lang == "en":
        t = re.sub(r"(\d),(\d{3})", r"\1\2", t)
        t = re.sub(r"(\d)\s*%", r"\1 percent ", t)
        t = re.sub(r"(\d)\s*[-–]\s*(\d)", r"\1 to \2", t)
        t = re.sub(r"\b(\d+)(st|nd|rd|th)\b", r"\1", t)
        t = re.sub(r"\d+", lambda m: " " + en_number(int(m.group(0))) + " ", t)
        t = t.replace("-", " ")
        t = re.sub(r"'(s|re|ll|ve|d|t|m)\b", r"\1", t)
    t = re.sub(r"[^\w\s]+", " ", t).replace("_", " ")
    if keep_marks:
        return t.split()
    words = strip_marks(t).split()
    return [northern(w) for w in words] if lang == "vi" else words


EN_DIGIT = {"zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
            "seven": "7", "eight": "8", "nine": "9", "ten": "10"}


def compact_en(t):
    """A compact form to compare two spellings of the same English words: number words as digits, no spaces or hyphens
    ('b02 one' and 'b021', 'mac os' and 'macos', 'lesson two' and 'lesson 2' are the same thing said)."""
    return "".join(EN_DIGIT.get(x, x) for x in re.findall(r"[a-z0-9]+", (t or "").lower()))


SHARED_HOMOPHONES = Path(__file__).resolve().parent.parent / "assets" / "whisper-homophones-en.txt"


def load_shared(lang):
    """Pairs every English lesson shares ("said>heard": Whisper spells them differently, the voice says them right)."""
    if lang != "en" or not SHARED_HOMOPHONES.is_file():
        return set()
    return {l.strip().lower() for l in SHARED_HOMOPHONES.read_text(encoding="utf-8").splitlines() if l.strip() and not l.lstrip().startswith("#")}


def mmss(s):
    return f"{int(s // 60)}:{s % 60:04.1f}"


INVENTED = re.compile(r"subscribe|thanks? for watching|thank you for watching|like and share|see you (next|in the)|"
                      r"dang ky kenh|cam on cac ban|hen gap lai|theo doi kenh|nhan chuong")


def strict_terms(text, lang):
    """Words that must be exact: capitalised mid-sentence (names, products) or, in Vietnamese, words with f/j/w/z
    (English). Words that also appear in lower case are dropped."""
    upper, lower = set(), set()
    for line in text.splitlines():
        ws = re.findall(r"[^\W\d_]+", line)
        for k, w in enumerate(ws):
            b = strip_marks(w.lower())
            if (lang == "vi" and re.search(r"[fjwz]", b)) or (k > 0 and w[0].isupper()):
                upper.add(b)
            elif w[0].islower():
                lower.add(b)
    return upper - lower


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mp3"); ap.add_argument("narration")
    ap.add_argument("--lang", default="en"); ap.add_argument("--out"); ap.add_argument("--exceptions")
    ap.add_argument("--timeline"); ap.add_argument("--only-lines", dest="only_lines")
    a = ap.parse_args()
    import ctranslate2
    from faster_whisper import WhisperModel
    dev = os.environ.get("WHISPER_DEVICE") or ("cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu")
    name = os.environ.get("WHISPER_MODEL", "large-v3")
    model = None
    if dev == "cuda":
        try:
            model = WhisperModel(name, device="cuda", compute_type="int8_float16")
            model.transcribe(np.zeros(16000, dtype=np.float32), language=a.lang)   # forces the CUDA libraries to load now
            for _ in model.transcribe(np.zeros(16000, dtype=np.float32), language=a.lang)[0]:
                pass
        except Exception as e:
            print(f"CUDA unavailable for Whisper ({str(e)[:90]}); using the CPU", flush=True)
            model, dev = None, "cpu"
    if model is None:
        model = WhisperModel(name, device="cpu", compute_type="int8")
    print("Whisper on", dev, flush=True)
    lang = a.lang
    tonal = lang == "vi"
    exceptions = set()
    if a.exceptions and Path(a.exceptions).is_file():
        exceptions = {l.strip().lower() for l in Path(a.exceptions).read_text(encoding="utf-8").splitlines() if l.strip()}
    exceptions |= load_shared(lang)
    tl =json.loads(Path(a.timeline).read_text(encoding="utf-8"))["lines"] if a.timeline else []
    tl = [l for l in tl if l.get("text")]
    raw = Path(a.narration).read_text(encoding="utf-8")
    script = re.sub(r"\|\s*\d+(?:[.,]\d+)?\s*$", " ", raw, flags=re.M)
    terms = strict_terms(script, lang)
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", a.mp3, "-ac", "1", "-ar", "16000", "-f", "f32le", "-"], capture_output=True, check=True).stdout
    audio = np.frombuffer(pcm, dtype="<f4")
    script_lines = [l for l in re.sub(r"\|\s*\d+(?:[.,]\d+)?\s*$", "", raw, flags=re.M).splitlines() if l.strip()]

    def line_at(t, margin=0.3):
        return next((l for l in tl if l["start"] - margin <= t <= l["end"] + margin), None)

    def hear(seg, offset):
        segs, _ = model.transcribe(seg, language=lang, beam_size=5, vad_filter=True, condition_on_previous_text=False, word_timestamps=True)
        words, words_m, times = [], [], []
        for sg in segs:
            for w in (sg.words or []):
                wt = w.word.replace("%", " percent " if lang == "en" else " phần trăm " if lang == "vi" else "%")
                wt = re.sub(r"^\s*[-–](\d)", (r" to \1" if lang == "en" else r" đến \1"), wt)
                x, y = norm(wt, lang), norm(wt, lang, True)
                words += x; words_m += y; times += [offset + w.start] * len(x)
        return words, words_m, times

    def hear_again(t, phrase, marks=False):
        """Second listen (beam 10, primed with the script line) on the line around t: True if it now hears the phrase."""
        l = line_at(t)
        s0, s1 = (l["start"] - 0.35, l["end"] + 0.35) if l else (t - 1.6, t + 2.2)
        seg = audio[int(max(0.0, s0) * 16000): int(s1 * 16000)]
        prompt = (l or {}).get("text") or next((x for x in script_lines if phrase and all(w in norm(x, lang, marks) for w in phrase.split())), "")
        sg2, _ = model.transcribe(seg, language=lang, beam_size=10, initial_prompt=prompt or None, condition_on_previous_text=False)
        txt = " ".join(" ".join(norm(x.text, lang, marks)) for x in sg2)
        return bool(phrase) and (" " + phrase + " ") in (" " + txt + " ")

    def compare(ref, ref_m, heard, heard_m, times):
        out = []
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ref, heard, autojunk=False).get_opcodes():
            if tag == "equal":
                if tonal:
                    for k in range(i2 - i1):
                        g = ref_m[i1 + k] if i1 + k < len(ref_m) else ""
                        n = heard_m[j1 + k] if j1 + k < len(heard_m) else ""
                        if g and n and g != n and strip_marks(g) == strip_marks(n):
                            out.append((times[j1 + k], "tone", g, n))
                continue
            t = times[j1] if j1 < len(times) else (times[-1] if times else 0)
            out.append((t, tag, " ".join(ref[i1:i2]), " ".join(heard[j1:j2])))
        return out

    diffs = []
    if a.only_lines:
        if not tl:
            raise SystemExit("--only-lines needs --timeline")
        wanted = {int(x) for x in a.only_lines.split(",") if x.strip()}
        n_ref = 0
        for l in tl:
            if l["n"] not in wanted:
                continue
            s0 = max(0.0, l["start"] - 0.3)
            heard = hear(audio[int(s0 * 16000): int((l["end"] + 0.3) * 16000)], s0)
            diffs += compare(norm(l["text"], lang), norm(l["text"], lang, True), *heard)
            n_ref += len(norm(l["text"], lang))
        n_heard = n_ref
    else:
        ref, ref_m = norm(script, lang), norm(script, lang, True)
        heard = hear(audio, 0.0)
        diffs = compare(ref, ref_m, *heard)
        n_ref, n_heard = len(ref), len(heard[0])

    problems, report, bad_times, filtered = 0, [], [], []
    count = {"exception": 0, "same words": 0, "second listen": 0, "short word": 0, "outside narration": 0, "invented": 0}
    for t, tag, g, n in diffs:
        if tag == "tone":
            if g in exceptions or f"{g}>{n}" in exceptions:
                count["exception"] += 1; continue
            if hear_again(t, g, True):
                count["second listen"] += 1; continue
            if len(g) <= 4 and len(n) <= 4 and g not in terms:
                count["short word"] += 1; filtered.append(f"{mmss(t)} tone '{g}'>'{n}' (one short syllable)"); continue
            report.append(f"  {mmss(t)}  TONE: script '{g}' heard '{n}' (second listen agrees)"); problems += 1; bad_times.append(t)
            continue
        if g.lower() in exceptions or (g and any(g == x or x in g for x in exceptions)) or f"{g}>{n}" in exceptions:
            count["exception"] += 1; continue
        if lang == "en" and tag == "replace" and compact_en(g) == compact_en(n):
            count["same words"] += 1; continue   # the same words spelled two ways, not a misreading
        if tag == "replace" and len(g) <= 2 and len(n) <= 2:
            continue
        if tag == "insert" and n.strip() in ("percent", "phan cham", "phần trăm"):
            continue  # Whisper adds "%" after a number from context
        if tag in ("insert", "replace") and n and INVENTED.search(n):
            count["invented"] += 1; filtered.append(f"{mmss(t)} {tag} '{g}'>'{n}' (common invented phrase)"); continue
        if tag == "insert" and tl and not a.only_lines and line_at(t, 0.3) is None:
            count["outside narration"] += 1; filtered.append(f"{mmss(t)} insert '{n}' (outside every narration line)"); continue
        if g and hear_again(t, g):
            count["second listen"] += 1; continue
        gw, nw = g.split(), n.split()
        if len(gw) <= 1 and len(nw) <= 1 and (gw or nw) and all(len(x) <= 4 for x in gw + nw) and not any(x in terms for x in gw + nw):
            count["short word"] += 1; filtered.append(f"{mmss(t)} {tag} '{g}'>'{n}' (short word)"); continue
        report.append(f"  {mmss(t)}  {tag}: script '{g}' heard '{n}'"); problems += 1; bad_times.append(t)
    scope = "lines " + a.only_lines if a.only_lines else f"{n_ref} script words, {n_heard} heard"
    lines_out = [f"{Path(a.mp3).name}: {scope}, {problems} suspect places (filtered: " +
                 ", ".join(f"{k} {v}" for k, v in count.items()) + ")"] + report
    if filtered:
        lines_out.append("  -- filtered automatically, listed so you can check:")
        lines_out += ["    " + x for x in filtered]
    txt = "\n".join(lines_out) + "\n"
    print(txt)
    out = Path(a.out) if a.out else Path(a.mp3).with_name("voice-review.txt")
    out.write_text(txt, encoding="utf-8")
    if a.timeline:
        bad = sorted({(line_at(t, 0.3) or {}).get("n") for t in bad_times} - {None})
        out.with_name("suspect-lines.json").write_text(json.dumps(bad), encoding="utf-8")
        if bad:
            print("suspect lines:", bad)
    sys.exit(EXIT_SUSPECTS if problems else 0)


if __name__ == "__main__":
    main()
