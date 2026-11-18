#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SMOOTH THE SCROLLING of a screen recording: browsers and apps often scroll a whole notch in one frame, which looks like
a jerk in a lesson video. This finds every such jump and replays it over several frames on an ease-in-out curve.

Usage:  python smooth_scroll.py <in.mp4> <out.mp4> [--fixed-top PX] [--fixed-bottom PX] [--cursor-template cursor.png]
                                [--start S] [--length S]
        python smooth_scroll.py <in.mp4> <out.mp4> --segments <clip.longtake.json> [--work-dir DIR] [--keep-work] [--min-segment 3]
  --fixed-top         height of a band at the top that does not scroll (a tab strip, a title bar). Default 0.
  --fixed-bottom      height of a band at the bottom that does not scroll (a chat input box, a status bar). Default 0.
  --cursor-template   a small PNG of the mouse pointer as it appears in the recording: the pointer is removed from the
                      scrolled content and redrawn where it really is, so it does not slide with the page. Optional.
How: for every frame pair whose content shifts vertically (phase correlation), build a panorama from the frame before
and the frame after, then replay the scroll over 12 to 48 frames (about 0.4 s or more) so no frame moves more than about
32 px. Sudden re-layouts that are not a clean scroll are cross-faded instead. The clip keeps its length: replaced
original frames are dropped (a very long scroll consumes extra original frames; it never inserts new ones, so the clip
and every timestamp measured on it stay valid). Works at any resolution; measure the result again with check_motion.py.

--segments: smooth a long clip piece by piece instead of in one pass, keeping the duration of every piece exactly (so the
seconds in the long-take config and in the action log stay right). The pieces are the "segments" of the config (each
segment starts at its "from"; the first starts at 0, the last ends at the clip end). A piece is left untouched when it is
not longer than --min-segment seconds, when its midpoint falls inside a "waits" entry (a wait is fast-forwarded or cut
later, smoothing it is wasted time and can build a wrong panorama), or when the segment has "smooth": false. Every
other piece is cut (30 fps, crf 12), smoothed, stretched or shrunk back to exactly its length, and all pieces are
joined again (crf 16, no audio). Exits with an error when the output duration differs from the input by more than 0.1 s.
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

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


def duration(path):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)]).decode())


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *map(str, args)], check=True)


