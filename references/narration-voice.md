# The narration voice

## 1. Local engines with a commercial licence

| | Kokoro-82M | VieNeu-TTS v3 Turbo |
|---|---|---|
| Languages | US and UK English, Spanish, French, Hindi, Italian, Japanese, Brazilian Portuguese, Mandarin (the first letter of the voice: a, b, e, f, h, i, j, p, z) | Vietnamese |
| Install | `pip install kokoro soundfile` (Python 3.10 to 3.12; espeak-ng comes inside the pip package). Mandarin also `pip install "misaki[zh]"`. Japanese also `pip install "misaki[ja]"`, which builds pyopenjtalk: on Windows install Visual Studio Build Tools with the C++ workload first | `pip install vieneu soundfile` (CPU via ONNX Runtime, no torch; NVIDIA GPU: see [its README](https://github.com/pnnbao97/VieNeu-TTS)) |
| Default voice | by `"language"` in slides.json: `en` `am_michael` (US male; `af_heart` is the best-rated female voice), `es` `ef_dora`, `fr` `ff_siwis`, `hi` `hf_alpha`, `it` `if_sara`, `ja` `jf_alpha`, `pt` `pf_dora`, `zh` `zf_xiaobei`. `--voice` picks another. A language outside the two engines stops the run unless `--voice` or `--engine files` is given | "Hai Dang" (northern male; `--voice` accepts preset names with or without tone marks) |
| Settings | speed per line 0.88 to 1.10 by its role | temperature 0.6, top_k 25, top_p 0.9, repetition penalty 1.2, silence 0.15, denoise |
| Pace | `natural`: speed and pauses vary with each line | `slow`: the model's own speed, 0.85 s after a sentence, 1.3 s after a question, 1.0 s before a turn, plus or minus 12% |
| Never | | time-stretch it (atempo sounds like a slowed-down tape) |
| Measured | about 2.3 to 2.8 words per second | about 4.3 words per second speaking, 3.2 with pauses |
| Licence | Apache 2.0 | Apache 2.0 |

Both run on CPU; a GPU (even 4 GB) makes them several times faster. The first line of the first video downloads the model and prints nothing meanwhile: Kokoro 330 MB (it also pip-installs a 13 MB spaCy English model into the environment), VieNeu 580 MB. `edge` (edge-tts, Microsoft online voices) exists only to test the pipeline quickly; its terms for commercial use are unclear, so do not publish with it.

Tell the skill which Python runs an engine that lives in its own virtual environment:

```bash
export KOKORO_PYTHON=/path/to/kokoro-venv/bin/python      # Windows: set KOKORO_PYTHON=C:\path\to\kokoro\.venv\Scripts\python.exe
```

## 2. How the voice is made (`make_voice.py`)

Line by line, each line to a WAV, joined with silences into an mp3 plus `timeline.json` (start and end of every line, exact, no forced alignment). Lines are cached in `<file_name>.voice.mp3.cache/` by a hash of text and voice: editing one line regenerates that line only; delete the cache after changing the voice. `|N` at the end of a line adds N seconds of silence. A line that is only `.` is 1.2 s of silence (a silent slide). Every run goes through `gpu_lock.py` so it does not fight Whisper or another job for the GPU.

## 3. Pronunciation fixes (for the voice only, captions keep the real spelling)

`PRONUNCIATION` in `make_voice.py`, one table per engine. It is almost empty on purpose (Kokoro has one pair: its own name, read as "Koh-koh-roh"): current engines read most product names and loan words correctly, and a respelling can make a good word bad (a test once turned a correctly read English word into nonsense in Vietnamese). Add a pair only after hearing the error and hearing the fix come out right. Typical candidates: unusual names (Kokoro read the Vietnamese name "Chuong" as "Qiwang"; "Chung" fixed it), acronyms you want spelled out, brand names with an unusual stress.

When a word keeps failing, try two or three spellings, or change the word in `slides.json` (the narration there is the source of truth).

## 4. The Whisper review (`review_voice.py`, part of every run)

faster-whisper large-v3 (int8_float16 fits a 4 GB GPU) transcribes the mp3 and compares it with `narration.txt`: different words (after normalising numbers, percentages and ranges, so "20%" equals "twenty percent") and, for Vietnamese, **wrong tones** (same letters, different diacritics). Each problem comes with mm:ss so you can listen: `ffmpeg -ss 1:23 -t 4 -i <voice.mp3> clip.wav`.

Filtered automatically and listed at the end of the report: a single short word (4 letters or fewer, not a term or a name) that Whisper heard differently; text Whisper invents over music or silence ("thanks for watching", "subscribe"); anything a second listen (beam 10, primed with the script line) hears correctly. When something is left, `make_video.py` regenerates just those lines (the engines sample, so a second take is usually right) and re-checks just those lines, up to three rounds, instead of listening to the whole lesson again.

In English, the same words spelled two ways are not an error: the review compares a compact form (number words as digits, no spaces or hyphens), so "lesson two" and "lesson 2", "mac os" and "macos" count as equal. Pairs that every English lesson meets (Whisper writes "clawed" or "cloud" for "Claude", "jason" for "JSON") live in `assets/whisper-homophones-en.txt`, one `said>heard` per line, and are loaded for every English review. Add a pair there only after listening; a pair that belongs to one lesson goes in that lesson's exceptions file.

If Whisper misheard (you listened and the voice is right), add the word, or `said>heard`, to `_check/voice-exceptions.txt`. Do not switch to a smaller Whisper model to make a finding go away: small models invent whole sentences. `--skip-review` is an emergency exit for pipeline tests only; say so in the report.

### Model, device, memory

| Variable | Default | When to change it |
|---|---|---|
| `WHISPER_MODEL` | `large-v3`, a 3.1 GB download on the first run (nothing is printed while it downloads) | `medium` (1.5 GB) on a machine without an NVIDIA GPU or with less than 16 GB of RAM, where large-v3 on the CPU needs several GB of free memory and can take many minutes per minute of audio. Expect a few more false alarms; listen, then add them to the exceptions file. `small` (0.5 GB) only to test the pipeline. Vietnamese stays on `large-v3`: the tone check depends on it |
| `WHISPER_DEVICE` | `cuda` when CTranslate2 finds a GPU (int8_float16), else `cpu` (int8) | `cpu` when the GPU is busy or its CUDA libraries do not load. When CUDA fails the script falls back to the CPU by itself and says so |
| `CUDA_DLL_DIRS` | empty | Windows with a GPU: extra folders holding the cuBLAS and cuDNN DLLs, separated by `;`. The script already adds PyTorch's `lib` folder and the `nvidia-*` pip packages of the environment |

The review prints `loading Whisper <model> on <device>` before it loads. Write in the report which model reviewed the voice when it was not `large-v3`.

## 5. Narration rules (from the slide step)

One spoken beat per line, 5 to 20 words, ending in `. , ?`; numbers written as they are said; never read the slide word for word; spoken language and one way of addressing the learner; question slides say "pause the video". If the narration itself is wrong, long or stiff, fix it in the lesson or slide step and rebuild. The video step does not rewrite content.
