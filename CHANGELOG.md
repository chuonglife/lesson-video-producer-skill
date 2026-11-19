# Changelog

## v1.2.3 - 2026-11-19

The repository is now plain English for an international audience. Videos render exactly as before: on the example deck the narration, `storyboard.json` and `storyboard.md` are byte-identical before and after, and every script answers `--help` with exit code 0 and no side effect.

- **Claude writes in the language the user types in.** README and SKILL.md say so; the voice follows `"language"` in `slides.json`, which is `en` when the key is missing.
- **No Vietnamese text with tone marks in the docs or the code.** The VieNeu voice is written "Hai Dang" in every doc. The Vietnamese title of the cited video standard is gone; the English title and the credit to its author stay. The Telex note in the screen-recording guide describes what the input method does instead of quoting the garbled word.
- **The VieNeu-TTS engine for Vietnamese narration stays, as one engine among others.** It is selected with `--engine vieneu` or by a deck written in Vietnamese. The language codes of the help texts read `CODE`, and the Kokoro error message names the engine instead of a code.
- **`--voice` accepts VieNeu preset names with or without tone marks.** `--voice "Hai Dang"` finds the preset; an unknown or ambiguous name still goes to VieNeu, which lists its voices. Checked on the 25 presets of VieNeu v3 Turbo: no two names collide once the marks are dropped.
- **Vietnamese data in the scripts is written as `\uXXXX` escapes** with an English comment saying what each string is: number words and "percent" in the voice review, emphasis and pause words in the storyboard and the voice pacing, the wait labels of long takes, the "Opening" label and the voice tags removed from subtitles. Each escaped literal was checked to decode to the original string, and the old and new modules give the same results on a set of Vietnamese test lines. A short Vietnamese line read with VieNeu ("Hai Dang") came out 7.9 s before and 7.8 s after (the model samples, so takes vary by a few percent); a Kokoro English line 10.0 s both times, with the same cache names.

## v1.2.2 - 2026-11-19

Fixes from an audit that followed the README on a clean machine: every item below stopped a new user or gave a wrong result.

### A new user can now get a video

- **The example deck is complete and runs from the repository.** `examples/M04-L02-script-a-video-lesson/` had `slides.json` but no `.pptx` and no slide images, so the only example stopped at step 1 with "Missing ...pptx". It now carries the `.pptx` and `_preview/slide-01..17.png` (1.7 MB, built with Lesson Slide Designer v1.3.1), and its `slides.json` is the one the deck was built from. README has a "Try it" command in bash and PowerShell.
- **The Lesson Slide Designer prerequisite is stated up front.** README said "You give Claude a slide deck" and "Turn my Udemy lecture deck into the final video", which reads as any PowerPoint. The Install section, the table and SKILL.md now say that the deck must come from that skill (`slides.json` + `.pptx` + `_preview/`), and that LibreOffice and Poppler are what it uses to make the previews. They were listed as optional.
- **One preflight before step 1.** `make_video.py` now checks `node`, `ffmpeg`, `ffprobe`, the browser (`CHROME_PATH`), the renderer's `node_modules`, the Python libraries, the voice engine and `--engine files` without `--voice`. Each message names the item, gives the install command for Windows, macOS and Linux and says to open a new terminal. Before, a missing Node or ffmpeg ended in `FileNotFoundError: [WinError 2]` with no hint of what was missing. New `scripts/preflight.py` holds the shared check; `make_voice.py`, `review_voice.py`, `mix_audio.py`, `composite_clips.py`, `check_video.py`, `check_motion.py`, `smooth_scroll.py`, `long_take.py`, the recorders and `render.mjs` use it or give the same message, so none of them shows a traceback for a missing program. A missing or invalid `slides.json` and `video.json` get a plain message too.
- **Japanese and Mandarin.** `pip install kokoro soundfile` is not enough for them: the run passed the voice check and failed at step 2 with `No module named 'pyopenjtalk'` or `'ordered_set'`. The table now gives `pip install "misaki[zh]"` and `"misaki[ja]"`, the preflight imports the extra when the voice is Japanese or Mandarin and prints that command, and the Japanese message says what Windows needs (Visual Studio Build Tools with the C++ workload: `pyopenjtalk` is built from source). Mandarin was run after the fix; Japanese on Windows was not.
- **The voice follows the language.** A deck with `"language": "es"` was read by the US English voice `am_michael`. The default voice now comes from the language (`es` ef_dora, `fr` ff_siwis, `hi` hf_alpha, `it` if_sara, `ja` jf_alpha, `pt` pf_dora, `zh` zf_xiaobei); `--voice` still wins; a language neither engine speaks stops the run with the choices.
- **An existing `.venv` is found.** Started with a bare `python`, the voice message told the user to create an environment "in the skill folder" and install for 25 minutes, even when the project's `.venv` already had the voice. It now looks in the current folder and in the skill folder, names the Python to use, and prints full paths in every command.

