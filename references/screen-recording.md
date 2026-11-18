# Real screen recordings

For **how-to, hands-on and software** lessons: using an app, filling in a form, prompting an AI tool, working in an LMS, Canva, Word or Excel. The rule that makes these lessons work: show the real action, typed gradually, with a correction and the reason for it, at least two cases (leave one for the learner), and **never replace it with a screenshot or a mocked-up page**.

For a software how-to lesson that is mostly screen recording (Claude Code doing a real job for 10 to 20 minutes, most of the video on screen): use the **long-take mode** of section 6, recorded by the **machine from an action script** (section 6.1). That is the default; recording by hand is the fallback. Sections 1 to 5 still apply to short clips inside a slide.

## 1. Prepare the window

- **Switch any Vietnamese (or other) input method to English** (UniKey, EVKey, OpenKey) and the keyboard to en-US before recording: a Telex input method turned "for lesson" into "fỏ leson". `record_screen.py` warns when it sees one; scripted typing uses KEYEVENTF_UNICODE and is safe, typing by hand is not.

- Browser: a private window or a clean profile, a temporary chat in AI tools, the interface in the course language (`?hl=en` on Google products), no bookmarks bar, no notifications, no account name in a side bar. Zoom the page to 110 to 125% so text stays readable when the clip shrinks to a 1280x720 frame inside a slide.
- Office apps: a clean sample file, the ribbon collapsed if it is not needed, a normal-size pointer.
- Window size 1280x720 or 1920x1080 (16:9). `record_screen.py --list` prints window titles and sizes (Windows).
- Type neutral content: AI tools add local details on their own (city names, currencies, brand images); scroll through the whole answer before stopping.

## 2. Record (`record_screen.py`, Windows)

```bash
python scripts/record_screen.py videos/<course>/<lesson>/clips/S07-fill-the-form.mp4 --window "Form 02 - Word" --seconds 45 --size 1280x720 --scroll "20:200:5"
```
- `gfxcapture` records the window itself, even when it is covered, pointer included. A window that does not change produces no frames, so the script nudges it when stopping.
- Stop early: create `<out.mp4>.stop`.
- **Smooth scrolling**: `--scroll "start:px-per-second:seconds"` sends 60 small wheel steps per second; in a browser you control, use `window.scrollBy({top: 200, behavior: 'smooth'})` every 0.6 to 0.8 s. Never a whole notch at once, never `scrollTo` jumps.
- Typing: 0.035 to 0.06 s per character, an occasional pause, an occasional corrected letter. Hold still 3 to 5 s after every result.
- One new file name per take.

On macOS or Linux record with OBS, QuickTime or ffmpeg (`avfoundation`, `x11grab`), at 30 fps, then continue with the steps below.

## 3. Measure and smooth

- `check_motion.py <clip>` (run automatically after `record_screen.py`) finds frames where the content shifts vertically by 40 px or more (at 1280 wide) within a single frame: a jump. A still image never shows it; only measurement does.
- Jumps left: `python scripts/smooth_scroll.py <in.mp4> <out.mp4> [--fixed-bottom 140] [--cursor-template pointer.png]` replays each scroll over 12 to 48 frames on an ease-in-out curve (no frame moves more than about 32 px), keeps a fixed bottom band still (a chat box), and can lift the pointer out of the scrolled content. Measure again until zero.
- Look at the top 60 px of the clip and its last frame: account names, tabs, notifications.

## 4. Composite it (`composite_clips.py`, step 7 of `make_video.py`)

`video.json`:
```json
"S07": {"clip": {"file": "clips/S07-fill-the-form.mp4", "start": 0.5, "length": 38, "mode": "frame", "speed": "auto"}}
```
- `mode: "frame"`: the clip sits in the slide's largest rounded frame (`clip_frame` in the storyboard), kept 16:9 and centred; or give `x, y, w, h`. Use an `image` slide whose picture is the clip's first frame (`composite_clips.py --first-frame`), or a `two-column` slide with the frame on the right. The clip fades in over 0.35 s on top of its own first frame, so there is no jump.
- `mode: "full"`: the clip covers the whole picture; the slide shows only while it comes in and goes out. Use it when details must be readable.
- `speed`: a number (1.15 = 15% slower) or `"auto"` (0.8x to 1.25x to fit the slide). Never faster than 1.25x: learners cannot follow.
- A clip longer than its narration: `make_video.py --extend` adds a `hold` to the slide (voice silent, music and picture running) and redoes the storyboard and voice (cached, so fast). Better still, write narration that explains the action while it is on screen.
- The clip's own audio is dropped; the narration plays over it.

