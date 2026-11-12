#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
RECORD ONE WINDOW for a how-to or hands-on lesson, with smooth scrolling. Windows 10/11 (ffmpeg gfxcapture).
On macOS or Linux record with OBS or ffmpeg (avfoundation / x11grab) instead; check_motion.py, smooth_scroll.py and
composite_clips.py work with any recording.

Usage:
  python record_screen.py <out.mp4> --window "<part of the window title>" [--seconds 30] [--crop-top 0]
                          [--scroll "<start s>:<px per s>:<seconds>" ...] [--size 1280x720]
  python record_screen.py --list           # print the open windows to pick a title

  --window    the window to record, matched on its title (case-insensitive). gfxcapture records it even when covered.
  --seconds   recording length (default 30). Stop early by creating the file <out.mp4>.stop
  --crop-top  remove N pixels at the top (title bar, address bar).
  --scroll    SMOOTH scroll of the recorded window with many small wheel steps (60 per second); "4:220:3" scrolls down
              220 px per second for 3 s starting at second 4. Negative speed scrolls up. Repeat for several scrolls.
  --size      scale to this size after cropping (default: keep, rounded to even). Use 1280x720 for clips placed in a slide.
When the recording ends the script runs check_motion.py; if it still finds jumps it prints the smooth_scroll.py command.

Note: a window that does not change produces no new frames, so ffmpeg would not stop by itself; the script nudges the
window when stopping so ffmpeg receives a last frame. Never record a browser that shows a real account in a side bar:
use a private window and look at the top band of the clip.
"""
import argparse
import ctypes
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
if sys.platform != "win32":
    raise SystemExit("record_screen.py needs Windows (ffmpeg gfxcapture). On macOS/Linux record with OBS or ffmpeg, "
                     "then use check_motion.py, smooth_scroll.py and composite_clips.py on the clip.")
import win32con  # noqa: E402  (pywin32)
import win32gui  # noqa: E402

HERE = Path(__file__).resolve().parent
user32 = ctypes.windll.user32


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def wheel(delta):
    inp = INPUT(type=0)
    inp.mi = MOUSEINPUT(0, 0, ctypes.c_ulong(delta & 0xFFFFFFFF).value, 0x0800, 0, None)  # MOUSEEVENTF_WHEEL
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def list_windows():
    found = []
    def cb(h, acc):
        if win32gui.IsWindowVisible(h) and win32gui.GetWindowText(h).strip():
            l, t, r, b = win32gui.GetWindowRect(h)
            acc.append((win32gui.GetWindowText(h), r - l, b - t))
    win32gui.EnumWindows(cb, found)
    for title, w, h in found:
        print(f"{w:5}x{h:<5} {title}")


def find_window(part):
    hits = []
    def cb(h, _):
        if win32gui.IsWindowVisible(h) and part.lower() in win32gui.GetWindowText(h).lower():
            hits.append(h)
    win32gui.EnumWindows(cb, None)
    return hits[0] if hits else None


def nudge(hwnd):
    win32gui.SetWindowPos(hwnd, 0, 0, 0, 0, 0, win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOZORDER | win32con.SWP_FRAMECHANGED)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?")
    ap.add_argument("--window"); ap.add_argument("--seconds", type=float, default=30)
    ap.add_argument("--crop-top", dest="crop_top", type=int, default=0)
    ap.add_argument("--scroll", action="append", default=[])
    ap.add_argument("--size"); ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        list_windows(); return
    if not a.out or not a.window:
        raise SystemExit("Give <out.mp4> and --window (see --list).")
    hwnd = find_window(a.window)
    if not hwnd:
        raise SystemExit(f"No window whose title contains: {a.window}")
    print("recording:", win32gui.GetWindowText(hwnd))
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    l, t, r, b = win32gui.GetWindowRect(hwnd)
    vf = ["hwdownload", "format=bgra"]
    if a.crop_top:
        vf.append(f"crop=iw:ih-{a.crop_top}:0:{a.crop_top}")
    if a.size:
        w, h = a.size.lower().split("x")
        vf.append(f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2")
    else:
        vf.append("crop=trunc(iw/2)*2:trunc(ih/2)*2")
    vf += ["fps=30", "format=yuv420p"]
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    stop = Path(str(out) + ".stop")
    stop.unlink(missing_ok=True)
    ff = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"gfxcapture=hwnd={hwnd}:capture_cursor=1:max_framerate=30",
                           "-t", f"{a.seconds + 30:.1f}", "-vf", ",".join(vf), "-fps_mode", "cfr", "-c:v", "libx264", "-preset", "veryfast",
                           "-crf", "18", "-pix_fmt", "yuv420p", str(out)], stdin=subprocess.PIPE)
    plan = sorted(tuple(float(v) for v in s.split(":")) for s in a.scroll)
    t0 = time.time()
    try:
        nudge(hwnd)
        while True:
            el = time.time() - t0
            if el >= a.seconds or stop.exists():
                break
            for start, speed, length in plan:
                if start <= el < start + length:
                    user32.SetCursorPos((l + r) // 2, (t + b) // 2 + a.crop_top // 2)
                    step = int(round(-speed / 60 * 1.2))   # one notch (120) is about 100 px
                    if step:
                        wheel(step)
                    break
            time.sleep(1 / 60)
    finally:
        try:
            ff.stdin.write(b"q"); ff.stdin.flush()
        except Exception:
            pass
        for _ in range(40):
            if ff.poll() is not None:
                break
            nudge(hwnd); time.sleep(0.25)
        if ff.poll() is None:
            ff.terminate()
        stop.unlink(missing_ok=True)
    print("recorded", out, f"({time.time() - t0:.1f} s)")
    if subprocess.run([sys.executable, str(HERE / "check_motion.py"), str(out)]).returncode:
        print(f"Jumps found: python \"{HERE / 'smooth_scroll.py'}\" \"{out}\" \"{out.with_suffix('.smooth.mp4')}\"")


if __name__ == "__main__":
    main()