### True sizes and waits

- README said the first video downloads "a few hundred MB" and needs "about 3 GB free". Measured: Whisper large-v3 3.1 GB, Kokoro 330 MB (plus a 13 MB spaCy model it installs by itself), VieNeu 580 MB, the environment 1.5 GB, so about 6 GB. Nothing is printed while a model downloads; the first Kokoro line took 17 minutes on a shared connection.
- `WHISPER_MODEL`, `WHISPER_DEVICE` and `CUDA_DLL_DIRS` were in the code only. They are now in README ("Whisper settings") and `references/narration-voice.md`, with when `medium` is acceptable (no NVIDIA GPU or under 16 GB of RAM) and that `small` is for tests. The default stays `large-v3`.
- Step 3 prints its banner (`=== 3/9 voice review ===`) and `loading Whisper <model> on <device>` with the download size. It used to start without a word.
- The espeak-ng note is gone: Spanish and French worked on a clean Windows install without it, because the pip package carries it.
- `requirements.txt` said "8 other languages" for Kokoro: seven.

### Recording

- **`comtypes` is in `requirements.txt`.** `record_actions.py` reads the terminal through UI Automation, which needs it. Without it the script printed one line and went on: no private-text masks, no answers to prompts, no stop on "is not recognized". Now the recording is refused ("RECORDING REFUSED") when the scan is on and UI Automation is not available; `"scan_private": false` in the action script is the only way to record without it. `--dry-run` prints a warning.
- `record_screen.py` checks that ffmpeg has the `gfxcapture` filter (ffmpeg 8.1 or newer) and gives the upgrade command; README and the reference state the minimum version.
- `templates/actions.example.json` used file names the sibling skills do not write. It now uses `lessons/<course>/<lesson>/01_Learning_Objectives.md` and `assessments/<course>/<lesson>/01_Test_Blueprint.md`.

### Picture

- **The video is yuv420p, limited range, BT.709, tagged.** The frames are JPEG screenshots (full range, BT.601) and were encoded without a conversion, so the file came out `yuvj420p` / `bt470bg` although the docs said `yuv420p`; some players and platforms show such a file washed out or too dark. `render.mjs` now converts and tags the stream. Checked on the same deck and timeline before and after: the main colours differ by at most one level out of 255 from the old render and two from the slide image (navy 20,33,61 decoded as 19,33,60 before and 19,32,59 now; the accent 252,163,17 is exact in both), which is the rounding of 8-bit limited-range video, not a visible shift. Segments cached by an older version are rendered again once (the encode version is part of the segment hash).
- `check_video.py` now fails a `yuvj420p` or full-range file, as `references/quality-checks.md` already claimed.

### Smaller things

- `video.json` is read from the output folder and, when there is none, from the folder of `slides.json` (the example keeps it there). Clip paths in it are relative to the folder it is in, in all four scripts that read it.
- `--help` works in every script with exit code 0 and no side effect: `make_sfx.py --help` regenerated all the sounds, `gpu_lock.py --help` returned 2, `insert_artifacts.py --help` printed nothing. Scripts with options now print their full description.
- README: the Claude desktop app section said to upload the `.skill` and run `npm install` in a folder that does not exist on the user's machine. It now says the truth: Claude Code, which includes the Code tab of the desktop app. Prerequisite commands for macOS and Debian/Ubuntu. A short "If something stops" list, including the shared lock file `~/.gpu-lock/gpu.lock`. The example video link points at the v1.0.0 asset (later releases did not carry the mp4).

## v1.2.1 - 2026-11-19