## 5. Checklist

- [ ] The clip is a real recording, not a simulation.
- [ ] Zero jumps (`check_motion.py`).
- [ ] No account names, notifications or stray tabs (top band).
- [ ] 3 to 5 s of stillness after each case; long results scrolled through.
- [ ] Not sped up beyond 1.25x; the end is not cut (see the warnings of `composite_clips.py`).
- [ ] The narration describes what is on screen (read the typed text again).
- [ ] The typed lines in the picture are right (no input method was on; no input-method warning in the action table).

## 6. Long-take mode (long how-to lessons recorded in one go)

When: a long hands-on task recorded in one go (Claude Code runs a step for 2 to 15 minutes, viewers need to see the whole process), the recording being most of the video. A short demo inside one slide stays an ordinary `clip` (section 4).

The difference from an ordinary clip: **record first, write the narration after**. The narration is not written in `slides.json` first with the clip stretched to fit it; the recording comes first, the action table follows, the writer writes for each piece of picture, and at render time each piece of narration lands on its own piece of picture.

### 6.1 Recording from an action script (`record_actions.py`, the default)

```bash
python scripts/record_actions.py videos/<course>/<lesson>/clips/S03-claude.actions.json [--dry-run] [--skip-review "<reason>"]
```
The script (`templates/actions.example.json`) names the window to open (`wt.exe` with `command`, `cwd`, `title`, `size`, `font_zoom` = how many Ctrl+= for larger text) and the steps: `pause`, `type` (typed like a person, 25 to 40 ms per character with light hesitations, KEYEVENTF_UNICODE), `key` (Enter, Esc, Ctrl+C, Shift+Tab, arrows), `wait_still` (window still for N s), `wait_text` (until a text shows), `wait_done` (the busy text such as "esc to interrupt" appeared and is gone and the window is still; prompts such as "Do you want" are answered with the given keys), `review_result`, `scroll`, `click` / `move` (window-relative coordinates), `mark` (a named segment edge the narration hangs on). The script opens the window, runs `record_screen.py --log-events`, plays the steps, stops, closes the window (after the recording stops), writes `<clip>.take.json` (marks, reading segments, masks, zoom) and runs `long_take.py analyse`. `--dry-run` plays the steps without recording.

Terminal text is read with UI Automation (the real text of Windows Terminal, no OCR), **visible part only**: reading the whole scrollback several times a second stops Windows Terminal from drawing. Without UI Automation the text waits fall back to still-window waits.

With the real Claude Code (tested with `claude` 2.1, creating real files): the script opens `claude` in the demo course folder (already signed in). It resolves the real `claude.exe` (wt.exe cannot start the npm shim: error 0x80070002), removes the `CLAUDE_*` variables of the controlling session from the environment, and refuses `;` in the command (wt.exe splits commands at `;`). The first `wait_done` answers the "Accessing workspace" prompt (**its default is "No, exit"**: answer `["Down", "Enter"]`) and "Chrome extension detected" (`Esc`). After each prompt typed for Claude comes a `wait_done` with `"busy": "esc to interrupt"` (it must appear, then go) and an answer for "Do you want" (`Enter`). Do not type `/exit` or `exit` at the end: the machine stops the recording first and then closes the window. The first time you record a new program, run `--dry-run` and read the "visible text (end)" line to pick the right busy text.

Starting from a PowerShell window instead (`"command": ["powershell", "-NoLogo"]`, then `type` "claude", `key` Enter): wt.exe opens the tab inside the Windows Terminal process that is already running, with the PATH it had when it started, so `claude` used to answer "is not recognized". The script now writes a small `.ps1` that runs silently before the prompt: it loads the PATH of the recording process plus the Machine and User PATH from the registry, aliases `claude` to the real executable and removes `CLAUDE_*`. Give Claude about 8 s to start (`{"pause": 8}`) before the first answer or prompt. If the shell still answers "is not recognized" after an Enter, the recording stops at once instead of typing the prompt into PowerShell (`"allow_error": true` on a `key` step turns the check off).