def smooth_by_segments(a):
    """--segments mode: cut the clip at the segment starts, smooth only the pieces worth it, join them, same duration."""
    cfg = json.load(open(a.segments, encoding="utf-8"))
    segs = sorted(cfg.get("segments") or [], key=lambda d: float(d["from"]))
    waits = [(float(w["from"]), float(w["to"])) for w in cfg.get("waits") or []]
    src, dst = Path(a.src), Path(a.dst)
    work = Path(a.work_dir) if a.work_dir else dst.with_name(dst.name + ".segments-work")
    work = work.resolve()                         # the concat list needs absolute paths
    work.mkdir(parents=True, exist_ok=True)
    total = duration(src)
    cuts = [0.0] + [float(d["from"]) for d in segs][1:] + [total]
    extra = []
    if a.fixed_top:
        extra += ["--fixed-top", str(a.fixed_top)]
    if a.fixed:
        extra += ["--fixed-bottom", str(a.fixed)]
    if a.tpl:
        extra += ["--cursor-template", a.tpl]
    parts, smoothed = [], 0
    for i in range(len(cuts) - 1):
        t0, t1 = cuts[i], cuts[i + 1]
        d = t1 - t0
        if d <= 0:
            continue
        raw, out = work / f"p{i:02d}.raw.mp4", work / f"p{i:02d}.mp4"
        ffmpeg("-ss", f"{t0:.3f}", "-i", src, "-t", f"{d:.3f}", "-an", "-vf", "fps=30", "-c:v", "libx264", "-crf", "12", "-preset", "fast", raw)
        mid = (t0 + t1) / 2
        in_wait = any(w0 <= mid <= w1 for w0, w1 in waits)
        seg_ok = segs[i].get("smooth", True) if i < len(segs) else True
        if d > a.min_segment and not in_wait and seg_ok:
            sm = work / f"p{i:02d}.sm.mp4"
            subprocess.run([sys.executable, "-X", "utf8", str(Path(__file__).resolve()), str(raw), str(sm), *extra], check=True, capture_output=True)
            ds = duration(sm)
            ffmpeg("-i", sm, "-vf", f"setpts=PTS*{d / ds:.6f},fps=30", "-t", f"{d:.3f}", "-c:v", "libx264", "-crf", "12", "-preset", "fast", out)
            smoothed += 1
        else:
            shutil.copy2(raw, out)
        parts.append(out)
    lst = work / "list.txt"
    lst.write_text("\n".join(f"file '{p.as_posix()}'" for p in parts), encoding="utf-8")
    dst.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg("-f", "concat", "-safe", "0", "-i", lst, "-c:v", "libx264", "-crf", "16", "-preset", "fast", "-pix_fmt", "yuv420p", dst)
    out_len = duration(dst)
    print(f"in {total:.2f} s -> out {out_len:.2f} s; {len(parts)} pieces, smoothed {smoothed}; {dst}")
    if not a.keep_work:
        shutil.rmtree(work, ignore_errors=True)
    if abs(out_len - total) > 0.1:
        sys.exit(f"ERROR: duration differs by {out_len - total:+.2f} s from the input")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("dst")
    ap.add_argument("--fixed-top", dest="fixed_top", type=int, default=0)
    ap.add_argument("--fixed-bottom", dest="fixed", type=int, default=0)
    ap.add_argument("--cursor-template", dest="tpl")
    ap.add_argument("--start", default="0"); ap.add_argument("--length", default="0")
    ap.add_argument("--segments", help="long-take config (.longtake.json): smooth piece by piece, keeping every piece's duration")
    ap.add_argument("--work-dir", dest="work_dir"); ap.add_argument("--keep-work", action="store_true")
    ap.add_argument("--min-segment", dest="min_segment", type=float, default=3.0, help="pieces not longer than this (s) are left as they are")
    a = ap.parse_args()
    if a.segments:
        return smooth_by_segments(a)
    W, H = probe(a.src)
    TOP = a.fixed_top                             # fixed band at the top
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
        return f[TOP:HS:S, ::S].astype(np.float32).mean(axis=2)

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
        g1 = f1[TOP:HS, W // 10: W - W // 10].astype(np.float32).mean(axis=2)
        g2 = f2[TOP:HS, W // 10: W - W // 10].astype(np.float32).mean(axis=2)
        HC = HS - TOP
        best, bn = 1e9, y0
        for n in range(y0 - 6, y0 + 7):
            if n == 0 or abs(n) >= HC - 40:
                continue
            e = np.abs(g1[n:HC - 40] - g2[:HC - 40 - n]).mean() if n > 0 else np.abs(g1[:HC - 40 + n] - g2[-n:HC - 40]).mean()
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
            pano = np.concatenate([without_cursor(old[:HS])[TOP:], without_cursor(new[:HS])[HS - d:HS]], axis=0)
            cursor = find_cursor(fin)
            # a very long scroll needs more frames so no frame moves more than ~32 px: READ (drop) that many more original
            # frames instead of inserting new ones. Inserting made the clip longer and shifted every later timestamp.
            need = int(np.ceil(1.18 * d / 32))
            while M < need:
                if read() is None:
                    break
                M += 1
            for j in range(1, M):
                s_ = int(round(d * ease(j / M)))
                s_ = s_ if net > 0 else d - s_
                view = pano[s_:s_ + HS - TOP].copy()
                if cursor is not None and cursor[1] >= TOP and cursor[1] + TH <= HS:
                    x, y = cursor
                    view[y - TOP:y - TOP + TH, x:x + TW] = fin[y:y + TH, x:x + TW]
                wr.stdin.write(np.concatenate([fin[:TOP], view, fin[HS:]], axis=0).tobytes())
            wr.stdin.write(last.tobytes())
            prev, gprev = last, small(last)
            continue
        wr.stdin.write(cur.tobytes())
        prev, gprev = cur, g
    wr.stdin.close(); wr.wait(); rd.stdout.close()
    print(f"wrote {a.dst}: smoothed {scrolls} scrolls, cross-faded {fades} re-layouts")


if __name__ == "__main__":
    main()