- **A missing voice engine stops the run before step 1, with the fix.** Without Kokoro the run used to build the storyboard and then fail at step 2 with `ModuleNotFoundError: No module named 'kokoro'`. `make_video.py` now imports the engine (`kokoro` + `soundfile`, `vieneu` or `edge_tts`) in the Python it will use and, if that fails, prints the install command for that Python, tells you to create a 3.12 virtual environment first when that Python is 3.13 or newer or not a virtual environment, names `KOKORO_PYTHON` / `VIENEU_PYTHON`, and offers `--engine files` with your own recordings. SKILL.md tells Claude how to set the voice up with the user.
- **Install section: pick the voice engine.** A table of Kokoro (English and seven other languages), VieNeu-TTS (Vietnamese, `pip install vieneu soundfile`, CPU without torch) and your own recordings, the VieNeu line in every install block, `VIENEU_PYTHON` and `setx` next to `KOKORO_PYTHON`, and a one-line voice check (`voice OK`). The FAQ answers "What if Kokoro is not installed?". The intro said "eight other languages" for Kokoro: it is seven.

## v1.2.0 - 2026-11-17

Fixes and features from recording a real course with `record_actions.py`: every item below comes from a take that failed or a video a learner could not follow. Videos without a long take render exactly as before (checked on the example lesson: storyboard and narration byte-identical; a long take without inserts renders frame-identical with identical metrics).

### Recording from an action script (`record_actions.py`)

- **The window is brought to the front, or the take stops.** Keys once went into another window because Windows refused `SetForegroundWindow` (the taskbar held the focus): the clip was empty and the next step failed because a folder had not been created. Now each step tries a synthetic Alt, `AttachThreadInput` to the thread holding the focus, `SwitchToThisWindow`, then a click on the recorded window's own title bar (only if that point belongs to it), up to 6 times 1.5 s apart, because a background program can grab the focus for a moment. If the window is still not in front, the script stops without sending a key.
- **PowerShell windows find `claude`.** `wt.exe` opens a tab inside the Windows Terminal process that is already running, with the PATH it had when it started, so typing `claude` answered "is not recognized". A PowerShell window now runs a small `.ps1` silently before its prompt: the PATH of the recording process plus the Machine and User PATH from the registry, an alias from `claude` to the real executable (the npm shim is not found inside the Terminal session even with the right PATH), and no `CLAUDE_*` variables. Give Claude about 8 s to start (`{"pause": 8}`), now in the docs.
- **"is not recognized" stops the take.** After an Enter, if the shell says the command is not recognized, the recording stops at once instead of typing the prompt into PowerShell. `"allow_error": true` on a key step turns it off.
- **New step `if_text`**: `{"if_text": {"text": "...", "goto_mark": "..."}}` skips to a later mark when the text is on screen (case-sensitive, so the typed prompt does not trigger it). Used when a job may already be done and "Continue" is not needed. A jump to a mark that is not later in the script is refused.
- **New step `wait_file`**: for jobs of an hour or more, where Claude Code works in the background and hands the turn back several times, so a still screen says nothing. It waits for the result file, types a nudge such as "Continue" every `nudge_every` seconds only while the busy text is not on screen, and answers prompts like `wait_done`. The nudge is checked for private text like any typed string.
- **A warning before `/exit`.** Claude Code once handed the turn back while `pip install kokoro` still ran in the background; `/exit` showed "Background work is running", Enter picked "Exit and stop tasks" and the install was killed. Every `/exit` in a script now prints a warning to wait for Claude to report the work done first.
- **New `scripts/close_recording_windows.py`**: closes windows left from an earlier take one tab at a time (Ctrl+C twice, then Ctrl+Shift+W). Closing a multi-tab window as a whole showed "Do you want to close all tabs?", which ended up in the next clip.

### Showing the real artifact in a long take