Focus: before every step the recorded window is brought to the front. Windows sometimes refuses (a notification, an office suite starting in the background or the taskbar holds the focus), so the script tries a synthetic Alt, then attaches its input thread to the one holding the focus, then `SwitchToThisWindow`, then a click on the title bar of the recorded window (only if that point really belongs to it), up to 6 times 1.5 s apart. If the window is still not in front it STOPS without sending a key: keys typed into another window are worse than a failed take. Before a new take, `python scripts/close_recording_windows.py` closes windows left from earlier takes (titles containing `REC-`, or `--match`) one tab at a time with Ctrl+Shift+W, after Ctrl+C twice; closing a multi-tab window as a whole would show "Do you want to close all tabs?" in the next clip.

Two steps for long and uneven jobs:
```json
{"wait_file": {"file": "course/INDEX.md", "max": 21600, "nudge": "Continue", "nudge_every": 900, "busy": "esc to interrupt",
               "answer": [{"text": "Do you want", "keys": "Enter"}]}}
{"if_text": {"text": "All lessons built", "goto_mark": "result"}}
```
- `wait_file`: a job of an hour or more runs in the background and Claude Code hands the turn back several times, so "the screen is still" says nothing. The step waits until the file exists (relative to the window's `cwd`); every `nudge_every` seconds, if the file is still missing and the busy text is not on screen, it types the nudge and Enter. Prompts are answered as in `wait_done`.
- `if_text`: if the text is on screen now, every step up to the named mark is skipped (the job is already done, no "Continue" needed). The match is case-sensitive, so the same words in the prompt you typed do not trigger it. The mark must come later in the script, otherwise the script is refused.

Background work and `/exit`: Claude Code can hand the turn back while an install or a render still runs in the background. Typing `/exit` then shows "Background work is running", and Enter picks "Exit and stop tasks". The script warns about every `/exit` it finds; put a wait before it that lasts until Claude reports the work is done (a `wait_done` with a long `start_within`, or a `wait_file`). In a lesson, tell learners the same: wait for Claude to say it is done before leaving.

**Required: review the result.** After every job (every `wait_done` with `busy`) there must be a `review_result` step before the next typing or before the end of the script; otherwise the script is refused before recording. Waive it only with a reason: `--skip-review "<reason>"`, `"skip_review": "<reason>"` in the script, or `"no_review": "<reason>"` on the `wait_done` step (the reason is printed and stored in `take.json`).
```json
{"review_result": {"speed": 160, "dwell": 2.5, "chunk_px": 360, "up_px": 1100, "files": ["notes.md"], "line_px": 26, "hold": 3, "zoom": [0, 0, 0.62, 0.62]}}
```
- Scroll smoothly up to the start of the answer (`up_px`, default 1.2 window heights), then read down at a readable speed (`speed` 120 to 200 px/s), `chunk_px` at a time with a `dwell` stop (2 to 3 s per chunk).
- `files`: what the job wrote. Text files (md, txt, json, csv, gift, py, html, vtt...) open with `Get-Content` in **a new tab of the same recorded window**, are scrolled through by line count (`line_px` per line), held `hold` seconds, then Ctrl+Shift+W returns to the program tab. Images, videos and pptx cannot be opened inside the recorded window yet: the script stores a warning in `take.json`; show such a file on a slide or record its viewer separately.
- `zoom` (window-relative 0..1) becomes a zoom box over the whole reading segment.
- The segment is a **reading segment**: the action table marks it "READING", it is never treated as a wait, never fast-forwarded, never cut; the 1.25x rule applies. Its narration EXPLAINS the result (what is right, what needs fixing) instead of reading the screen aloud.

**Privacy** (always check): before and during the recording the visible terminal text is scanned 3 times a second; emails, API keys (sk-, AIza, ghp_, xox), `C:\Users\<name>` paths and the strings in `private` become timed masks (a solid box with an orange edge). Fixed masks go in `masks` of the script. A typed string that contains an email, a key or a user path makes the script REFUSED, unless the step says `"secret": true` (then typed text is never logged; but while the string is half typed its start does not match a pattern yet and a few characters can show: better not to type secrets at all, keep them in a file or an environment variable). Check the frames in the action table and the contact sheet.

### 6.2 Recording by hand (the fallback)

`record_screen.py ... --log-events [--hide-typing]` writes the action log `<clip>.events.jsonl` (seconds, clicks, keys and combos, wheel). Off by default; only for your own recordings on your own machine; only logs while the recorded window is in front. `--hide-typing`: typed characters are never written to the file (only "typed" and combos such as Ctrl+C, Enter): use it whenever a password or an API key could be typed. The log's seconds match the frames thanks to x264 `-tune zerolatency` (the measured start offset is printed at the end). Then run `long_take.py analyse <clip>`.

### 6.3 The action table and the narration

`long_take.py analyse <clip> [--threshold 0.004] [--min-wait 4] [--allow-blips 1] [--mode fast|cut] [--language en]` writes:
- `<clip>.longtake.json`: the draft config. `segments` (split at the start and end of each wait, at script marks, at reading segments, at Enter in long action stretches), `waits`, `zoom_suggestions`, `masks`, `highlight`.
- `<clip>.action-table.md` + `.action-table-NN.png`: one row per segment (source seconds, actions, waits, suggested zoom, start/middle/end pictures with the suggested zoom box).

Wait detection: the share of pixels changing between two frames 0.1 s apart below `threshold` (0.4%) is "still"; short changes up to `allow_blips` seconds (a spinner, a stray log line) do not break a wait; around each key or click (-0.5 to +1.5 s), 3 s after each `mark` and over every reading segment there is never a wait; the shortest wait is `min_wait` seconds. Without an action log, typing looks like a still screen: check the waits and delete those that are not.

The writer reads the table and writes `segments[].narration` (one spoken beat per line). A wait is the place to explain why. A segment without narration joins the one before. Copy the boxes you want from `zoom_suggestions` to `zoom` (edit `box`, `from`, `to`, `ease` freely).

### 6.4 Declaring and rendering

`video.json`: `"S03": {"clip": {"file": "clips/S03-claude.mp4", "mode": "full", "long_take": true}}`. S03 should be an `image` slide showing the clip's first frame. Then `make_video.py` as usual:
1. `storyboard.py` takes the narration from `segments[].narration` (instead of the slide's narration) and stores the line range of each group.
2. After the voice, `long_take.py fit`: a group whose picture cannot shrink to its narration gets `pause_after` in the config, then steps 1 to 4 run again (the voice is cached).
3. Step 7, `composite_clips.py`, calls `long_take.py` to render the edited clip to the narration's timing (stored as `clips/_longtake/<clip>-<hash>.mp4`, rendered again only when the narration or config changes) and lays it over 1:1.

Speed rules (narration and picture, group by group):
- A piece with actions the viewer must follow: **never faster than 1.25x** (the rule of section 4, unchanged). Never slowed down; a longer narration holds the last frame instead.
- **The exception is for waits only**: `fast` runs at 8x by default, up to 16x (`max_speed`) when the narration is short, down to 2x when it is long, with an "8× speed »" label in the top right; `cut` replaces the wait with 1.6 s (0.8 to 3 s) that dissolves from before to after, with a "4 min later" label at the top. The first and last second of each wait stay at normal speed so viewers see the start and the finish.
- Narration longer than the picture: the fast-forward slows (not below 2x), then the last frame holds. Narration shorter: waits shrink first, then action pieces speed up to 1.25x, then `fit` adds a pause after the narration.

Zoom and pan: `zoom` boxes in source seconds, widened to 16:9, at most 3x; in, out and the pan between neighbouring boxes follow a smootherstep curve over `ease` seconds **of output** (a zoom inside a 16x fast-forward is still smooth). The report gives the largest step (px per frame) and the jerk (velocity change between frames, px per frame²; a warning above 20).

Highlights: an orange ripple at each click (0.6 s); a key label in the bottom right ("Enter", "Ctrl + C"); `hide_typing: true` (the default) never shows typed text even if the log has it. Masks are drawn on the source frame before the zoom, so they follow it. The window's pointer is recorded (a how-to needs it) unless the script uses no mouse.

The report `_check/<name>.report.md` adds a "Long take" line: source seconds -> output seconds, waits cut and seconds cut, fast-forwards and their speeds, seconds held, zoom boxes, largest zoom, step and jerk, clicks, key labels, masks, the fastest action piece (above 1.25x is a hard failure). Fast-forward and cut pieces are not counted as jumpy scrolls. Details in `_check/long-take.json`. A video without `long_take` renders exactly as before.

A quick test without slides: `long_take.py render <clip> <out.mp4> [--group-seconds 12,30,8]`.

### 6.5 Showing the real artifact after each result (`inserts`)

When Claude Code reports a job done, learners must SEE what it made (a document, a deck, a video), not only the line in the terminal. No extra window is recorded: at render time `long_take.py` inserts a piece of picture built from the artifact file itself, right after the result review. Declare it in `<clip>.longtake.json`:
```json
"inserts": [
  {"after": 72.64, "file": "D:/demo-course/program.docx", "pages": [1, 2], "seconds": 14,
   "zoom": [{"from": 6, "to": 11, "box": [330, 300, 900]}], "narration": "This is the program Claude just wrote."},
  {"after_end_of": "step-12", "file": "D:/demo-course/slides/lesson-1/lesson-1.pptx", "pages": [1, 5]},
  {"after": 90, "file": "D:/demo-course/videos/lesson-1.mp4", "start": 20, "length": 5}]
```
- `after`: a SOURCE second of the clip, or a mark name (the start of the segment with that mark); `after_end_of`: a mark name (the end of that segment) or `"end"`. A point inside a segment splits it in two; the source frame stands still while the insert plays.
- `kind`: `auto` (the default, from the extension) | `document` | `text` | `slides` | `image` | `video`. What works: .docx .doc .odt .rtf .pdf (headless LibreOffice with a profile of its own, then `pdftoppm` at 200 dpi, white margins cropped, a smootherstep scroll, pages centred on the dark theme); .md .txt .json .csv (drawn as large light text, headings in the accent colour; `lines: [a, b]` for a range); .pptx .ppt .odp (the deck's `_preview/slide-NN.png` and `contact-sheet.png` when present, otherwise LibreOffice; the overview for 2.5 s, then each slide at full size for 2.2 s with a soft cross-fade; `pages` picks slides); .png .jpg (shown whole, `zoom` to pan); .mp4 .mov (the `start`/`length` part, with its sound, lowered to 0.35 under narration; `composite_clips.py` mixes it in).
- A label "Opening: <file>" sits at the top left; the top 132 px stay free for it, so scrolled text never runs under the label.
- An insert is a SEGMENT of its own: with `narration` it opens a new narration group, without it the group before carries on. A longer narration stretches the insert (a slower scroll); a shorter one shrinks it by at most 30% (never under 2 s, a video never). If it still does not fit, `fit` adds `pause_after` on the insert itself. The fast-forward and cut rules for waits never touch it; the report lists the inserts, and their in and out cross-fades are not counted as jumpy scrolls.
- Small text in a document (a folder tree, a table): add `zoom` on the part being read; `box` is x, y, width on the 1920x1080 frame of the insert, seconds are seconds inside the insert. Pages are cached in `_insert-cache/` next to the config and rebuilt when the file changes (the hash of the rendered clip includes the size and time of every inserted file).
- Office files and decks without slide images need LibreOffice and Poppler (`pdftoppm`; on Windows `winget install oschwartz10612.Poppler`). LibreOffice starts in the background for a moment, so do not render while a recording is running.


### 6.6 A still frame with zoom and outline (`static`, `outline` in `inserts`)

To zoom into and outline one exact spot of an inserted text (for example the conclusion line and the objectives table of a review report), set `"static": true` together with `lines: [a, b]` so the text fits ONE 1080 px frame (otherwise the renderer stops with an error and asks for fewer lines): the text sits under the label band and does not scroll. `outline: [{"from", "to", "box": [x, y, w, h]}]` draws an orange frame (fading in over 0.3 s) on the 1920x1080 frame BEFORE the zoom, so it follows the zoom; seconds are seconds inside the insert. On a scrolling strip the outline does not follow the text, so do not use it there.

### 6.7 Reveal order and the same-row cap (`storyboard.py`)

- `process` and `table` slides (row by row) and numbered lists (3 or more zones starting 1, 2, 3...) reveal their zones IN POSITION ORDER: a later zone never appears before an earlier one, and it only matches words from the line of the previous zone onwards. A label "6" once matched the word "six" in an opening sentence ("The skill runs six steps") and pulled step 6 to the front. The build is stopped by an automatic check ("SHOW ORDER ERROR") if the order is still inverted; to invert it on purpose set `"S04": {"order": false}` in `video.json`.
- `closing`, `question` and `key-message` slides: at most 2 zones reveal on the same line (a third zone moves to the next line). The renderer staggers zones on the same line by 0.25 s and makes the last zone finish 0.3 s before the voice does; with three zones on the first line the last one would finish after the voice (the video check reports "a cue for the previous zone before the zone has finished appearing", -0.12 s). No manual line hint is needed any more.

### 6.8 Audio peak limit in the final composite

`composite_clips.py` always passes the audio through `alimiter=limit=0.75` (sample peak at most -2.5 dBFS) AFTER mixing the sound of an inserted video, even when there is no clip (the copy step then re-encodes the audio too). Before this, the peak reached -0.1 dBTP when an inserted artifact video had sound, and the video check refuses anything above -1 dBTP.
