#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SMOOTH THE SCROLLING of a screen recording: browsers and apps often scroll a whole notch in one frame, which looks like
a jerk in a lesson video. This finds every such jump and replays it over several frames on an ease-in-out curve.

Usage:  python smooth_scroll.py <in.mp4> <out.mp4> [--fixed-bottom PX] [--cursor-template cursor.png] [--start S] [--length S]
  --fixed-bottom      height of a band at the bottom that does not scroll (a chat input box, a status bar). Default 0.
  --cursor-template   a small PNG of the mouse pointer as it appears in the recording: the pointer is removed from the
                      scrolled content and redrawn where it really is, so it does not slide with the page. Optional.
How: for every frame pair whose content shifts vertically (phase correlation), build a panorama from the frame before
and the frame after, then replay the scroll over 12 to 48 frames (about 0.4 s or more) so no frame moves more than about
32 px. Sudden re-layouts that are not a clean scroll are cross-faded instead. The clip keeps its length: replaced
original frames are dropped. Works at any resolution; measure the result again with check_motion.py.
"""
import argparse
import json
import subprocess
import sys

import numpy as np

try:
    import cv2
except ImportError:
    raise SystemExit("OpenCV is missing: pip install opencv-python")

K = 12          # minimum frames to replay one scroll
KMAX = 48       # maximum, while the scroll is still running
RELAYOUT = 9.0  # a frame-to-frame difference this large without a clean shift is a re-layout


def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "json", path],
                       capture_output=True, text=True, check=True)
    s = json.loads(r.stdout)["streams"][0]
    return s["width"], s["height"]


def ease(t):
    """Smooth both ends with a peak speed only ~1.18x the average (smoothstep peaks at 1.5x, too fast for long scrolls)."""
    r = 0.15
    v = 1 / (1 - r)
    if t < r:
        return 0.5 * v * t * t / r
    if t < 1 - r:
        return 0.5 * v * r + v * (t - r)
    return 1 - 0.5 * v * (1 - t) ** 2 / r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("dst")
    ap.add_argument("--fixed-bottom", dest="fixed", type=int, default=0)
    ap.add_argument("--cursor-template", dest="tpl")
    ap.add_argument("--start", default="0"); ap.add_argument("--length", default="0")
    a = ap.parse_args()
    W, H = probe(a.src)
    HS = H - a.fixed                              # scrolling area
    S = max(1, W // 320)                          # downscale factor for fast shift estimates
    MIN_DY = max(8, int(14 * H / 720))
    tpl = cv2.imread(a.tpl) if a.tpl else None
    TH, TW = (tpl.shape[:2] if tpl is not None else (0, 0))

    def find_cursor(f):
        if tpl is None:
            return None
        r = cv2.matchTemplate(np.ascontiguousarray(f), tpl, cv2.TM_CCOEFF_NORMED)
        _, mx, _, loc = cv2.minMaxLoc(r)
        return loc if mx > 0.55 else None

    def without_cursor(f):
        g = np.ascontiguousarray(f.copy())
        loc = find_cursor(g)
        if loc is None:
            return g
        x, y = loc
        m = np.zeros(g.shape[:2], np.uint8)
        m[max(0, y - 12):y + TH + 12, max(0, x - 12):x + TW + 12] = 255
        return cv2.inpaint(g, m, 3, cv2.INPAINT_TELEA)

    def small(f):
        return f[:HS:S, ::S].astype(np.float32).mean(axis=2)

    def shift(a_, b_):
        A = np.fft.fft2(a_ - a_.mean()); B = np.fft.fft2(b_ - b_.mean())
        R = A * np.conj(B); R /= np.abs(R) + 1e-6
        r = np.fft.ifft2(R).real
        y, x = np.unravel_index(np.argmax(r), r.shape)
        h, w = r.shape
        if y > h // 2:
            y -= h
        if x > w // 2:
            x -= w
        return y * S, x * S, float(r.max())

    def refine(f1, f2, y0):
        """Exact vertical shift in pixels: the content of f2 equals f1 moved up by n. Try n around the rough estimate."""
        g1 = f1[:HS, W // 10: W - W // 10].astype(np.float32).mean(axis=2)
        g2 = f2[:HS, W // 10: W - W // 10].astype(np.float32).mean(axis=2)
        best, bn = 1e9, y0
        for n in range(y0 - 6, y0 + 7):
            if n == 0 or abs(n) >= HS - 40:
                continue
            e = np.abs(g1[n:HS - 40] - g2[:HS - 40 - n]).mean() if n > 0 else np.abs(g1[:HS - 40 + n] - g2[-n:HS - 40]).mean()
            if e < best:
                best, bn = e, n
        return bn

    def chained(frames):
        total = 0
        for f1, f2 in zip(frames[:-1], frames[1:]):
            y, x, pk = shift(small(f1), small(f2))
            if abs(y) >= 6 and abs(x) < 8 and pk > 0.2:
                total += refine(f1, f2, y)
        return total

    cmd = ["ffmpeg", "-loglevel", "error", "-ss", a.start]
    if float(a.length) > 0:
        cmd += ["-t", a.length]
    rd = subprocess.Popen(cmd + ["-i", a.src, "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], stdout=subprocess.PIPE)
    wr = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", "30", "-i", "-",
                           "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p", "-movflags", "+faststart", a.dst], stdin=subprocess.PIPE)
    n = W * H * 3

    def read():
        b = rd.stdout.read(n)
        return None if len(b) < n else np.frombuffer(b, np.uint8).reshape(H, W, 3)

    prev = read()
    if prev is None:
        raise SystemExit("could not read any frame")
    wr.stdin.write(prev.tobytes())
    gprev = small(prev)
    scrolls = fades = 0
    while True:
        cur = read()
        if cur is None:
            break
        g = small(cur)
        diff = np.abs(g - gprev).mean()
        dy = 0
        if diff > 1.0:
            y, x, pk = shift(gprev, g)
            if abs(y) >= MIN_DY and abs(x) < 8 and pk > 0.12:
                dy = y
        # a clean vertical shift is a scroll even when it changes many pixels; only frames that no shift explains are cross-faded
        if dy == 0 and diff > RELAYOUT:
            run = [cur]
            for _ in range(K - 1):
                nx = read()
                if nx is None:
                    break
                run.append(nx)
            for j, fr in enumerate(run, 1):
                k = ease(j / len(run))
                wr.stdin.write((prev.astype(np.float32) * (1 - k) + fr.astype(np.float32) * k).astype(np.uint8).tobytes())
            fades += 1
            prev, gprev = run[-1], small(run[-1])
            continue
        if dy != 0:
            scrolls += 1
            run = [cur]
            while True:
                if len(run) >= K and (len(run) >= KMAX or np.abs(small(run[-1]) - small(run[-2])).mean() <= 1.0):
                    break
                nx = read()
                if nx is None:
                    break
                run.append(nx)
            M, last = len(run), run[-1]
            y2, x2, pk2 = shift(gprev, small(last))
            if abs(y2) >= MIN_DY and abs(x2) < 8 and pk2 > 0.2:
                net, use_last = refine(prev, last, y2), True
            else:
                net = chained([prev] + run)          # too far for one measurement: add up the frame pairs
                use_last = net != 0
            if net == 0:
                for fr in run:
                    wr.stdin.write(fr.tobytes())
                prev, gprev = last, small(last)
                continue
            d = abs(net)
            fin = last if use_last else cur
            old, new = (prev, fin) if net > 0 else (fin, prev)
            pano = np.concatenate([without_cursor(old[:HS]), without_cursor(new[:HS])[HS - d:HS]], axis=0)
            cursor = find_cursor(fin)
            M = max(M, int(np.ceil(1.18 * d / 32)))
            for j in range(1, M):
                s_ = int(round(d * ease(j / M)))
                s_ = s_ if net > 0 else d - s_
                view = pano[s_:s_ + HS].copy()
                if cursor is not None and cursor[1] + TH <= HS:
                    x, y = cursor
                    view[y:y + TH, x:x + TW] = fin[y:y + TH, x:x + TW]
                wr.stdin.write(np.concatenate([view, fin[HS:]], axis=0).tobytes())
            wr.stdin.write(last.tobytes())
            prev, gprev = last, small(last)
            continue
        wr.stdin.write(cur.tobytes())
        prev, gprev = cur, g
    wr.stdin.close(); wr.wait(); rd.stdout.close()
    print(f"wrote {a.dst}: smoothed {scrolls} scrolls, cross-faded {fades} re-layouts")


if __name__ == "__main__":
    main()
