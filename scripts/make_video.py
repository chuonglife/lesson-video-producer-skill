#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
MAKE THE LESSON VIDEO with ONE COMMAND from an existing deck (slides/<course>/<lesson>/slides.json + .pptx + _preview/slide-NN.png).

Usage:
  python make_video.py <slides.json> [--lang CODE] [--engine kokoro|vieneu|edge|files] [--voice NAME or folder]
                       [--no-music] [--music-db -28] [--no-sfx] [--extend] [--skip-review]
                       [--from-step N] [--workers 2] [--crf 18] [--full-render]

Before step 1 everything the run needs is checked: node, ffmpeg, ffprobe, a browser (Chrome, Chromium or Edge; CHROME_PATH),
the renderer's node_modules, the Python libraries and the voice engine. A missing item stops the run with its install command.

Steps (everything is written to videos/<course>/<lesson>/; a deck outside a "slides" folder goes to <slides folder>/video/):
  1. storyboard.py     slides.json + pptx -> narration.txt, storyboard.json, storyboard.md
                       (reads video.json: the output folder first, then the folder of slides.json)
  2. make_voice.py     narration.txt -> <name>.voice.mp3 + timeline.json   (through gpu_lock). "language" is en when missing.
                       The voice follows "language" in slides.json: en am_michael, es ef_dora, fr ff_siwis, hi hf_alpha,
                       it if_sara, ja jf_alpha, pt pf_dora, zh zf_xiaobei (Kokoro); the VieNeu-TTS engine for Vietnamese
                       narration with --engine vieneu; --voice picks another; other languages stop the run
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
otherwise the current Python is used. Whisper: WHISPER_MODEL (default large-v3, 3.1 GB; medium on a machine without a GPU
or with little memory), WHISPER_DEVICE (cuda | cpu), CUDA_DLL_DIRS (Windows, extra folders with the CUDA DLLs).
"""
import argparse
import importlib.util
import json
import os
import shutil
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
sys.path.insert(0, str(HERE))
import preflight  # noqa: E402


def run(cmd, step):
    print(f"\n=== {step} · {time.strftime('%H:%M:%S')} ===")
    print("+", " ".join(f'"{c}"' if " " in str(c) else str(c) for c in cmd), flush=True)
    try:
        code = subprocess.run([str(c) for c in cmd]).returncode
    except FileNotFoundError:
        raise SystemExit(f"STOPPED at {step}: {preflight.tool_message(Path(str(cmd[0])).name)}")
    if code:
        raise SystemExit(f"STOPPED at {step}")


def duration(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)], capture_output=True, text=True)
    return float(r.stdout.strip() or 0)


VOICE_MODULES = {"kokoro": "kokoro, soundfile", "vieneu": "vieneu", "edge": "edge_tts"}
# Kokoro: the default voice of each language (the first letter of a voice is its language code). An explicit --voice wins.
KOKORO_VOICES = {"en": "am_michael", "es": "ef_dora", "fr": "ff_siwis", "hi": "hf_alpha", "it": "if_sara", "ja": "jf_alpha",
                 "pt": "pf_dora", "zh": "zf_xiaobei"}
# Kokoro languages that need one more package than `pip install kokoro`: voice letter -> (import to try, pip package, language)
KOKORO_EXTRAS = {"j": ("from misaki import ja", "misaki[ja]", "Japanese"), "z": ("from misaki import zh", "misaki[zh]", "Mandarin")}
PY_MODULES = [("pptx", "python-pptx"), ("numpy", "numpy"), ("PIL", "Pillow")]
REVIEW_MODULES = [("faster_whisper", "faster-whisper"), ("ctranslate2", "ctranslate2")]
JA_WINDOWS = ("Japanese pulls pyopenjtalk, which pip builds from source. On Windows that needs a C++ compiler and CMake: install "
              "Visual Studio Build Tools with the \"Desktop development with C++\" workload "
              "(winget install Microsoft.VisualStudio.2022.BuildTools, then add the workload in the Visual Studio Installer), "
              "open a new terminal and run the pip command again. On macOS (Xcode command line tools) and Linux "
              "(build-essential, cmake) the build normally works as is.")


def venv_python(folder):
    return Path(folder) / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def probe_voice(py_tts, engine, extra=None):
    """(Python version, in a virtual environment, engine imports, language extra imports) for one Python."""
    code = ("import sys\nprint('%d.%d' % sys.version_info[:2])\nprint(int(sys.prefix != sys.base_prefix))\n"
            f"try:\n    import {VOICE_MODULES[engine]}\n    print('BASE_OK')\nexcept Exception as e:\n    print('BASE_FAIL', repr(e)[:200])\n")
    if extra:
        code += f"try:\n    {extra}\n    print('EXTRA_OK')\nexcept Exception as e:\n    print('EXTRA_FAIL', repr(e)[:200])\n"
    try:
        out = subprocess.run([str(py_tts), "-c", code], capture_output=True, text=True, timeout=900).stdout
    except Exception:
        out = ""
    lines = out.strip().splitlines() + ["?", "?"]
    return lines[0], lines[1] == "1", "BASE_OK" in out, (not extra) or "EXTRA_OK" in out


def check_voice_engine(engine, py_tts, voice=None):
    """Stop before step 1 when the voice engine is not installed, with the exact fix, instead of failing at step 2."""
    if engine not in VOICE_MODULES:
        return
    extra = KOKORO_EXTRAS.get((voice or "a")[0]) if engine == "kokoro" else None
    ver, in_venv, base_ok, extra_ok = probe_voice(py_tts, engine, extra and extra[0])
    if base_ok and extra_ok:
        return
    env = {"kokoro": "KOKORO_PYTHON", "vieneu": "VIENEU_PYTHON"}.get(engine)
    if base_ok:   # Kokoro is there, the Japanese or Mandarin text front end is not
        _, pkg, language = extra
        msg = [f"The Kokoro voice is installed, but {language} (voice {voice}) needs one more package in this Python: {py_tts} (Python {ver}).",
               f"Install it once: \"{py_tts}\" -m pip install \"{pkg}\""]
        if pkg == "misaki[ja]":
            msg.append(JA_WINDOWS)
        msg.append("Or use your own recordings: --engine files --voice <folder with 001.wav, 002.wav, ...>.")
        raise SystemExit("\n".join(msg))
    msg = [f"The {engine} voice is not installed in this Python: {py_tts} (Python {ver})."]
    if engine in ("kokoro", "vieneu"):
        fits = lambda v: v != "?" and (engine != "kokoro" or (3, 10) <= tuple(map(int, v.split("."))) < (3, 13))
        # an environment made by the README install: the project's .venv (current folder) or the .venv in the skill folder
        found = []
        for folder in (Path.cwd(), HERE.parent):
            vp = venv_python(folder)
            if vp.is_file() and vp.resolve() != Path(py_tts).resolve() and vp not in found:
                found.append(vp)
        probes = {vp: probe_voice(vp, engine) for vp in found}
        ready = next((vp for vp in found if probes[vp][2]), None)
        if ready:
            raise SystemExit("\n".join(msg + [
                f"It IS installed in this environment: {ready}",
                f"Run the same command with that Python: \"{ready}\" \"{Path(__file__).resolve()}\" <slides.json> ...",
                f"(or set {env} to that path; the Python that runs make_video.py then still needs requirements.txt)."]))
        target = py_tts
        if not fits(ver) or not in_venv:
            why = "Kokoro needs Python 3.10, 3.11 or 3.12 (it does not install on 3.13 or newer)" if not fits(ver) else "This is not a virtual environment"
            usable = next((vp for vp in found if fits(probes[vp][0])), None)
            if usable:
                target = usable
                msg.append(f"{why}. There is an environment at {usable}: install the voice there, then run make_video.py with that Python.")
            else:
                target = venv_python(Path.cwd())
                msg.append(f"{why}. Create a Python 3.12 environment first: "
                           f"{'py -3.12' if os.name == 'nt' else 'python3.12'} -m venv \"{target.parent.parent}\"")
                msg.append(f"then: \"{target}\" -m pip install -r \"{HERE.parent / 'requirements.txt'}\"")
                msg.append(f"and run make_video.py with \"{target}\".")
        if engine == "kokoro":
            msg.append(f"Install the voice once (about 15 minutes, pulls torch; pip stays silent while it downloads): "
                       f"\"{target}\" -m pip install kokoro soundfile")
            if extra:
                msg.append(f"{extra[2]} also needs: \"{target}\" -m pip install \"{extra[1]}\""
                           + (" (on Windows this builds pyopenjtalk: Visual Studio Build Tools with the C++ workload first)"
                              if extra[1] == "misaki[ja]" else ""))
        else:
            msg.append(f"Install the voice once (CPU, no torch): \"{target}\" -m pip install vieneu soundfile "
                       "(NVIDIA GPU: see https://github.com/pnnbao97/VieNeu-TTS).")
    else:
        msg.append(f"\"{py_tts}\" -m pip install edge-tts")
    if env:
        msg.append(f"If it is installed in another environment, set {env} to that python.exe.")
    msg.append("No install possible? Use your own recordings: --engine files --voice <folder with 001.wav, 002.wav, ...> "
               "(or --engine edge to test the pipeline only; do not publish with it).")
    raise SystemExit("\n".join(msg))


def check_programs(review):
    """Everything a run needs besides the voice, checked before step 1: node, ffmpeg, ffprobe, a browser, the renderer's
    node_modules and the Python libraries. One line per missing item, with the install command."""
    problems = [preflight.tool_message(n) for n in preflight.missing_tools("node", "ffmpeg", "ffprobe")]
    if not preflight.find_browser():
        problems.append(preflight.browser_message())
    if not (ENGINE / "node_modules" / "puppeteer-core").is_dir():
        problems.append(f"The frame renderer is not installed yet. Install it once: npm install --prefix \"{ENGINE}\"")
    missing = [pkg for mod, pkg in PY_MODULES + (REVIEW_MODULES if review else []) if importlib.util.find_spec(mod) is None]
    if missing:
        other = next((vp for vp in (venv_python(Path.cwd()), venv_python(HERE.parent))
                      if vp.is_file() and vp.resolve() != Path(sys.executable).resolve()), None)
        problems.append(f"Python libraries missing in {sys.executable}: {', '.join(missing)}. "
                        + (f"There is an environment at {other}: run make_video.py with that Python (\"{other}\" \"{Path(__file__).resolve()}\" ...). "
                           if other else "You are probably on the wrong Python: run make_video.py with the environment that has requirements.txt. ")
                        + f"Or install them here: \"{sys.executable}\" -m pip install -r \"{HERE.parent / 'requirements.txt'}\"")
    if problems:
        raise SystemExit("Cannot start. Fix this first:\n- " + "\n- ".join(problems))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slides")
    ap.add_argument("--lang", metavar="CODE", help="optional; must match \"language\" in slides.json, which is used when omitted (default en)")
    ap.add_argument("--engine", choices=["kokoro", "vieneu", "edge", "files"])
    ap.add_argument("--voice", help="a voice name (Kokoro: am_michael, af_heart, ef_dora, ...); with --engine files, the folder of recordings")
    ap.add_argument("--no-music", action="store_true")
    ap.add_argument("--music-db", type=float, default=-28)  # -22 sounded loud under the voice
    ap.add_argument("--no-sfx", action="store_true")
    ap.add_argument("--extend", action="store_true")
    ap.add_argument("--skip-review", action="store_true")
    ap.add_argument("--from-step", type=int, default=1)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--crf", type=int, default=18)
    ap.add_argument("--full-render", action="store_true")
    a = ap.parse_args()
    src = Path(a.slides).resolve()
    if not src.is_file():
        raise SystemExit(f"slides.json not found: {src}")
    try:
        spec = json.loads(src.read_text(encoding="utf-8-sig"))
    except ValueError as e:
        raise SystemExit(f"{src} is not valid JSON: {e}")
    name = spec.get("file_name") or spec.get("ten_tep") or src.stem
    spec_lang = spec.get("language") or "en"
    if a.lang and a.lang != spec_lang:
        raise SystemExit(f"--lang {a.lang} differs from \"language\": \"{spec_lang}\" in {src.name}: drop the option or fix slides.json "
                         "(the deck, the narration and the voice must be the same language)")
    lang = a.lang or spec_lang   # no option: the language comes from slides.json
    base_lang = str(lang).replace("_", "-").split("-")[0].lower()
    parts = list(src.parent.parts)
    out = Path(*[("videos" if p == "slides" else p) for p in parts]) if "slides" in parts else src.parent / "video"
    engine = a.engine or ("vieneu" if base_lang == "vi" else "kokoro")
    check_programs(review=a.from_step <= 3 and not a.skip_review and engine not in ("edge", "files"))
    voice_name = a.voice
    if engine == "files":
        if not a.voice:
            raise SystemExit("--engine files needs --voice <folder>: one recording per narration line, named 001.wav, 002.wav, ... "
                             "(any format ffmpeg reads). Run storyboard.py first to get <name>.narration.txt, the lines to record.")
        if not Path(a.voice).is_dir():
            raise SystemExit(f"--voice {a.voice}: this folder does not exist. With --engine files it must hold 001.wav, 002.wav, ...")
    elif engine == "kokoro" and not a.voice:
        if base_lang not in KOKORO_VOICES:
            raise SystemExit(
                f"No local voice for \"language\": \"{lang}\". Kokoro speaks {', '.join(sorted(KOKORO_VOICES))}; the VieNeu-TTS engine (--engine vieneu) reads Vietnamese. "
                "Either record the lines yourself (--engine files --voice <folder with 001.wav, 002.wav, ...>), or force a "
                "Kokoro voice with --voice <name> if you have heard it read this language acceptably.")
        voice_name = KOKORO_VOICES[base_lang]
    py = sys.executable
    py_tts = {"kokoro": os.environ.get("KOKORO_PYTHON", py), "vieneu": os.environ.get("VIENEU_PYTHON", py), "edge": py, "files": py}[engine]
    if not Path(py_tts).is_file():
        raise SystemExit(f"Python for {engine} not found: {py_tts}")
    if a.from_step <= 3:
        check_voice_engine(engine, py_tts, voice_name)
    out.mkdir(parents=True, exist_ok=True)
    f = lambda ext: out / f"{name}{ext}"
    narration, board, voice, tl, events, audio, base, final = (f(".narration.txt"), f(".storyboard.json"), f(".voice.mp3"), f(".timeline.json"),
                                                              f(".events.json"), f(".audio.mp3"), f(".base.mp4"), f(".mp4"))
    # video.json: the output folder first, then next to slides.json; clip paths in it are relative to the folder it is in
    overrides = out / "video.json"
    if not overrides.is_file() and (src.parent / "video.json").is_file():
        overrides = src.parent / "video.json"
        print(f"overrides: {overrides} (no video.json in {out})")
    check = out / "_check"; check.mkdir(exist_ok=True)
    gpu = [py, HERE / "gpu_lock.py", "--"]

    def steps_1_to_4(start=1):
        run([py, HERE / "storyboard.py", src, "--overrides", overrides], "1/9 storyboard")
        tts = gpu + [py_tts, HERE / "make_voice.py", narration, voice, tl, "--engine", engine] + (["--voice", voice_name] if voice_name else [])
        if start <= 2:
            run(tts, "2/9 narration")
        if start <= 3 and not a.skip_review and engine not in ("edge", "files"):
            review = gpu + [py, HERE / "review_voice.py", voice, narration, "--lang", lang, "--out", check / "voice-review.txt",
                            "--exceptions", check / "voice-exceptions.txt", "--timeline", tl]
            print(f"\n=== 3/9 voice review (Whisper listens back) · {time.strftime('%H:%M:%S')} ===", flush=True)
            r = subprocess.run([str(c) for c in review])
            suspects = check / "suspect-lines.json"
            for round_ in range(3):
                if r.returncode not in (0, 3):
                    raise SystemExit(f"STOPPED at 3/9: the voice review itself failed (exit code {r.returncode}); see the error above. "
                                     "Fix faster-whisper (pip install faster-whisper; on Windows the CUDA libraries, or set WHISPER_DEVICE=cpu; "
                                     "out of memory: WHISPER_MODEL=medium) "
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
                if not c or c.get("long_take"):
                    continue   # a long take fits group by group (long_take.py fit), not the whole slide
                cf = Path(c["file"]); cf = cf if cf.is_absolute() else overrides.parent / cf
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
        if overrides.is_file() and any(isinstance(v, dict) and (v.get("clip") or {}).get("long_take")
                                       for v in json.loads(overrides.read_text(encoding="utf-8")).values()):
            # long take: a group whose picture cannot shrink to its narration (actions never above 1.25x) gets a pause, then 1-4 again
            for _ in range(3):
                r = subprocess.run([str(c) for c in [py, HERE / "long_take.py", "fit", board, tl, overrides]])
                if r.returncode == 0:
                    break
                if r.returncode != 3:
                    raise SystemExit(f"STOPPED at 4/9: long_take.py fit failed (exit code {r.returncode})")
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
    run([py, HERE / "check_video.py", final, "--timeline", tl, "--events", events, "--storyboard", board], "9/9 final check")
    print(f"\nDONE: {final}\nLook at {check}/contact-*.png, report: {check}/{name}.report.md")


if __name__ == "__main__":
    main()
