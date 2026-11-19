---
name: lesson-video-producer
description: Turn a lesson slide deck (slides.json + .pptx + slide images from the lesson-slide-designer skill) into a finished narrated lesson video (1080p mp4) with a local text-to-speech voice (Kokoro for English and 7 other languages, optional VieNeu-TTS for Vietnamese), every card and step revealed in sync with the narration, varied transitions, hand-drawn attention circles, sound effects and a ducked piano bed, pause countdowns, separate .vtt/.srt subtitles, real screen recordings with smooth scrolling for how-to lessons, and a measured quality report. Follows instructional video standards (one topic per video, script, open-body-close, transitions, interaction). Re-renders only changed slides. Use this skill whenever the user wants to make, render or export a lesson video, a course video, a Udemy lecture, a narrated slideshow, a voice-over for slides, an explainer from a deck, or a screen recording in a lesson, even if they only say "turn these slides into a video". Not for making the slides or writing the lesson.
---

# Lesson Video Producer

Turn the slide deck of **one lesson** into a **finished teaching video**: a synthetic voice reads the narration, each card, step or row appears exactly when the voice reaches it, transitions vary, soft sound effects mark each reveal, a piano bed ducks under the voice, a countdown runs where learners pause, key items get a hand-drawn circle, subtitles come as separate files, and real screen recordings slot into how-to lessons. One lesson at a time; run it, look at it, then hand it over.

Input, from the `lesson-slide-designer` skill: `slides/<course>/<lesson>/slides.json`, `<file_name>.pptx` and `_preview/slide-NN.png`. All three are required: an ordinary PowerPoint without `slides.json` cannot be rendered, so if the user only has a .pptx or a lesson text, build the deck with that skill first (it needs LibreOffice and Poppler for the `_preview` images); if that skill is not installed, say so. Decks from the Vietnamese edition (`kieu`, `loi_doc`, `_kiem/`) are read too. When this skill was installed with `git clone`, a complete example deck is in its `examples/M04-L02-script-a-video-lesson/` folder (the `.skill` download does not carry it); `python scripts/make_video.py <that folder>/slides.json` renders it and is the quickest way to test an install.

Output in `videos/<course>/<lesson>/` (mirrors the slides path; otherwise `<slides folder>/video/`):

| File | What it is |
|---|---|
| `<file_name>.mp4` | **The video**: 1920x1080, 30 fps, H.264 yuv420p (limited range, BT.709), AAC 48 kHz, -16 LUFS |
| `<file_name>.<lang>.vtt` / `.srt` | Subtitles as **separate files**, never burned in (they would cover slide text); upload the .vtt as captions |
| `<file_name>.narration.txt` | Clean narration, one spoken beat per line; `|N` adds N seconds of silence |
| `<file_name>.storyboard.json` / `.md` | What happens when: regions measured from the pptx, the line each one appears on, effects, transitions, circles, zooms, countdowns; the .md is for reviewing by eye |
| `<file_name>.voice.mp3` + `.timeline.json` | The narration and the exact start and end of every line (lines cached in `.voice.mp3.cache/`) |
| `<file_name>.events.json`, `.audio.mp3` | Sound events and the three-layer mix |
| `video.json` (optional, you write it) | Per-slide overrides: reveal lines, transition, hold, circle, zoom, screen recording. Search order: this output folder, then the folder of `slides.json`. Clip paths in it are relative to the folder it is in |
| `_check/` | `contact-NN.png` (frames of the finished video), `<file_name>.report.md` (measurements), `voice-review.txt` (Whisper), `voice-exceptions.txt` |
| `_segments/` | One rendered segment per slide, reused when that slide has not changed |

