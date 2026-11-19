# Motion, transitions and sound

The goal: a video that is **lively, never sleepy, easy to follow**, with one focal point per frame and nothing gratuitous. The numbers come from the motion-design rules of whaleyxbt/claude-motion and from a production line of online courses where they were tuned on real lessons.

## 1. What the renderer does with a slide

`storyboard.py` opens the pptx, measures every shape (inches to 1920x1080 pixels) and groups them into **regions**: a rounded box (card, row, step, column) takes every shape whose centre lies inside it; a small numbered oval joins the row beside it; an icon and a line of text on the same row become one region; a table splits into rows. Title, section label, footer and thin decorations stay **static** (always visible). In the video every region is **covered** with the exact background colour around it until its moment, then the slice of the slide image under it **appears** with the effect of its slide type. Nothing is re-laid-out, so fonts and themes do not matter.

Regions appear **with the narration**. The even spread is only the starting guess: K regions over M narration lines, region k on line `1 + floor(k*(M-1)/K)` (line 1 is usually a lead-in); with M = K, one region per line; with M < K they are spread over time. Then each region is moved to the FIRST line that mentions it: rare words weigh more than common ones, a pair of words counts 1.5x, a card with a title and bullets matches the first line that clearly mentions any of its ideas, and a capitalised name or a number that opens an idea counts on its own. A bullet list typed in ONE text box is split into one region per paragraph (measured on the slide image) so it does not appear all at once. Ordered slides (process, table rows, lists numbered 1, 2, 3...) keep position order, and a build check stops with `SHOW ORDER ERROR` if the narration would show a later step first (fix the narration, or `"order": false`). Closing, question and key-message slides show at most two regions on one line. On a `question` slide the question shows at once and the options follow the lines. Types that are not stepped (`title`, `section`, `image`) reveal everything at the start, 0.22 s apart. Notes in slides.json such as "reveal one by one" force stepping. `reveal_lines` in video.json sets the exact lines.

### Voice-picture timing

With `"sync": 1` in the storyboard (always, when written by this version), the slide starts its transition before its first line, so the picture has arrived (transition time plus a 0.4 s settle) when the voice starts; `make_voice.py` widens the silence between two slides when the real gap is too short, and writes `speech_start`/`speech_end` (when the voice really starts and stops, not the file edges) into the timeline. A region finishes appearing 0.3 s before the voice mentions it; regions on the same line are staggered by 0.25 s with the last one finishing 0.3 s early. The teaching pointer and the circles follow `speech_start`, so they never run ahead of the voice. An older storyboard without `sync` keeps the old timing (a slide changes exactly when its first line starts).

## 2. Slide type table

| Slide type | Reveal effect | Sound on reveal | Transition into the slide |
|---|---|---|---|
| `title` | fade (everything, from frame 0) | none | (first slide) |
| `objectives` | slide-up, one by one | ui (three marimba notes, rotating) | push-left |
| `agenda` | fade, one by one | none | fade-up |
| `section` | scale-in (everything) | none | zoom-blur (signals a new part) |
| `cards` | pop, one by one | pop (two pitches, rotating) | push-left / fade-up / diagonal-wipe, rotating |
| `process` | slide-up, one step at a time | ui | as above |
| `compare` | slide-side (left from the left, right from the right) | ui | as above |
| `big-numbers` | pop | pop | as above |
| `table` | slide-up, one row at a time | ui | as above |
| `two-column`, `image`, `chart` | fade | a soft swoosh | as above |
| `question` | slide-up: the question at once, options with the voice | click | iris (the background turns to the accent colour) |
| `key-message` | scale-in | ting (two-note bell) | push-up / iris |
| `summary` | pop | pop | diagonal-wipe / push-up |
| `closing` | scale-in | success (four notes) | zoom-blur |

Neighbouring slides **never share a transition** (the script rotates). Transition sounds: `whoosh` (push-left, diagonal-wipe), `swoosh` (fade-up, push-up), `transition` (iris, zoom-blur: a long swoosh with a sparkle, only at new parts and questions).

## 3. Motion numbers (`assets/engine/video.js`)

