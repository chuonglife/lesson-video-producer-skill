#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Composite REAL SCREEN RECORDINGS (how-to, hands-on and software demos) into the rendered slide video.

Usage:
  python composite_clips.py <storyboard.json> <timeline.json> <video.json> <base.mp4> <out.mp4>
  python composite_clips.py --first-frame <clip.mp4> <out.png> [seconds]   # a frame of the clip to put on the slide

In video.json, the "clip" of a slide:
  "S07": {"clip": {"file": "clips/S07-chatgpt.mp4", "start": 0, "length": 24, "mode": "frame", "speed": "auto"}}
    file    clip path (relative to the lesson's video folder, or absolute)
    start / length   where to start in the clip and how many seconds to use (no length = to the end)
    mode    "frame": the clip sits inside the slide's frame (clip_frame from the storyboard: the largest rounded box,
            for example the picture frame of a two-column or image slide; or give x, y, w, h);
            "full": the clip covers the whole 1920x1080 picture, the slide only shows while it comes in and goes out
    speed   time factor (1.15 = 15% slower); "auto" stretches 0.8x to 1.25x to fit the slide. Never faster than 1.25x:
            learners cannot follow a sped-up demo.
  A clip shorter than the slide holds its last frame. A clip longer than the slide is cut, with a WARNING: add "hold"
  to that slide or run make_video.py --extend, which adds the hold for you.
The base video's audio (voice, effects, music) is kept; the clip's own audio is dropped.
Run check_motion.py on every clip first (and smooth_scroll.py if it finds jumps).
"""
import json
import subprocess
import sys
from pathlib import Path

DELAY = 0.5     # the clip appears once the slide transition has nearly finished
FADE = 0.35


def duration(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def first_frame(clip, out, sec="0.3"):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(sec), "-i", clip, "-frames:v", "1", out], check=True)
    print("wrote", out)


def frame_of(slide, c):
    if all(k in c for k in ("x", "y", "w", "h")):
        return c["x"], c["y"], c["w"], c["h"]
    bb = slide.get("clip_frame") or (max(slide["regions"], key=lambda v: v["bbox"][2] * v["bbox"][3])["bbox"] if slide.get("regions") else None)
    if not bb:
        return 320, 262, 1280, 720
    x, y, w, h = bb
    if w / h > 16 / 9:          # keep 16:9 inside the frame, centred
        w2 = int(h * 16 / 9); x += (w - w2) // 2; w = w2
    else:
        h2 = int(w * 9 / 16); y += (h - h2) // 2; h = h2
    return x, y, w // 2 * 2, h // 2 * 2


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--first-frame":
        first_frame(*sys.argv[2:5]); return
    board_p, tl_p, ov_p, base, out = sys.argv[1:6]
    board = json.loads(Path(board_p).read_text(encoding="utf-8"))
    tl = json.loads(Path(tl_p).read_text(encoding="utf-8"))
    ov = json.loads(Path(ov_p).read_text(encoding="utf-8")) if Path(ov_p).is_file() else {}
    root = Path(ov_p).resolve().parent
    starts = [l["start"] for l in tl["lines"]]
    total = tl["duration"]
    slides = board["slides"]
    clips = [(sid, o["clip"]) for sid, o in ov.items() if isinstance(o, dict) and o.get("clip")]
    if not clips:
        print("no clips in video.json: copying the base video")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", base, "-c", "copy", out], check=True)
        return
    inputs, chains, last, errors = ["-i", base], [], "[0:v]", []
    for k, (sid, c) in enumerate(clips):
        i = next(j for j, s in enumerate(slides) if s["id"] == sid)
        t_in = (0 if i == 0 else starts[slides[i]["from_line"] - 1]) + DELAY
        t_out = (starts[slides[i + 1]["from_line"] - 1] if i + 1 < len(slides) else total) - 0.08
        span = t_out - t_in
        f = Path(c["file"]); f = f if f.is_absolute() else root / f
        if not f.is_file():
            errors.append(f"{sid}: clip not found {f}"); continue
        ss = float(c.get("start", 0))
        length = float(c.get("length") or max(0.1, duration(f) - ss))
        speed = c.get("speed", 1.0)
        if speed == "auto":
            speed = min(1.25, max(0.8, (span - 0.4) / length))
        played = length * speed
        if played > span + 0.2:
            print(f"WARNING {sid}: the clip is {played - span:.1f} s longer than the slide and gets cut (add a hold or use --extend)")
        full = c.get("mode", "frame") == "full"
        x, y, w, h = (0, 0, 1920, 1080) if full else frame_of(slides[i], c)
        inputs += ["-i", str(f)]
        n = k + 1
        chains.append(
            f"[{n}:v]trim=start={ss}:duration={length},setpts=(PTS-STARTPTS)*{speed},fps=30,scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,tpad=stop_mode=clone:stop_duration={max(0, span - played) + 1:.2f},"
            f"trim=duration={span:.3f},format=yuva420p,fade=t=in:st=0:d={FADE}:alpha=1,fade=t=out:st={max(0, span - FADE):.3f}:d={FADE}:alpha=1,"
            f"setpts=PTS+{t_in:.3f}/TB[c{n}]")
        chains.append(f"{last}[c{n}]overlay=x={x}:y={y}:eof_action=pass:enable='between(t,{t_in:.3f},{t_out:.3f})'[v{n}]")
        last = f"[v{n}]"
        print(f"clip {sid}: {t_in:.2f} to {t_out:.2f} s ({'full screen' if full else f'{w}x{h} at {x},{y}'}), {length:.1f} s x {speed:.2f}")
    if errors:
        raise SystemExit("\n".join(errors))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(chains), "-map", last, "-map", "0:a?",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", out], check=True)
    print("wrote", out)


if __name__ == "__main__":
    main()
