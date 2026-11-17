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

## v1.0.0 - 2026-11-12

First public release.
