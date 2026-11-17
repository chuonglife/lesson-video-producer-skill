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
