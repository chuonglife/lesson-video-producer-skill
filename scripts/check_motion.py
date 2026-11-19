#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Check a video for JUMPY SCROLLING: content that moves vertically by a large amount within a single frame. Run it on every
screen recording and every finished video. A still image never shows this defect; only measurement does.

Usage:  python check_motion.py <video.mp4> [region X Y W H]
  region: measure inside a rectangle only (coordinates in the video's resolution), e.g. a recording placed in a 1080p
  video at x=320 y=262 w=1280 h=720:  region 320 262 1280 720
Prints the number of jumps (a vertical shift of 40 px or more at 1280 wide within one frame) and when they happen.
Exit code 1 if there is any.
"""
import subprocess
import sys

import numpy as np


def read_frames(path, region):
    info = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,r_frame_rate",
                           "-of", "csv=p=0", path], capture_output=True, text=True).stdout.strip().split(",")
    w, h = int(info[0]), int(info[1])
    num, den = info[2].split("/")
    fps = float(num) / float(den)
    vf = []
    if region:
        x, y, cw, ch = region
        vf.append(f"crop={cw}:{ch}:{x}:{y}")
        w, h = cw, ch
    sw = 320
    sh = int(h * sw / w) // 2 * 2
    vf += [f"scale={sw}:{sh}", "format=gray"]
    p = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-i", path, "-vf", ",".join(vf), "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
    n, frames = sw * sh, []
    while True:
        b = p.stdout.read(n)
        if len(b) < n:
            break
        frames.append(np.frombuffer(b, np.uint8).reshape(sh, sw).astype(np.float32))
    return frames, fps, w, sw


def vertical_shift(a, b):
    A = np.fft.fft2(a - a.mean()); B = np.fft.fft2(b - b.mean())
    R = A * np.conj(B); R /= np.abs(R) + 1e-6
    r = np.fft.ifft2(R).real
    y, x = np.unravel_index(np.argmax(r), r.shape)
    h, w = r.shape
    if y > h // 2:
        y -= h
    if x > w // 2:
        x -= w
    return y, x, float(r.max())


def find_jumps(path, region=None):
    """List of (seconds, vertical shift in px) for every jump."""
    frames, fps, w, sw = read_frames(path, region)
    scale = (1280 / sw) if not region else (region[2] / sw)
    limit = 40 * (w / 1280) / scale
    jumps = []
    for i in range(len(frames) - 1):
        if np.abs(frames[i + 1] - frames[i]).mean() < 1.0:
            continue
        y, x, peak = vertical_shift(frames[i], frames[i + 1])
        if abs(y) >= limit and abs(x) < 4 and peak > 0.25:
            jumps.append((round((i + 1) / fps, 2), int(y * scale)))
    return len(frames), jumps


def main(path, region=None, ignore=()):
    """ignore: slide start times; jumps within 0.9 s of them are slide transitions, not scrolling."""
    n, jumps = find_jumps(path, region)
    real = [(t, d) for t, d in jumps if not any(-0.9 <= t - b <= 0.9 for b in ignore)]
    print(f"{path}: {n} frames, {len(real)} jumps" + (f" at {real[:12]}" if real else ""))
    return 1 if real else 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"):
        print(__doc__); sys.exit(0 if a else 2)
    if len(a) > 1 and not (len(a) >= 6 and a[1] == "region"):
        sys.exit("Usage: check_motion.py <video> [region X Y W H]")
    import preflight
    preflight.need("ffmpeg", "ffprobe")
    sys.exit(main(a[0], tuple(int(v) for v in a[2:6]) if len(a) >= 6 else None))