Tools: Python 3.10 to 3.12 (Kokoro does not install on 3.13+) with `python-pptx`, `numpy`, `Pillow` (`opencv-python` for smoothing recordings, `faster-whisper` for the voice review); Node 18+ with `puppeteer-core` (`npm install` in `assets/engine`) and Chrome, Chromium or Edge; `ffmpeg`/`ffprobe`. Voices: [Kokoro](https://github.com/hexgrad/kokoro) (`pip install kokoro soundfile`; Mandarin also `pip install "misaki[zh]"`, Japanese also `pip install "misaki[ja]"`, which on Windows needs Visual Studio Build Tools with the C++ workload) or [VieNeu-TTS](https://github.com/pnnbao97/VieNeu-TTS) (`pip install vieneu soundfile`), both Apache 2.0 and local. If an engine lives in its own virtual environment, set `KOKORO_PYTHON` or `VIENEU_PYTHON` to that Python. A GPU helps but is optional. On Windows the recorders also need `pywin32` and `comtypes` (both in `requirements.txt`) and ffmpeg 8.1 or newer.

**The preflight.** Before step 1, `make_video.py` checks `node`, `ffmpeg`, `ffprobe`, the browser (`CHROME_PATH`), `assets/engine/node_modules`, the Python libraries, the voice engine (with the Japanese or Mandarin extra when the voice needs it) and `--engine files` without `--voice`. It prints one line per missing item with the install command for Windows, macOS and Linux. Run the command it gives, in a new terminal when it installed a program, then run again. `python scripts/preflight.py` shows the programs it found.

**First run.** The models download without printing anything: Whisper large-v3 3.1 GB at step 3, Kokoro 330 MB or VieNeu 580 MB at step 2. Tell the user before starting so a silent ten minutes does not look like a hang. On a machine without an NVIDIA GPU or with less than 16 GB of RAM set `WHISPER_MODEL=medium` (1.5 GB) before the run; `WHISPER_DEVICE=cpu` forces the CPU when the GPU is busy; say in the report which model reviewed the voice. `small` is for pipeline tests only. Voice and Whisper jobs queue on one lock file (`~/.gpu-lock/gpu.lock`, shared by every project): "[gpu_lock] waiting" means another render holds it (`python scripts/gpu_lock.py --show`).

**Which Python to run.** If the project has a `.venv` folder, run every script with that environment's Python: `.venv/Scripts/python` on Windows, `.venv/bin/python` elsewhere (or the `.venv` inside this skill folder if the user installed it there). Otherwise use `python`. The `python scripts/...` commands below mean that interpreter. `make_video.py` starts the other scripts with the same Python it was started with, so the whole run stays in the environment. If an import fails (`kokoro`, `faster_whisper`, `pptx`), you are on the wrong Python; do not `pip install` into the system Python, point at the venv instead.

**When the voice engine is not installed at all.** `make_video.py` checks the voice before step 1 and stops with the exact fix when `kokoro` (or `vieneu`) cannot be imported. The check itself looks for a `.venv` in the current folder and in this skill folder and, when one of them has the voice, tells you to run with that Python: do that, do not reinstall. If there is none (and no `KOKORO_PYTHON` / `VIENEU_PYTHON`), tell the user the voice is missing and set it up with them: a Python 3.12 virtual environment in the project folder (`py -3.12 -m venv .venv` on Windows, `python3.12 -m venv .venv` elsewhere; the message prints the full paths), then `requirements.txt` and `pip install kokoro soundfile` (Vietnamese: `pip install vieneu soundfile`) into it, run in the background (about 25 minutes the first time, pip is silent while torch downloads), then rerun with that Python. If installing is not possible, offer `--engine files --voice <folder>` with the user's own recordings (one file per narration line). `--engine edge` only tests the pipeline; never deliver a course video made with it.

## Workflow

### Step 0. Read the deck and settle the brief

1. Read `slides.json` (narration, production notes, slide types) and glance at `_preview/contact-sheet.png`. If the lesson source exists, read it to know where learners practise and where they are asked questions.
2. Read `references/video-standards.md` (the standard: one topic, script, open-body-close, transitions, interaction) and `references/motion-and-sound.md` (what each slide type gets, and why the video must move without becoming busy).
3. Settle: language and voice. Write everything (messages, notes, any text you add) in the language the user types in. The voice follows `language` in slides.json, which is `en` when the key is missing (it picks the default voice: `en` Kokoro `am_michael`, `af_heart` for a female voice; `es` `ef_dora`, `fr` `ff_siwis`, `hi` `hf_alpha`, `it` `if_sara`, `ja` `jf_alpha`, `pt` `pf_dora`, `zh` `zf_xiaobei`; Vietnamese narration uses the VieNeu-TTS engine, selected with `--engine vieneu` or by a deck written in Vietnamese; `--voice` overrides; any other language stops the run, so offer `--engine files` with the user's own recordings); whether the lesson needs **real screen recordings** (any lesson that teaches clicks, typing or software: yes, see Step 2); which question slides pause and for how long; anything to circle or zoom. The narration was written for text-to-speech in the slide step. **Do not rewrite the teaching content here**; fix only how a word is pronounced when the voice gets it wrong.

### Step 1. Build the storyboard and review it

```bash
python scripts/storyboard.py slides/<course>/<lesson>/slides.json
```
Read `<file_name>.storyboard.md`: regions per slide, the line each appears on, transitions, holds, circles. Check it against section 4 of `motion-and-sound.md`: the third card appears when the voice reaches the third idea; neighbours never share a transition; question slides hold; a note like "circle answer B" produced a circle. Fix with `video.json` (see `templates/video.example.json`) and run again. "No regions found" means the slide appears whole: fine for `image`, check the pptx for other types.

### Step 2. Real screen recordings (how-to, hands-on and software lessons)

When the lesson teaches an action, show the real action. Never replace it with a screenshot or a mocked-up page. Rules in `references/screen-recording.md`. In short:
1. Prepare the window: a private browser window or a clean account, no notifications, no real names in side bars. On Windows, `python scripts/record_screen.py --list` gives window titles.
2. Record: `python scripts/record_screen.py videos/<course>/<lesson>/clips/S07-name.mp4 --window "<title>" --seconds 40 --size 1280x720 [--crop-top 90] [--scroll "6:200:4"]` (Windows; elsewhere use OBS or ffmpeg). Drive the clicks and typing yourself through browser tools, or let the user do them. **Scroll only with `--scroll` or a smooth in-page scroll** (`window.scrollBy({top: 200, behavior: 'smooth'})` every 0.6 to 0.8 s), never notch by notch. Hold still 3 to 5 s after each result; scroll long results slowly (150 to 250 px/s) so learners can read them.
3. `check_motion.py` runs after each recording. Any jump left: `python scripts/smooth_scroll.py <in> <out>`, then measure again until zero. Look at the top band of the clip for account names and stray tabs.
4. Declare it in `video.json`: `"S07": {"clip": {"file": "clips/S07-name.mp4", "mode": "frame", "speed": "auto"}}`. The slide should be an `image` or `two-column` slide with a large frame; put the clip's first frame on it (`composite_clips.py --first-frame clips/S07-name.mp4 slides/<course>/<lesson>/S07-first-frame.png`) and rebuild the deck, so the clip fades in without a jump.
5. Run `make_video.py ... --extend`: it adds silence where a recording runs longer than its narration. Never speed a recording beyond 1.25x.

### Step 2b. Long-take mode (long how-to lessons that are mostly screen recording)

Use it when the lesson is **a long hands-on task recorded in one go** and the recording is most of the video (for example Claude Code doing a real job for 2 to 15 minutes per step). A short demo inside one slide stays in step 2. Details, speed rules and privacy: `references/screen-recording.md` section 6. The workflow is **record first, write the narration after**:
1. **Record from an action script (the default; recording by hand is the fallback)**: write `clips/<Sxx>-name.actions.json` (see `templates/actions.example.json`: open `wt.exe` with `claude` or another command, type like a person, key combos, `wait_done` for Claude Code to finish with automatic answers to permission prompts, scroll, click, `mark`, and a **required `review_result` after every job**: scroll up to the start of the answer and read down at 120 to 200 px/s with a 2 to 3 s stop per chunk, open the files the job wrote in a new tab of the recorded window; a script without it is refused unless `--skip-review "<reason>"`; this becomes a reading segment, never fast-forwarded or cut, and its narration explains the result). For very long jobs that hand the turn back several times, wait for the result file with `wait_file` (it types a nudge such as "Continue" only while the screen is idle); `if_text` skips ahead to a mark when a text is already on screen. To start Claude from a PowerShell window, type `claude`, press Enter and `pause` about 8 s. Run `python scripts/close_recording_windows.py` first so no window of an earlier take is left, then `python scripts/record_actions.py <actions.json>` (`--dry-run` to check without recording). The machine records with an action log, masks emails / API keys / `C:\Users\<name>` while they are on screen, stops by itself and writes the action table. It never types into another window: if the recorded window cannot be brought to the front after 6 tries, or the shell says "is not recognized" after Enter, it stops. By hand: `record_screen.py ... --log-events --hide-typing`, then `long_take.py analyse <clip>`.
2. **Write the narration from the action table** `clips/<Sxx>-name.action-table.md` (+ `.action-table-NN.png`): fill `segments[].narration` in `<clip>.longtake.json`, pick `zoom` boxes from `zoom_suggestions`, check `waits` (fast | cut) and the masks.
2b. **Show the real artifact after every result.** When Claude Code reports a job done, learners must see what it made (the document, the deck, the video), not just the line in the terminal. Declare `inserts` in `<clip>.longtake.json` (`after` or `after_end_of`, `file`, `kind`, `seconds`, `pages`, `zoom`, `narration`); the insert is built from the file itself at render time, with an "Opening: <file>" label, no extra window recorded. Details: `references/screen-recording.md` section 6.5 and the docstring of `scripts/insert_artifacts.py`.
3. Declare it in `video.json`: `"S03": {"clip": {"file": "clips/S03-claude.mp4", "mode": "full", "long_take": true}}` (S03 an `image` slide with the clip's first frame). The slide's narration comes from the long-take config.
4. `make_video.py` as usual: it fits narration and picture group by group (waits fast-forwarded up to 16x or cut with a "4 min later" label; action pieces never faster than 1.25x; a longer narration holds the last frame; a longer picture gets a pause), zooms and pans smoothly, draws a ripple at clicks and a key label in the corner. The report adds the seconds cut, the fast-forwards, the zoom boxes and the masks. Videos without `long_take` render exactly as before.

### Step 3. Render with one command

```bash
python scripts/make_video.py slides/<course>/<lesson>/slides.json [--extend]
```
Nine steps: storyboard, narration (through `gpu_lock.py`), Whisper review, render plan, three-layer mix, picture (headless Chrome, slide by slide), screen recordings, subtitles, final check. Run it in the background for lessons over 3 minutes (rendering takes roughly one to two minutes per minute of video the first time, seconds for a slide-level fix). When it stops:
- **Voice review** (`_check/voice-review.txt`): Whisper listens to the whole file once, then only the suspect lines are regenerated and re-checked, up to 3 rounds. It filters out Whisper's own mistakes on short words, phrases it invents over music, and anything a second, primed listen hears correctly; it stops only on long words, terms, names or several words in a row. Listen to the place (`ffmpeg -ss 1:23 -t 4 -i <voice.mp3> clip.wav`). If the voice is wrong, add a respelling to `PRONUNCIATION` in `make_voice.py` (captions keep the real spelling) or change the word in `slides.json`; if Whisper misheard, add the word to `_check/voice-exceptions.txt`. Then `--from-step 2` (cached lines are not regenerated).
- **Final check FAIL** (`_check/<file_name>.report.md`): fix the cause (loudness with `--music-db`, jumps by smoothing the recording, length by re-rendering) and rerun from that step.

### Step 4. Look before you report

1. **Look at** `_check/contact-NN.png` (three frames per slide: arriving, settled, about to leave) with the checklist in `references/quality-checks.md`: a cover patch left over text, text clipped by a zoom, two slides visible at once during a transition, a countdown over text, a recording out of its frame, an empty first frame. To inspect a moment closely: `node assets/engine/render.mjs sheet <storyboard.json> <timeline.json> _check/zoom --from 40 --to 46 --every 0.25`.
2. Listen to two places: the first 20 s and one transition (`ffmpeg -ss 0 -t 20 -i <mp4> -vn test.mp3`). Effects audible but clearly under the voice, music low.
3. Fix with `video.json` or the scripts, render again (only changed slides re-render), look again until a full pass finds nothing. **Never report a video as done before looking at the contact sheets of the latest render.**
4. **Watch it as a learner would.** A passing report is not enough. Take a frame at the moment the first narration line of 3 or 4 slides starts (the picture must already be that slide), look at the long-take and insert parts (no scene that flashes by in under about 2 s, text readable at 1080p), and look at the title slide (no stray word on its own line). Anything only an ear catches (a name read oddly, music too loud) goes in the report with its mm:ss so the user can listen.

### Step 5. Report

Give the user: the mp4 and vtt paths; real duration; voice and pace (words per second); slides, effects, pauses; the check report (verdict, LUFS, jumps); which recordings were composited; words added to the pronunciation table or the Whisper exceptions; warnings left and why. Show a contact sheet.

## Several lessons in a row

Keep the voice, music level and sounds the same across a course; lessons should differ by no more than 1.5 LU (compare the LUFS line of each report). The pronunciation table and the Whisper exceptions grow over time; do not reset them. Keep recordings in `videos/<course>/<lesson>/clips/`, one new file name per take. A deck split into topic videos (`V<k>-<name>/slides.json`) is rendered one sub-deck at a time.

## Principles

- **The standard is fixed** (`video-standards.md`): one topic per video, a script, open-body-close, spoken transitions between parts, interaction. Rhythm, picture and sound are where you create.
- **Picture and voice complete each other; the voice never reads the slide.** A region appears when the voice reaches it; text that is being read does not move.
- **Pauses that agree with the screen**: narration that says "pause the video" gets a 3 s hold and no countdown (the learner presses pause; a running timer next to a "60 seconds" label would contradict it). A question without that phrase holds for its stated time, at most 60 s, with a countdown.
- **The picture comes before the voice** (`"sync": 1` in the storyboard): a slide enters 0.4 s before its first line is spoken, a region has finished appearing 0.3 s before the line that mentions it, and each region appears on the FIRST line that mentions it. Process steps, table rows and numbered lists appear in position order (a build check, `SHOW ORDER ERROR`, refuses the opposite; `"order": false` in video.json for a deliberate exception). Key-message, question and closing slides show at most two regions per line. A clip that covers the whole slide replaces the slide image with the clip's first frame, with a 3.8 s stage label.
- **Attention circles**: answers and notes like "circle B" get a deliberate circle; regions are also scored (emphasis word in the line that mentions them, a big number, the last row of a table, best word match) and the best one or two (three with three emphatic lines) get a circle drawn while the voice mentions them, fading after a few seconds; ellipses for cards, rounded boxes for rows; at most three per slide.
- **Teaching pointer on by default for English lessons** (`"language": "en"`): it moves on curves to the region being explained, rests outside text and never shows on title, section, key-message or closing slides. Turn it off with `{"_all": {"cursor": false}}` in video.json; for other languages it is off unless you turn it on with `{"_all": {"cursor": true}}`.
- **Lively, not busy**: something changes every 5 to 10 seconds and nothing stands still for more than 25; but one focal point per frame, no spins or flips, at most 16 sound effects a minute, transition sounds only at slide changes, a quiet music bed (-28 dB by default) ducked under the voice.
- **The voice is the quality people hear first.** Do not time-stretch a model that sounds bad stretched (VieNeu); slow it with longer pauses instead. The Whisper review is not optional: a mispronounced term is a teaching error.
- **Subtitles are separate files**, never burned in.
- **Content does not change at the video step**: no new ideas, no invented numbers. A narration problem goes back to the lesson or slide step.
- **Run it, measure it, look at it** before handing over: loudness, jumps, duration, contact sheets.
- **A recording is a recording**: no screenshots standing in for actions; scrolling must measure smooth.
- To add a transition, effect or sound: extend `assets/engine/video.js`, the tables in `scripts/storyboard.py` and `references/motion-and-sound.md`, render a test, look at it, then use it.

## References

- `references/video-standards.md`: the instructional standard for audio and video learning materials, mapped to slide types, plus platform specs (Udemy and similar).
- `references/motion-and-sound.md`: how regions and actions are inferred, the slide type table, motion numbers, the soundtrack, `video.json` syntax, how to keep learners awake.
- `references/narration-voice.md`: Kokoro and VieNeu, pace, pronunciation fixes, the Whisper review.
- `references/screen-recording.md`: recording a window, smooth scrolling, measuring and smoothing jumps, compositing, privacy; section 6 the long-take mode (recording from an action script, the action table, cutting or fast-forwarding waits, zoom, clicks, keys, masks).
- `templates/actions.example.json`: an action script for a real Claude Code session.
- `scripts/insert_artifacts.py` (docstring): every field of a long-take insert; `scripts/close_recording_windows.py`: closes leftover recording windows tab by tab.
- `assets/whisper-homophones-en.txt`: `said>heard` pairs every English voice review accepts.
- `references/quality-checks.md`: thresholds of the final check and the contact-sheet checklist.
- `templates/video.example.json`: per-slide overrides.
