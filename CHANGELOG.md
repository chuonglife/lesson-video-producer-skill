# Changelog

## v1.1.0 - 2026-11-17

Install fixes from a test run as a new user on Windows 11 (Python 3.12 in a venv, Node, ffmpeg).

- README: the Python requirement is now Python 3.10 to 3.12, not "3.10+". Kokoro declares `<3.13`, so a machine whose default Python is 3.13 or newer failed to install the voice.
- README: full command blocks for the "one project only" install, which used to be one sentence, and for the personal install, each in bash and in PowerShell (no `&&`, `export` or `~`; `$HOME\.claude\skills\...`).
- README: install into a `.venv` (in the project, or in the skill folder for the personal install) instead of the system Python.
- README: a "Before you start" table of the outside software (Python, Node 18+, ffmpeg/ffprobe on the PATH, Chrome/Chromium/Edge, git, free disk space) with the `winget` command for each on Windows; GPU optional; the first run downloads the voice model and Whisper.
- README: measured install times (requirements 318 s, `kokoro soundfile` 915 s with a silent pip while torch downloads, npm 37 s; venv 1.5 GB), a `--help` check after installing, and `KOKORO_PYTHON` in PowerShell.
- `requirements.txt`: `pywin32` is installed on Windows (environment marker) for `record_screen.py`; it used to be a comment only. The Python range is stated at the top.
- SKILL.md: Claude runs the scripts with the project's `.venv` Python when there is one (`.venv/Scripts/python` on Windows, `.venv/bin/python` elsewhere), otherwise `python`. The Python range is corrected there too.
- `make_video.py`: the "install the renderer" message prints `npm install --prefix "<engine>"`, which works in PowerShell 5.1 as well as bash. The sub-steps already ran with `sys.executable`, so a run started from the venv stays in it.

### Long-take mode: long how-to lessons that are mostly screen recording

For lessons where a real tool (for example Claude Code) works for minutes on end and the recording is most of the video. Record first, write the narration after. Videos that do not declare `long_take` render exactly as before (checked: storyboard, narration, compositing and report byte-identical on an existing lesson).

- New `scripts/record_actions.py`: records from an action script (`templates/actions.example.json`), the default way to record software how-tos. It opens Windows Terminal, types like a person with KEYEVENTF_UNICODE (an input method cannot alter the text), presses keys, waits for a still window, for a text, or for a program to finish (`wait_done`, with automatic answers to prompts), scrolls, clicks, sets marks, stops by itself and runs the analysis. It reads the terminal text with UI Automation (visible part only) and turns emails, API keys and `C:\Users\<name>` paths on screen into timed masks; typed strings that look private refuse the script unless marked `secret`. Tested with a real Claude Code 2.1 session (trust prompt, a prompt, the work, the result review).
- Required `review_result` step after every job: scroll to the start of the answer and read down at 120 to 200 px/s with a stop per chunk, open the text files the job wrote in a new tab of the recorded window. A script without it is refused unless `--skip-review "<reason>"`. Reading segments are never treated as waits, never fast-forwarded or cut, and the table asks for narration that explains the result.
- New `scripts/long_take.py`: `analyse` finds waits (frame-difference threshold, adjustable, never around input events, marks or reading segments) and writes `<clip>.longtake.json` plus an action table (`.action-table.md` and picture sheets) to write the narration from; `render` builds the edited clip: waits fast-forwarded (8x, up to 16x, with an "8× speed" label) or cut (with a "4 min later" label), zoom and pan with smootherstep easing in output time, a ripple at clicks, a key label in the corner, privacy masks; `fit` adds a pause after a narration group whose picture cannot shrink further. Action pieces are never faster than 1.25x; only waits are exempt.
- `record_screen.py`: `--log-events` (off by default) writes an action log of clicks, keys and combos with frame-accurate seconds (x264 zerolatency), only while the recorded window is in front; `--hide-typing` never writes typed characters; `--no-cursor`. With the log on, the mp4 is fragmented and stopped with Ctrl+Break, so a closed or still window no longer loses the whole clip; it stops when the window closes. It warns when a Vietnamese input method (UniKey, EVKey, OpenKey) runs or the keyboard is not en-US, and the action table warns about accented characters in the key log (a Telex input method had turned "for lesson" into "fỏ leson").
- `storyboard.py` takes a long-take slide's narration from the config in groups; `make_video.py` runs `long_take.py fit` after the voice and skips long takes in `--extend`; `composite_clips.py` renders the edited clip (cached by hash in `clips/_longtake/`) and lays it over 1:1; `check_video.py` reports seconds cut, fast-forwards and speeds, seconds held, zoom boxes, zoom step and jerk, clicks, key labels and masks, fails an action piece above 1.25x and ignores jumps inside fast or cut pieces.
- Docs: SKILL.md step 2b, `references/screen-recording.md` section 6, `templates/actions.example.json`, a long-take line in `templates/video.example.json`.

## v1.0.0 - 2026-11-12

First public release.
