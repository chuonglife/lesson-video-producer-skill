# Quality checks

The most important rule: **run it, measure it, look at it before handing it over.** Measurements catch form; eyes and ears catch meaning and feel. Both are required.

## 1. Measurements (`check_video.py`, step 9)

| Item | Threshold | Hard failure? |
|---|---|---|
| Size, frame rate, codec | 1920x1080, 30 fps, H.264 yuv420p, AAC present | yes |
| Length | matches `timeline.json` within 1 s | yes |
| Integrated loudness | -20 to -15 LUFS | yes |
| True peak | at most -1 dBTP | yes |
| Channels | both carry sound, within 6 dB | yes |
| Silence | no stretch over 12 s outside learner pauses | warning |
| Still picture | nothing still for over 25 s (sampled every second) outside learner pauses | warning |
| Scroll jumps | zero (0.9 s around slide changes ignored) | yes |
| Sound effect density | 4 to 16 per minute | warning |
| Slide rate | 1 to 6 slides per minute | warning |
| Loudness across a course | within 1.5 LU (compare the reports) | yes before publishing |

The report is `_check/<file_name>.report.md`. Every warning gets looked at and decided (write the reason in your report), never ignored.

## 2. Contact sheets (`_check/contact-NN.png`, three frames per slide: in, settled, end)

- [ ] The first frame is not empty (the title is already on screen).
- [ ] No cover patch over text (a region box slightly off) in "settled" and "end"; no leftover slice of text next to a region in "in".
- [ ] Transitions never show two slides clearly at once; the light streak does not cover text for more than 0.3 s.
- [ ] Voice and picture agree: the voice of a slide starts at least 0.15 s after its transition has finished, a region has finished appearing before the line that mentions it, process steps and table rows appear in order, no slide stays on screen for under 2 s, no scene of a long take is under 1.5 s, and the placeholder slide never flashes around a full-screen clip (all measured by `check_video.py`; hard failures when the storyboard has `"sync": 1`).
- [ ] Zooms do not cut text at the edge; circles hug their region and do not cut the neighbour's text; question slides circle the answer after the wait; the countdown covers nothing.
- [ ] Recordings sit in their frame, not distorted, no large black bars; their first and last frames match the picture under them.
- [ ] One focal point per frame; text readable at 480 px wide.
- [ ] Slide numbers in the footer increase steadily (no slide lost).
- [ ] No captions burned into the picture (captions are separate files).
- [ ] If the cursor is on: it rests next to the region, never over text, and never shows on title, section, key-message or closing slides or during a countdown.

To inspect a moment closely: `node assets/engine/render.mjs sheet <storyboard.json> <timeline.json> _check/zoom --from a --to b --every 0.25`, or take a frame from the finished file: `ffmpeg -ss <s> -i <mp4> -frames:v 1 frame.png`.

## 3. Listen

- The first 20 s: the voice starts at 0.6 s, the music fades in over 2.5 s, nothing fights the voice.
- One transition and one card reveal: the effect is audible but clearly under the voice; no two effects stuck together.
- A learner pause: the music does not cut off abruptly; a ting at the end of a countdown.
- Three technical terms: pronounced correctly (compare with `voice-review.txt`).

## 4. Content (against the lesson)

- Slide order and narration match `slides.json`; opening, presentation and closing are all there; at least one question.
- Regions appear when the voice reaches them (on two `cards` or `process` slides, at the "settled" frame, the number of cards shown is about the number of ideas spoken).
- Recordings match the narration.

## 5. Report

Every sentence is something you checked or did: the mp4, vtt and contact sheet paths; the measurements; what you fixed and what is left, with the reason. No "seems", no "probably".