- **New `scripts/insert_artifacts.py`, `inserts` in `<clip>.longtake.json`.** A test viewer saw "Done" in the terminal but never the document Claude had written. Now, right after a result, the long take can show the real file: .docx/.pdf pages (LibreOffice and Poppler), .md/.txt/.json/.csv as large text, a deck (its slide images, overview first), an image, or part of a video with its sound. It is built from the file at render time, no extra window recorded, with an "Opening: <file>" label on a 132 px band kept free at the top. Each insert is a segment of its own, so it carries its own narration, stretches or shrinks (at most 30%, never a video) to fit it, and `fit` writes `pause_after` on the insert itself. `long_take.py`, `composite_clips.py` (mixes a video insert's sound, at 0.35 under narration) and `check_video.py` (lists inserts; their fades are not jumpy scrolls) know about it. The audio mix gives the base track its own label before `amix`; without it ffmpeg stops with "Trailing garbage after a filter", as it did in the first take with a video insert.
- Text inserts read files with a byte order mark correctly (a BOM had turned "# Title" into plain text).

### Voice and sound

- **`review_voice.py` stops less often for nothing.** In English it compares a compact form (number words as digits, no spaces or hyphens), so "lesson two" / "lesson 2" and "mac os" / "macos" are equal; a review once stopped the whole run after three regenerations of a line that was read correctly. New `assets/whisper-homophones-en.txt`: `said>heard` pairs every English review accepts (Whisper writes "clawed", "cloud" or "clod" for Claude, "jason" for JSON, "forth" for fourth). The report counts them under "same words" and "exception".
- `make_voice.py`: Kokoro now reads its own name right ("Kokoro" -> "Koh-koh-roh" in the Kokoro pronunciation table).
- `make_video.py` and `mix_audio.py`: the music bed defaults to **-28 dB** instead of -22, which sounded loud under the voice. `--music-db -22` gives the old level.

### Voice and picture in sync (the picture never trails the voice)

Found by timing a real course: the voice started 0.24 s before the picture arrived on every slide, regions appeared after the sentence that mentioned them, and some scenes flashed for under a second. Videos built from an older storyboard (no `"sync"` key) keep the old timing; run `storyboard.py` again to get the new one.

- **The slide enters before its first line.** `storyboard.json` now has `"sync": 1` and a `lead_wait` per slide (transition time + 0.4 s). `render.mjs` / `video.js` start the transition so the picture has settled when the voice starts, and never change slide while the previous slide's voice or countdown is still running. `make_voice.py` widens the silence at a slide change when the real gap is too short, and writes `speech_start` / `speech_end` (when the voice really starts and stops, ignoring the silence at the edges of each voice file) into the timeline.
- **A region finishes 0.3 s before the line that mentions it.** Regions of one line are staggered by 0.25 s and the last one finishes 0.3 s early. Automatic circles and the pointer follow `speech_start`, not the line start.
- **Each region is assigned to the first line that mentions it** (`storyboard.py`, `match_regions`): word and word-pair matching with rare words weighted up, ideas of multi-idea cards matched one by one, names and numbers that open an idea counted on their own. Before, regions were spread evenly, so a sentence could be spoken a line or two before its card appeared.
- **Ordered slides keep their order.** Process steps, table rows and lists numbered 1, 2, 3... appear in position order; a build check (`SHOW ORDER ERROR`) refuses a narration that would show a later step first (`"order": false` in video.json to allow it).
- **Closing, question and key-message slides show at most two regions per line**, so the last region does not finish after the voice.
- **A bullet list in one text box is split into one region per paragraph** (measured on the slide image), so it no longer appears all at once while the voice reads it item by item.
- **A clip that covers its slide** (`"mode": "full"` long take) replaces the slide image with the first frame of the edited clip (`long_take.py first-frame`), so the placeholder slide does not flash before and after the clip; the clip fades in over 0.12 s and carries a 3.8 s stage label (the slide's label and title). New storyboard keys: `lead_wait`, `covers_clip`, `clip_label`; the render plan (`events.json`) now lists `entered`, `reveals`, `circles` and `cursor_marks`.
- **Hand-drawn circles are scored, not only triggered by emphasis words.** Every region gets a score (emphasis word in its line, the big number of a big-numbers slide, the last table row, word overlap with the line being read); the best one or two (three with three emphatic lines) are circled, at most one per line, for at least 2.2 s so they never flicker. Auto circles now also work on two-column, agenda, chart and key-message slides, and more emphasis phrases count ("only", "notice", "the answer", "that is why").
- **The teaching pointer is on by default for English lessons** (it was off): it moves to the region being explained and rests outside the text. `{"_all": {"cursor": false}}` turns it off; other languages stay off by default.
- `make_video.py`: the language is read from `slides.json` when `--lang` is not given; a `--lang` that differs from the deck stops the run instead of mixing languages.

### Machine checks added to `check_video.py`

New `--storyboard` option (passed by `make_video.py`; derived from `--events` otherwise). Hard failures when the storyboard has `"sync": 1`, warnings otherwise:

- the voice of a slide starts at least 0.15 s after the slide has arrived;
- a region has finished appearing before the line that mentions it starts;
- process and table regions appear in position order;
- no slide is on screen for less than 2 s; no scene of a long take (the picture between two changes of picture) lasts under 1.5 s; the placeholder slide never flashes for 0.05 to 1.5 s around a full-screen clip;
- a clip's slide is not counted as short; the report lists the circle and pointer counts.

### Long takes and compositing

- Cuts of 90 minutes or more are labelled "3.5 hours later" instead of "210 min later".
- Anti-flicker rules in `long_take.py`: a cut is never shorter than 2 s (`cut_seconds` default 2.4), a wait core under 3 s plays at normal speed, a fast-forward is never shorter than 1.5 s, and an action fragment under 1.5 s squeezed between two cuts or inserts is merged into the neighbour (`merge_crumbs`). `<out>.metrics.json` lists the scenes.
- New in `long_take.py`: `first-frame`, `render --stage-label`, automatic callout frames around the text that appeared before each reading segment (`callouts`, `auto_callouts`), a `bg` mask for an OS dialog that got into the frame; the picture of a narration group changes 0.4 s before its voice.
- `composite_clips.py`: under sync a clip window starts and ends with the slides' real transition times (`clip_window`, `line_marks`); the final mix always passes `alimiter=limit=0.75` (peak at most -2.5 dBFS; a real video insert had peaked at -0.1 dBTP) and the AAC encoder runs with `-aac_pns 0`; new `--self-test` for the insert sound mix.
- `insert_artifacts.py`: `"static": true` renders one still frame of a text insert (error when the text does not fit; fewer `lines`), `"outline": [{"from", "to", "box"}]` draws a frame around a region and follows the zoom.
- `smooth_scroll.py`: a very long scroll now drops source frames instead of inserting new ones, so the clip keeps its length and later timestamps do not move; `--fixed-top PX` for a tab strip or title bar that must not scroll; `--segments <clip.longtake.json>` smooths only the worthwhile pieces of a long take and restores each piece's exact length.

### Voice review

- `review_voice.py`: multi-word English numbers are merged before comparing ("twenty one" = "21", "one hundred" = "100", "a hundred and thirty five" = "135"); the second listen is no longer primed with the script line (priming made Whisper copy the script and hide real misreadings); an exception excuses a heard word only on an exact whole-phrase match, and entries longer than 3 words are ignored and listed; tone mismatches that remain after the second listen go into a "LISTEN BY HAND" list instead of being dropped.

### Docs

- README: recording from an action script is the default way to record a how-to; optional LibreOffice and Poppler in "Before you start".
- SKILL.md: principles describe the new timing, circles and pointer; `references/motion-and-sound.md` has a voice-picture timing section; `references/screen-recording.md` sections 6.6 to 6.8.
- SKILL.md: step 2b covers `wait_file`, `if_text`, the 8 s start, `close_recording_windows.py` and the artifact inserts; step 4 adds "watch it as a learner would".
- `references/screen-recording.md`: section 6.1 (PowerShell start, focus, the two new steps, background work and `/exit`) and a new section 6.5 (inserts). `references/narration-voice.md` and `references/motion-and-sound.md` updated.

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
- `record_screen.py`: `--log-events` (off by default) writes an action log of clicks, keys and combos with frame-accurate seconds (x264 zerolatency), only while the recorded window is in front; `--hide-typing` never writes typed characters; `--no-cursor`. With the log on, the mp4 is fragmented and stopped with Ctrl+Break, so a closed or still window no longer loses the whole clip; it stops when the window closes. It warns when a Vietnamese input method (UniKey, EVKey, OpenKey) runs or the keyboard is not en-US, and the action table warns about accented characters in the key log (a Telex input method had rewrote "for lesson" as it typed (it reads the "r" after a vowel as a tone mark, and the second "s" too)).
- `storyboard.py` takes a long-take slide's narration from the config in groups; `make_video.py` runs `long_take.py fit` after the voice and skips long takes in `--extend`; `composite_clips.py` renders the edited clip (cached by hash in `clips/_longtake/`) and lays it over 1:1; `check_video.py` reports seconds cut, fast-forwards and speeds, seconds held, zoom boxes, zoom step and jerk, clicks, key labels and masks, fails an action piece above 1.25x and ignores jumps inside fast or cut pieces.
- Docs: SKILL.md step 2b, `references/screen-recording.md` section 6, `templates/actions.example.json`, a long-take line in `templates/video.example.json`.

## v1.0.0 - 2026-11-12

First public release.
