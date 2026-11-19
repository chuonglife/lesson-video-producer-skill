# The instructional standard for video learning materials

Source: *Developing digital learning materials: audio and video* (Phát triển học liệu số dạng audio, video), Institute of Technical Education, Ho Chi Minh City University of Technology and Education (lecturer Nguyen Minh Khanh), 13 slides. Section 6 adds platform specifications checked in practice on Udemy in 2026. This part of the skill does not change from video to video; what happens inside each video is the creative part.

## 1. Definition (slide 5)

An audio or video learning material is a digital learning material whose **digital media components are audio and video**. These components carry the teaching content, digitised from traditional materials (text, numbers, symbols, pictures) or from text-and-image digital materials into a machine-readable form, stored and shown on digital devices, and learners can interact with it in several ways.

For this skill: the video is the **next digitisation step** after the slide deck (a text-and-image material). The teaching content stays the same; only its carrier changes. The narration becomes a voice, the slides become pictures that move with the voice.

## 2. Three ways to produce one (slide 7)

| Form | In the source | What this skill does |
|---|---|---|
| Convert a slide presentation into a video | Turn a slideshow into a video with PowerPoint or other software | **The main path**: slide images + narration + motion -> mp4 |
| Convert pictures into a video | A slideshow of pictures with commentary | `image` and `chart` slides with narration, a slow Ken Burns push |
| Record with capture tools | Record and edit into a teaching video | **Real screen recordings** for how-to, hands-on and software lessons (`record_screen.py`), placed inside a slide frame or full screen |

One lesson can mix all three: slides for concepts, recordings for actions, pictures for examples.

## 3. Three kinds of interaction (slide 9)

| Kind | In the source | In the video |
|---|---|---|
| Questions | Recall and prompting questions inserted between segments, following the logic of learning | `question` slides that ask the learner to pause, a hold or a countdown, a `key-message` slide with the answer, the answer circled |
| Navigation | Menus inside and outside the video to jump between segments | The `agenda` slide repeated before each part with the current part highlighted; slide times in `events.json` serve as chapters when publishing; captions |
| Chained activities | Watch, then fill in blanks, take a quiz... | The `closing` slide gives one action to do now; worksheets and templates are attached to the lecture on the platform |

Every video has at least one question; a video over 8 minutes has at least two pauses.

## 4. Design principles (slide 11)

1. **One topic per video.** A lesson can be one or several videos; never merge two lessons into one video. For online courses, 5 to 12 minutes per video.
2. **A script and the necessary media.** The script is `slides.json` (narration, production notes) + `storyboard.json` (actions in time) + `video.json` (overrides); the media are slide images, icons, recordings, sounds and music. Do not render before you have them all.
3. **A structure: opening, presentation, closing** (section 5).
4. **Spoken transitions between parts**, so the information has a thread. The narration of `section` and `agenda` slides is that transition; the renderer gives these slides distinct transitions (`zoom-blur`, `fade-up`) so eye and ear both notice "new part".
5. **Interactive learning activities** (section 3).

## 5. Structure of a video lesson (slide 12)

| Part | In the source | Slides | In the video |
|---|---|---|---|
| Opening | Introduce yourself, the topic, the objectives and the content | `title` -> (`question`, try it first) -> `objectives` -> `agenda` | The title is on screen from the first frame; objectives appear line by line with the voice |
| Presentation | Linked sections: introduction, explanation, illustration, application | Per part: `section`/`agenda` -> 2 to 5 content slides (`cards`, `process`, `compare`, `table`, `image`, recordings) -> `question` | Regions in step with the voice, circles and zooms on what is being said, recordings for actions |
| Closing | Recap with keywords, point to the next lesson | `summary` -> `closing` | Keywords pop in, a success chime on the closing slide, music fades out over 3.5 s |

The slide skill already orders the deck; this skill **checks** it. A missing `question` or `closing` is reported to the user, not added silently.

## 6. Platform specifications (checked in 2026)

- At least 720p; this skill renders 1080p, 30 fps, H.264 yuv420p (limited range, BT.709, tagged in the stream), AAC 48 kHz 192 kbps, `+faststart`.
- Udemy paid courses: at least 30 minutes of video and at least 5 lectures; measure real files, never estimate.
- Audio: Udemy publishes no loudness number, only clear, clean, stereo and consistent across lectures. Internal target: -20 to -15 LUFS integrated, true peak at most -1 dBTP, lectures within 1.5 LU of each other.
- Captions: WebVTT only; replacing a video removes its captions, upload them again.
- Synthetic voices must be disclosed where the platform asks for it (Udemy: "This course contains the use of artificial intelligence."), and the voice must have a clear commercial licence (Kokoro and VieNeu: Apache 2.0; avoid online voices with unclear terms).
- No personal data or account names in screen recordings.

## 7. Multimedia principles applied (Mayer)

- Coherence: no reading the slide aloud, no music over the voice, no effect without a reason.
- Signalling: highlight what is being said (reveals, circles, zooms).
- Temporal contiguity: a picture appears when the words about it are heard (regions are tied to narration lines).
- Segmenting: one idea per slide, one topic per video, pauses.
- Personalisation: spoken language, one consistent way of addressing the learner.
