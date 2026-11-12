# Real screen recordings

For **how-to, hands-on and software** lessons: using an app, filling in a form, prompting an AI tool, working in an LMS, Canva, Word or Excel. The rule that makes these lessons work: show the real action, typed gradually, with a correction and the reason for it, at least two cases (leave one for the learner), and **never replace it with a screenshot or a mocked-up page**.

## 1. Prepare the window

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