- Entrances: ease-out `cubic-bezier(0.16, 1, 0.3, 1)`; slide-up 0.6 s over 40 px; pop 0.5 s from 84% with a slight overshoot (easeOutBack); fade 0.55 s; slide-side 0.6 s over 44 px; scale-in 0.75 s from 106%.
- Exits (the previous slide): ease-in `cubic-bezier(0.6, 0, 0.9, 0.35)`, about half the entrance time.
- Transitions: 0.6 to 0.75 s. push-left has a light streak in the accent colour (opacity at most 0.5); iris opens from the centre 8% to 100%; zoom-blur scales 108% to 100% with blur 8 px to 0; diagonal-wipe sweeps from the top left while the old slide fades and recedes; push-up pushes the whole frame up while the old slide moves back 28%.
- Stagger: 0.22 s between regions revealed together.
- Ken Burns: slides of 9 s or more push in very slowly (1.0 to 1.015) for their whole length, anchored at the bottom so the footer and progress bar are never cropped; off for `question` and `table`, or with `"ken_burns": false`. It keeps the picture alive while text stays readable.
- Zoom (`zoom`): the camera scales to 122% over 0.55 s, holds 1.2 to 3 s, returns in 0.5 s, centred on the chosen region.
- Attention circles: a hand-drawn stroke in the accent colour (white on question slides), drawn in 0.75 to 0.9 s. An **ellipse** (1.15 turns, slightly wobbly) for cards and number tiles that are roughly square; a **rounded box** tilted -0.7 degrees for wide rows and table rows (an ellipse on a wide card cuts its corners and touches its neighbours). Three sources:
  1. Deliberate: a note such as "circle answer B" / "circle <text>", or `"circle"` in video.json. On a question slide with a hold it is drawn right after the wait, and the script adds 2.4 s so it is seen; it stays until the slide ends.
  2. Automatic: on cards, process, objectives, big-numbers, table, compare, summary, question, two-column, agenda, chart and key-message slides every region is scored: an emphasis word in the line that reveals it (remember, important, never, don't, mistake, key, must, always, only, notice, the answer, that is why, note that, watch out, careful, critical, essential, crucial) adds 3, the big number of a big-numbers slide 2, the last row of a table 1.5, plus a small score for words shared with the line being read. The best one or two regions (three when at least three lines carry an emphasis word), at most one per line, are circled 0.5 s after the voice starts the line and fade after 3.5 s (never before 2.2 s, so there is no flicker) or when the next region appears. Tall loose text blocks (over 260 px high) and empty frames are skipped; `"auto_circle": false` turns it off for a slide.
  3. A `circle` sound (a short swoosh) plays with every circle.
- Countdown: a ring in the bottom right (70/90 px from the edges), seconds counting down, a check mark for 0.9 s at the end, with a ting.
- Never: spins, flips, explosions, flying letters; text moving while it is read; two focal points in one frame; content within 60 px of the edge.

## 4. Review the storyboard (`<file_name>.storyboard.md`) before rendering

1. The number of regions of `cards`, `process` and `objectives` slides equals the cards, steps or items in slides.json. A mismatch (two cards merged, an icon on its own) means adjusting `storyboard.py` or setting `"stepped": false`.
2. Each region appears on the right line: read the slide's narration and check that "region 3 on line 4" is when the third idea is spoken. Otherwise set `"reveal_lines": [2, 3, 5, 6]`.
3. Neighbours differ in transition; new parts use `zoom-blur`; questions use `iris`.
4. Question slides hold (3 s when the narration says "pause the video", otherwise their timer, with a countdown).
5. A note "circle answer B" produced a `circle`; "zoom on X" a `zoom`. If not, set `"circle": "B"` or `"zoom": 2` in video.json.
6. Sound events (printed by the plan step) divided by minutes falls between 4 and 16.

## 5. The three-layer soundtrack (`mix_audio.py`)

- **The voice**: everything else serves it.
- **Effects** (`assets/sfx/`, synthesised by `make_sfx.py`, WAV 44.1 kHz stereo): `ui1-3` pentatonic marimba, `pop1-2` bubbles, `click`, `swoosh`/`whoosh` panned air, `circle`, `underline`, `transition` (long swoosh with a sparkle), `typing`, `ting`, `success`. Peaks around -19 to -23 dBFS. Density: any two at least 0.22 s apart, the same one at least 0.35 s apart; extra ones are dropped, except transition, ting and success.
- **Music**: `assets/music/piano-bed.mp3` (synthesised piano, 240 s, looped; Cmaj7-Am7-Fmaj7-G6 at 66 bpm) at -28 dB (`--music-db`; it was -22 until v1.1, which sounded loud under the voice), sidechain-ducked by the voice (threshold 0.03, ratio 4:1, release 700 ms), 2.5 s fade in, 3.5 s fade out. No organ pads, no water or wind. Interviews or long recordings: `--no-music`. `make_music.py --seed N` makes a different bed per course.
- Levels: the mix is normalised to -18 LUFS (TP -2); the final mux to -16 LUFS (TP -1.5, LRA 11). The report must read -20 to -15 LUFS.

## 6. `video.json` syntax (keys are slide ids)

Where it lives: `make_video.py` and `storyboard.py` read `video.json` from the output folder (next to the storyboard) and, when there is none, from the folder of `slides.json`. `storyboard.py --overrides <file>` names another one. Clip paths inside it are relative to the folder the `video.json` is in.

```json
{
  "_all": {"cursor": false},
  "S06": {"reveal_lines": [2, 3, 4, 5, 6, 7], "transition": "diagonal-wipe"},
  "S09": {"hold": 8, "circle": "B", "ken_burns": false},
  "S11": {"zoom": 2, "stepped": false, "effect": "pop"},
  "S07": {"clip": {"file": "clips/S07-chatgpt.mp4", "start": 0, "length": 24, "mode": "frame", "speed": "auto"}, "hold": 0}
}
```
`reveal_lines` counts the slide's narration lines from 1; `auto_circle: false` disables automatic circles on the slide; `transition` is one of push-left, fade-up, iris, zoom-blur, diagonal-wipe, push-up; `effect` one of slide-up, pop, fade, slide-side, scale-in; `circle` and `zoom` take a region number (from 1) or the first words of the region; `hold` is the silence after the slide's last line (overrides the notes and the pause rule); `clip` is described in `screen-recording.md`. Run `storyboard.py` again (or `make_video.py --from-step 1`).

## 7. Keeping learners awake, in one paragraph

The screen changes every 5 to 10 seconds (a reveal, a circle, a zoom, a recording), transitions vary, a soft sound marks each idea, the music has a pulse but stays low, the voice pauses after questions, and learners have something to do. But liveliness comes from **timing that matches the voice**, not from piling on effects. If two things move in one frame, remove one.
