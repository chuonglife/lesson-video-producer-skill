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

Long-take mode (long_take.py, see references/screen-recording.md section 6):
  --log-events   write an ACTION LOG <out>.events.jsonl: seconds, mouse clicks (in clip pixels), keys and key combos, wheel.
                 OFF BY DEFAULT. Only for your own recordings on your own machine. Only logs while the recorded window is
                 in front (typing into another window is not logged). With this flag x264 runs with -tune zerolatency so
                 the log's seconds match the frames, and the mp4 is fragmented so a forced stop cannot lose the recording.
  --hide-typing  never write typed characters: only "typed" (no character) and keys / combos such as Ctrl+C, Enter, Tab.
                 Use it whenever a password, an API key or private data might be typed. The text is not in the file, so
                 no later step can show it.
  --no-cursor    do not record the mouse pointer (scripted recordings that do not use the mouse).
Before recording the script warns when a Vietnamese input method (UniKey, EVKey, OpenKey...) runs or the keyboard layout
of the window is not en-US: such an input method rewrites typed text ("for lesson" became "fỏ leson").
"""
import argparse
import ctypes
import json
import os
import signal
import subprocess
import sys
import threading
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


# ---------- action log (--log-events) ----------
KEY_NAMES = {0x0D: "Enter", 0x09: "Tab", 0x1B: "Esc", 0x08: "Backspace", 0x20: "Space", 0x2E: "Delete", 0x2D: "Insert",
             0x25: "Left", 0x26: "Up", 0x27: "Right", 0x28: "Down", 0x24: "Home", 0x23: "End", 0x21: "PgUp", 0x22: "PgDn",
             **{0x70 + i: f"F{i + 1}" for i in range(12)}}
MODIFIERS = {0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C, 0x14}
INPUT_METHODS = ("unikey", "evkey", "openkey", "gotiengviet", "vietkey")


def warn_input_method(hwnd):
    """A Vietnamese input method (Telex/VNI) rewrites typed text in the recording. Check its process and the window's
    keyboard layout; print a warning, do not block (the input method may be in E/English mode)."""
    found = []
    try:
        tasks = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True, errors="replace").stdout.lower()
        found += [f"process {t}" for t in INPUT_METHODS if t in tasks]
    except Exception:
        pass
    try:
        lang = user32.GetKeyboardLayout(user32.GetWindowThreadProcessId(hwnd, None)) & 0xFFFF
        if lang and lang != 0x0409:
            found.append(f"keyboard layout 0x{lang:04X} (not en-US 0x0409)")
    except Exception:
        pass
    if found:
        print("INPUT METHOD WARNING: " + "; ".join(found) + ". Switch the Vietnamese input method to E/English (and the keyboard "
              "to en-US) before recording, or typed text changes (\"for lesson\" became \"fỏ leson\").")
    return found


def visible_rect(hwnd):
    """The visible window frame (DWM, physical pixels): what gfxcapture records, without the invisible borders."""
    r = wintypes.RECT()
    if ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(r), ctypes.sizeof(r)) == 0:
        return r.left, r.top, r.right, r.bottom
    return win32gui.GetWindowRect(hwnd)


class ActionLog:
    """Low-level keyboard + mouse hooks (WH_KEYBOARD_LL / WH_MOUSE_LL) on a thread with its own message loop."""

    def __init__(self, hwnd, hide_typing):
        self.hwnd, self.hide, self.ev, self.tid = hwnd, hide_typing, [], None
        self.th = threading.Thread(target=self._run, daemon=True)

    def _in_front(self):
        fg = user32.GetForegroundWindow()
        return fg == self.hwnd or user32.GetAncestor(fg, 2) == self.hwnd

    def _key(self, vk, scan=0):
        if vk == 0xE7:   # VK_PACKET: a Unicode character sent directly (an input method, a typing tool); scan holds the character
            return {"kind": "type", "packet": True} if self.hide else {"kind": "type", "packet": True, "char": chr(scan)}
        if vk in MODIFIERS:
            return None
        down = lambda k: bool(user32.GetAsyncKeyState(k) & 0x8000)
        ctrl, alt, shift, win = down(0x11), down(0x12), down(0x10), down(0x5B) or down(0x5C)
        name = KEY_NAMES.get(vk)
        if ctrl or alt or win:
            if name is None:
                c = user32.MapVirtualKeyW(vk, 2) & 0xFFFF
                name = chr(c).upper() if c else f"VK{vk:02X}"
            mods = [m for m, b in (("Ctrl", ctrl), ("Alt", alt), ("Win", win), ("Shift", shift)) if b]
            return {"kind": "key", "name": "+".join(mods + [name])}
        if name is not None and name != "Space":
            return {"kind": "key", "name": ("Shift+" if shift else "") + name}
        if self.hide:
            return {"kind": "type"}
        st = (ctypes.c_ubyte * 256)()
        if shift:
            st[0x10] = 0x80
        if user32.GetKeyState(0x14) & 1:
            st[0x14] = 1
        buf = ctypes.create_unicode_buffer(8)
        n = user32.ToUnicode(vk, user32.MapVirtualKeyW(vk, 0), st, buf, 8, 4)
        return {"kind": "type", "char": buf.value[:n]} if n > 0 else {"kind": "type"}

    def _run(self):
        LRESULT = ctypes.c_ssize_t
        PROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        user32.CallNextHookEx.restype = LRESULT
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, PROC, ctypes.c_void_p, wintypes.DWORD]
        user32.SetWindowsHookExW.restype = ctypes.c_void_p
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetAncestor.restype = wintypes.HWND
        user32.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]

        class KB(ctypes.Structure):
            _fields_ = [("vk", wintypes.DWORD), ("scan", wintypes.DWORD), ("flags", wintypes.DWORD), ("time", wintypes.DWORD), ("extra", ctypes.c_void_p)]

        class MS(ctypes.Structure):
            _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG), ("data", wintypes.DWORD), ("flags", wintypes.DWORD), ("time", wintypes.DWORD), ("extra", ctypes.c_void_p)]

        def kb(n, w, l):
            if n == 0 and w in (0x100, 0x104):
                try:
                    if self._in_front():
                        k = ctypes.cast(l, ctypes.POINTER(KB)).contents
                        e = self._key(k.vk, k.scan)
                        if e:
                            e["t"] = time.time(); self.ev.append(e)
                except Exception:
                    pass
            return user32.CallNextHookEx(None, n, w, l)

        def ms(n, w, l):
            if n == 0 and w in (0x201, 0x204, 0x20A):
                try:
                    if self._in_front():
                        m = ctypes.cast(l, ctypes.POINTER(MS)).contents
                        self.ev.append({"t": time.time(), "kind": {0x201: "click", 0x204: "click", 0x20A: "wheel"}[w],
                                        "button": {0x201: "left", 0x204: "right"}.get(w), "sx": m.x, "sy": m.y})
                except Exception:
                    pass
            return user32.CallNextHookEx(None, n, w, l)

        self._keep = (PROC(kb), PROC(ms))   # keep references, or Python frees the callbacks
        self.tid = ctypes.windll.kernel32.GetCurrentThreadId()
        h1 = user32.SetWindowsHookExW(13, self._keep[0], None, 0)
        h2 = user32.SetWindowsHookExW(14, self._keep[1], None, 0)
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            pass
        user32.UnhookWindowsHookEx(ctypes.c_void_p(h1)); user32.UnhookWindowsHookEx(ctypes.c_void_p(h2))

    def start(self):
        self.th.start()
        while self.tid is None:
            time.sleep(0.01)

    def stop(self):
        user32.PostThreadMessageW(self.tid, 0x12, 0, 0)
        self.th.join(2)


def read_progress(ff, stamps):
    """Read ffmpeg -progress: wall time of the first frame = wall time of the report - out_time (zerolatency: ~no encoder lag)."""
    t_us = None
    for line in iter(ff.stdout.readline, b""):
        s = line.decode(errors="replace").strip()
        if s.startswith("out_time_us="):
            try:
                t_us = int(s.split("=")[1])
            except ValueError:
                t_us = None
        elif s.startswith("progress=") and t_us and t_us > 0:
            stamps.append(time.time() - t_us / 1e6)


def write_log(out, log, t0_frame, rect, crop_top, size, w_out, h_out):
    L, T, R, B = rect
    w0, h0 = R - L, B - T - crop_top
    if size:
        k = min(w_out / w0, h_out / h0); ox, oy = (w_out - w0 * k) / 2, (h_out - h0 * k) / 2
    else:
        k, ox, oy = 1.0, 0.0, 0.0
    p = out.with_name(out.stem + ".events.jsonl")
    with open(p, "w", encoding="utf-8") as f:
        f.write(json.dumps({"kind": "head", "clip": out.name, "t0_wall": round(t0_frame, 3), "size": [w_out, h_out], "hide_typing": log.hide,
                            "window_rect": [L, T, R, B], "crop_top": crop_top, "events": len(log.ev)}, ensure_ascii=False) + "\n")
        for e in log.ev:
            e = dict(e); e["t"] = round(e["t"] - t0_frame, 3)
            if "sx" in e:
                e["x"] = round((e.pop("sx") - L) * k + ox); e["y"] = round((e.pop("sy") - T - crop_top) * k + oy)
                if not (0 <= e["x"] < w_out and 0 <= e["y"] < h_out):
                    continue   # a click outside the recorded picture (another window just got clicked)
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    count = {}
    for e in log.ev:
        count[e["kind"]] = count.get(e["kind"], 0) + 1
    print(f"action log: {p} ({', '.join(f'{v} {k}' for k, v in count.items()) or 'no events'}{'; typed text NOT logged' if log.hide else ''})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?")
    ap.add_argument("--window"); ap.add_argument("--seconds", type=float, default=30)
    ap.add_argument("--crop-top", dest="crop_top", type=int, default=0)
    ap.add_argument("--scroll", action="append", default=[])
    ap.add_argument("--size"); ap.add_argument("--list", action="store_true")
    ap.add_argument("--log-events", dest="log_events", action="store_true")
    ap.add_argument("--hide-typing", dest="hide_typing", action="store_true")
    ap.add_argument("--no-cursor", dest="no_cursor", action="store_true")
    a = ap.parse_args()
    if a.log_events:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # mouse coordinates and window rect both in physical pixels
    if a.list:
        list_windows(); return
    if not a.out or not a.window:
        raise SystemExit("Give <out.mp4> and --window (see --list).")
    hwnd = find_window(a.window)
    if not hwnd:
        raise SystemExit(f"No window whose title contains: {a.window}")
    print("recording:", win32gui.GetWindowText(hwnd), flush=True)
    warn_input_method(hwnd)
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
    # action log: zerolatency so the log's seconds match the frames; a fragmented mp4 so a forced stop (a still or closed window
    # gives gfxcapture no frames and ffmpeg never reads 'q') cannot lose the whole clip; remuxed to a normal mp4 afterwards
    extra = ["-tune", "zerolatency", "-progress", "pipe:1", "-stats_period", "0.1",
             "-movflags", "+frag_keyframe+empty_moov+default_base_moof", "-frag_duration", "1000000"] if a.log_events else []
    log, stamps = None, []
    if a.log_events:
        rect = visible_rect(hwnd)
        log = ActionLog(hwnd, a.hide_typing); log.start()
    raw = out.with_suffix(".raw.mp4") if a.log_events else out
    ff = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                           f"gfxcapture=hwnd={hwnd}:capture_cursor={0 if a.no_cursor else 1}:max_framerate=30",
                           "-t", f"{a.seconds + 30:.1f}", "-vf", ",".join(vf), "-fps_mode", "cfr", "-c:v", "libx264", "-preset", "veryfast",
                           "-crf", "18", *extra, "-pix_fmt", "yuv420p", str(raw)], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE if a.log_events else None,
                          creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if a.log_events else 0)
    if a.log_events:
        threading.Thread(target=read_progress, args=(ff, stamps), daemon=True).start()
    plan = sorted(tuple(float(v) for v in s.split(":")) for s in a.scroll)
    t0 = time.time()
    try:
        nudge(hwnd)
        while True:
            el = time.time() - t0
            if el >= a.seconds or stop.exists():
                break
            if a.log_events and not win32gui.IsWindow(hwnd):
                print("the recorded window closed: stopping"); break
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
        for _ in range(12 if a.log_events else 40):
            if ff.poll() is not None:
                break
            if win32gui.IsWindow(hwnd):
                nudge(hwnd)
            time.sleep(0.25)
        if a.log_events and ff.poll() is None:
            # a closed or still window: gfxcapture sends no frames and ffmpeg never reads 'q'. Ctrl+Break lets ffmpeg close the file properly
            os.kill(ff.pid, signal.CTRL_BREAK_EVENT)
            for _ in range(40):
                if ff.poll() is not None:
                    break
                time.sleep(0.25)
        if ff.poll() is None:
            ff.terminate()
        stop.unlink(missing_ok=True)
        if log:
            log.stop()
    if a.log_events:
        r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-c", "copy", "-movflags", "+faststart", str(out)])
        if r.returncode:
            raise SystemExit(f"ERROR: the recording {raw} has no frames (window minimised, closed or not redrawing?). Show the window and record again.")
        raw.unlink()
    print("recorded", out, f"({time.time() - t0:.1f} s)")
    if log:
        t0_frame = min(stamps[:30]) if stamps else t0
        print(f"first frame: {t0_frame - t0:+.2f} s after ffmpeg started ({len(stamps)} progress reports)")
        if a.size:
            w_out, h_out = (int(v) for v in a.size.lower().split("x"))
        else:
            w_out, h_out = (rect[2] - rect[0]) // 2 * 2, (rect[3] - rect[1] - a.crop_top) // 2 * 2
        write_log(out, log, t0_frame, rect, a.crop_top, a.size, w_out, h_out)
    if subprocess.run([sys.executable, str(HERE / "check_motion.py"), str(out)]).returncode:
        print(f"Jumps found: python \"{HERE / 'smooth_scroll.py'}\" \"{out}\" \"{out.with_suffix('.smooth.mp4')}\"")


if __name__ == "__main__":
    main()
