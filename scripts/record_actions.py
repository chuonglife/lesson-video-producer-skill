#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
RECORD FROM AN ACTION SCRIPT (Windows): the machine opens a terminal window, types, presses keys, waits, scrolls and
clicks from a script file while record_screen.py records it (with the action log), masks private text by itself, stops
by itself and writes the action table. This is the DEFAULT way to record software how-to lessons; recording by hand is
the fallback.

Usage:
  python record_actions.py <clip.actions.json> [--dry-run] [--skip-review "<reason>"]
      --dry-run      run the steps without recording (to check a script)
      --skip-review  waive the review_result rule, with a reason (printed and stored in <clip>.take.json)

The action script (paths are relative to the script file; see templates/actions.example.json):
  {"out": "S03-claude.mp4", "out_size": "1920x1080", "max_seconds": 900, "hide_typing": true, "language": "en",
   "window": {"command": ["claude"], "cwd": "D:/demo-course", "title": "REC-S03", "size": [1600, 900], "font_zoom": 2},
   "masks": [{"box": [0, 0, 1920, 60], "kind": "solid"}],    fixed masks in output pixels, "solid" | "blur"
   "private": ["Jane Doe"],                                   extra strings to mask (emails, API keys, C:\\Users\\<name> always are)
   "steps": [ ... ]}
  Steps:
   {"pause": 2}                                  stand still N seconds (the viewer reads)
   {"type": "create a file hello.txt", "pace": [0.025, 0.04]}   types like a person (KEYEVENTF_UNICODE: an input method
       such as a Vietnamese Telex IME cannot change the text). "secret": true allows a string that looks private;
       otherwise the script is refused
   {"key": "Enter"} | "Esc" | "Ctrl+C" | "Shift+Tab" | "Up" | "1", "repeat": 2
       after Enter, if the shell answers "is not recognized" (the command is not on the PATH) the recording STOPS;
       "allow_error": true on the step turns that off
   {"wait_still": 3, "max": 60}                  until the window has not changed for 3 s (at most 60)
   {"wait_text": "Do you want", "max": 30}       until the text shows in the terminal (UI Automation reads the real text, no OCR)
   {"wait_done": {"busy": "esc to interrupt", "still": 3, "max": 600,
                  "answer": [{"text": "Do you want", "keys": "Enter"}]}}
       until Claude Code (or any program) is done: the busy text appeared and is gone, and the window is still for N s;
       any matching prompt is answered with the given keys (a list for several keys). Without UI Automation it only waits
       for a still window.
   {"wait_file": {"file": "course/INDEX.md", "max": 21600, "nudge": "Continue", "nudge_every": 900,
                  "busy": "esc to interrupt", "answer": [{"text": "Do you want", "keys": "Enter"}]}}
       for very long jobs that run in the background and hand the turn back several times: wait until the file exists
       (relative to the window's cwd); every nudge_every s, if it is still missing and the busy text is not on screen,
       type the nudge and Enter; prompts are answered as in wait_done
   {"if_text": {"text": "All lessons built", "goto_mark": "result"}}
       if the text is on screen now (case-sensitive), skip every step up to the mark named "result" (for example the job
       is already done, no need to type "Continue"); the mark must come later in the script
   {"review_result": {"speed": 160, "dwell": 2.5, "files": ["notes.md"], "zoom": [0, 0, 0.6, 0.6]}}
       REQUIRED after every finished job: scroll up to the start of the answer and read down at a readable speed, stop at
       each chunk; open each text file the job wrote in a new tab of the SAME recorded window (Get-Content), scroll through
       it, hold. This becomes a READING segment: never fast-forwarded, never cut.
   {"scroll": -400, "seconds": 2}                smooth scroll (px, negative = up) over N seconds
   {"click": [0.5, 0.4]} | {"move": [0.5, 0.4], "seconds": 0.6}   window-relative (0..1) or pixel coordinates
   {"mark": "S03"}                               a named mark: long_take.py starts a new segment here
Outputs next to the clip: <out>.mp4, <out>.events.jsonl (action log), <out>.take.json (marks, reading segments, masks,
zoom), then long_take.py analyse runs -> <out>.longtake.json + the action table.
Privacy: before and during the recording the visible terminal text is scanned 3 times a second; emails, API keys and
paths with the Windows user name become timed masks. The scan reads the terminal through UI Automation (the comtypes
package, in requirements.txt). When it is not available the script REFUSES to record instead of recording unmasked;
"scan_private": false in the action script turns the scan off on purpose (then only the fixed "masks" apply).
Focus: before every step the recorded window is brought to the front (synthetic Alt, AttachThreadInput,
SwitchToThisWindow, a click on its own title bar, up to 6 tries); if it still is not in front the script STOPS without
sending a key. A PowerShell window loads the PATH of this process and the registry, aliases 'claude' to the real
executable and drops CLAUDE_* before its prompt; after typing 'claude' there, give it about 8 s ({"pause": 8}).
Close leftover recording windows with close_recording_windows.py before a new take.
"""
import argparse
import ctypes
import importlib.util
import json
import os
import random
import re
import shutil
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
    raise SystemExit("record_actions.py needs Windows (Windows Terminal, SendInput, UI Automation).")
HERE = Path(__file__).resolve().parent
ctypes.windll.shcore.SetProcessDpiAwareness(2)
try:
    import win32gui  # noqa: E402  (pywin32, after DPI awareness)
except ImportError:
    raise SystemExit(f"pywin32 is missing in {sys.executable}. Install it: \"{sys.executable}\" -m pip install pywin32 comtypes "
                     "(both are in requirements.txt), or run with the Python of the project's .venv.")

u = ctypes.windll.user32
VK = {"enter": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B, "backspace": 0x08, "space": 0x20, "delete": 0x2E, "insert": 0x2D,
      "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28, "home": 0x24, "end": 0x23, "pgup": 0x21, "pgdn": 0x22,
      "ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B, **{f"f{i + 1}": 0x70 + i for i in range(12)}, "=": 0xBB, "-": 0xBD}
USER = os.environ.get("USERNAME", "")
PRIVATE = [("email", r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
           ("key", r"\b(?:sk-[A-Za-z0-9_-]{10,}|AIza[0-9A-Za-z_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[bpas]-[A-Za-z0-9-]{10,})"),
           ("path", r"[A-Za-z]:[\\/]+Users[\\/]+" + re.escape(USER) + r"\b" if USER else r"$^"),
           ("path", r"/(?:home|Users)/" + re.escape(USER) + r"\b" if USER else r"$^")]
TEXT_FILES = {".md", ".txt", ".json", ".csv", ".gift", ".py", ".js", ".html", ".yml", ".yaml", ".vtt", ".srt", ".log"}


class KI(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("extra", ctypes.c_void_p)]


class MI(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("data", wintypes.DWORD), ("flags", wintypes.DWORD), ("time", wintypes.DWORD), ("extra", ctypes.c_void_p)]


class INP(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", KI), ("mi", MI), ("pad", ctypes.c_byte * 32)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def _send(i):
    u.SendInput(1, ctypes.byref(i), ctypes.sizeof(INP))


def vk(code, up=False):
    ext = 1 if code in (0x25, 0x26, 0x27, 0x28, 0x24, 0x23, 0x21, 0x22, 0x2E, 0x2D) else 0
    i = INP(type=1); i.ki = KI(code, u.MapVirtualKeyW(code, 0), (2 if up else 0) | ext, 0, None)
    _send(i)


def unicode(ch):
    """Send one character as KEYEVENTF_UNICODE (VK_PACKET): an input method (Telex/VNI) cannot
    rewrite it (Telex reads the "r" in "for" as a tone mark)."""
    for f in (4, 4 | 2):
        i = INP(type=1); i.ki = KI(0, ord(ch), f, 0, None); _send(i); time.sleep(0.012)


def press(name):
    parts = [p.strip() for p in name.split("+")]
    mods = [VK[p.lower()] for p in parts[:-1]]
    k = parts[-1]
    if not mods and len(k) == 1:
        unicode(k); return
    code = VK.get(k.lower()) or (u.VkKeyScanW(ord(k.lower())) & 0xFF if len(k) == 1 else None)
    if code is None:
        raise SystemExit(f"unknown key: {name}")
    for m in mods:
        vk(m)
    vk(code); time.sleep(0.03); vk(code, True)
    for m in reversed(mods):
        vk(m, True)


def type_text(text, pace):
    a, b = pace
    for ch in text:
        unicode(ch) if ch != "\n" else press("Shift+Enter")
        d = random.uniform(a, b)
        if ch in " ,." and random.random() < 0.09:
            d += random.uniform(0.12, 0.38)     # a light hesitation, like a person
        time.sleep(d)


def wheel(delta):
    i = INP(type=0); i.mi = MI(0, 0, ctypes.c_ulong(delta & 0xFFFFFFFF).value, 0x0800, 0, None); _send(i)


def button(down):
    i = INP(type=0); i.mi = MI(0, 0, 0, 2 if down else 4, 0, None); _send(i)


# ---------------------------------------------------------------- window and terminal text
def frame_rect(hwnd):
    r = wintypes.RECT()
    if ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(r), ctypes.sizeof(r)) == 0:
        return r.left, r.top, r.right, r.bottom
    return win32gui.GetWindowRect(hwnd)


def to_front(hwnd, tries=6):
    """Bring the recorded window to the front, or STOP. Another window (a notification, an office suite starting in the
    background, the taskbar) can hold the focus for a moment: try again, 1.5 s apart, before giving up. Keys are never sent
    to a window that is not the recorded one."""
    for k in range(tries):
        try:
            return _to_front(hwnd)
        except SystemExit:
            if k == tries - 1:
                raise
            time.sleep(1.5)


def _to_front(hwnd):
    if u.GetForegroundWindow() == hwnd:
        return
    vk(0x12); vk(0x12, True)          # a synthetic Alt lets Windows change the foreground window
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass
    if u.GetForegroundWindow() != hwnd:
        # Windows refuses to change the foreground window while another one holds the focus: attach our input thread to
        # the thread that holds it, then bring the window up
        k32 = ctypes.windll.kernel32
        fg = u.GetForegroundWindow()
        t_fg = u.GetWindowThreadProcessId(fg, None)
        t_me = k32.GetCurrentThreadId()
        u.AttachThreadInput(t_me, t_fg, True)
        try:
            u.BringWindowToTop(hwnd); u.ShowWindow(hwnd, 5)
            try:
                win32gui.SetForegroundWindow(hwnd)
            except Exception:
                pass
            u.SetFocus(hwnd)
        finally:
            u.AttachThreadInput(t_me, t_fg, False)
    time.sleep(0.15)
    if u.GetForegroundWindow() != hwnd:
        # when the taskbar holds the focus SetForegroundWindow is blocked; SwitchToThisWindow still works
        u.SwitchToThisWindow(hwnd, True); time.sleep(0.4)
    if u.GetForegroundWindow() != hwnd:
        # last resort: click the title bar of THE RECORDED WINDOW, only if that point really belongs to it (never click another window)
        L, T, R, _B = frame_rect(hwnd)
        x, y = int(L + (R - L) * 0.6), int(T + 14)
        target = u.GetAncestor(u.WindowFromPoint(wintypes.POINT(x, y)), 2)
        if target == hwnd:
            pt = wintypes.POINT(); u.GetCursorPos(ctypes.byref(pt))
            u.SetCursorPos(x, y); time.sleep(0.08)
            button(True); time.sleep(0.05); button(False); time.sleep(0.4)
            u.SetCursorPos(pt.x, pt.y)
    if u.GetForegroundWindow() != hwnd:
        raise SystemExit("STOPPED: could not bring the recorded window to the front (another window holds the focus). No keys were sent.")


class TermText:
    """Reads Windows Terminal text with UI Automation (comtypes). Without it .ok is False and text waits fall back to still waits."""

    def __init__(self, hwnd):
        self.ok, self.tp, self.hwnd = False, None, hwnd
        try:
            import comtypes.client
            comtypes.client.GetModule("UIAutomationCore.dll")
            from comtypes.gen import UIAutomationClient as U
            self.U = U
            self.uia = comtypes.client.CreateObject(U.CUIAutomation, interface=U.IUIAutomation)
            self._find()
        except Exception as e:
            print("UI Automation not available:", e)

    def _find(self):
        el = self.uia.ElementFromHandle(self.hwnd)
        al = el.FindAll(4, self.uia.CreatePropertyCondition(30040, True))
        cands = [al.GetElement(i) for i in range(al.Length)]
        cands = [c for c in cands if c.CurrentClassName == "TermControl"] or cands
        if cands:
            self.tp = cands[0].GetCurrentPattern(10014).QueryInterface(self.U.IUIAutomationTextPattern)
            self.ok = True

    def _visible(self):
        # ONLY the visible part: reading the whole buffer (DocumentRange) several times a second locks Windows Terminal's
        # buffer, the terminal stops drawing, gfxcapture gets no frames and keystrokes stall (measured: a 0.6 s clip instead of 7 s)
        a = self.tp.GetVisibleRanges()
        return [a.GetElement(i) for i in range(a.Length)]

    def read(self):
        if not self.ok:
            return ""
        for _ in range(2):
            try:
                return "\n".join(r.GetText(-1) for r in self._visible())
            except Exception:
                try:
                    self._find()
                except Exception:
                    return ""
        return ""

    def rects_of(self, s, limit=30):
        """Screen rectangles (physical pixels) where the string s is visible."""
        out = []
        try:
            for doc in self._visible():
                r = doc.FindText(s, False, False)
                while r is not None and len(out) < limit:
                    b = r.GetBoundingRectangles()
                    out += [tuple(b[i:i + 4]) for i in range(0, len(b) - 3, 4)]
                    nxt = doc.Clone()
                    nxt.MoveEndpointByRange(0, r, 1)     # search on from the end of the last hit
                    r = nxt.FindText(s, False, False)
        except Exception:
            pass
        return out


def private_in(text, extra=()):
    hits = []
    for kind, pat in PRIVATE:
        hits += [(kind, m.group(0)) for m in re.finditer(pat, text)]
    for s in extra:
        if s and s.lower() in text.lower():
            i = text.lower().index(s.lower()); hits.append(("private", text[i:i + len(s)]))
    return hits


class PrivacyScan(threading.Thread):
    """Scans the visible terminal text 3 times a second: each private string on screen is logged (wall time, screen rect, kind)."""

    def __init__(self, hwnd, extra):
        super().__init__(daemon=True)
        self.hwnd, self.extra, self.stop, self.hits = hwnd, extra, False, []

    def run(self):
        import comtypes
        comtypes.CoInitialize()
        tt = TermText(self.hwnd)
        while not self.stop:
            t = time.time()
            for kind, s in set(private_in(tt.read(), self.extra)):
                for rc in tt.rects_of(s):
                    self.hits.append((t, rc, kind))
            time.sleep(max(0.05, 0.33 - (time.time() - t)))


def grab(hwnd):
    from PIL import ImageGrab
    import numpy as np
    L, T, R, B = frame_rect(hwnd)
    return np.asarray(ImageGrab.grab(bbox=(L, T, R, B), all_screens=True).convert("L").resize((320, 180))).astype(np.int16)


def wait_still(hwnd, seconds, limit, threshold=0.002, condition=None):
    """Wait until the window has been still for `seconds` (share of changed pixels < threshold every 0.25 s) and condition() holds."""
    import numpy as np
    t0 = time.time(); prev = grab(hwnd); still_since = time.time()
    while time.time() - t0 < limit:
        time.sleep(0.25)
        cur = grab(hwnd)
        if float((np.abs(cur - prev) > 24).mean()) >= threshold:
            still_since = time.time()
        prev = cur
        if time.time() - still_since >= seconds and (condition is None or condition()):
            return time.time() - t0
    print(f"  {limit} s passed without {seconds} s of stillness, going on")
    return time.time() - t0


def point(hwnd, p):
    L, T, R, B = frame_rect(hwnd)
    x, y = p
    return (L + x * (R - L), T + y * (B - T)) if 0 <= x <= 1 and 0 <= y <= 1 else (L + x, T + y)


def smooth_scroll(hwnd, px, speed):
    """Scroll px pixels (negative = up) at speed px/s in 60 small wheel steps a second (the smooth-scroll rule)."""
    L, T, R, B = frame_rect(hwnd)
    u.SetCursorPos((L + R) // 2, (T + B) // 2)
    n = max(1, int(abs(px) / max(1.0, speed) * 60))
    step = -px / n * 1.2           # one notch (120) is about 100 px
    acc = 0.0
    for _ in range(n):
        acc += step
        d = int(round(acc))
        acc -= d
        if d:
            wheel(d)
        time.sleep(1 / 60)


def read_down(hwnd, total, speed, chunk, dwell):
    """Read from the top: scroll `chunk` px at reading speed, stop `dwell` s for the viewer, until `total` px are done."""
    done = 0.0
    while done < total - 1:
        x = min(chunk, total - done)
        smooth_scroll(hwnd, x, speed)
        done += x
        time.sleep(dwell)


def review_result(hwnd, title, win, c, warnings):
    """Required after every job: scroll up to the start of the answer, read down at a readable speed with a stop at each
    chunk; open each text file the job wrote in a new tab of the SAME recorded window (Get-Content), scroll through, hold."""
    speed, dwell = float(c.get("speed", 160)), float(c.get("dwell", 2.5))
    L, T, R, B = frame_rect(hwnd)
    chunk = float(c.get("chunk_px", (B - T) * 0.4))
    time.sleep(1.0)
    if c.get("scroll", True):
        up = float(c.get("up_px") or (B - T) * 1.2)
        smooth_scroll(hwnd, -up, speed * 2.5)
        time.sleep(dwell)
        read_down(hwnd, up, speed, chunk, dwell)
    for name in c.get("files", []):
        p = Path(name)
        p = p if p.is_absolute() else Path(win["cwd"]) / p
        if p.suffix.lower() not in TEXT_FILES:
            warnings.append(f"{p.name}: a {p.suffix} file cannot be opened inside the recorded window (text files only); record its viewer separately or show it on a slide")
            print("  WARNING:", warnings[-1]); continue
        if not p.is_file():
            warnings.append(f"{p.name}: file not found (the job did not write it?)")
            print("  WARNING:", warnings[-1]); continue
        n_lines = len(p.read_text(encoding="utf-8", errors="replace").splitlines())
        subprocess.Popen(["wt.exe", "-w", win["name"], "new-tab", "--title", title, "--suppressApplicationTitle", "-d", str(win["cwd"]),
                          "powershell", "-NoLogo", "-NoExit", "-Command", f"Get-Content -LiteralPath '{p}' -Encoding UTF8"], env=win["env"])
        time.sleep(2.5)
        to_front(hwnd)
        total = n_lines * float(c.get("line_px", 26))
        if total > (B - T) * 0.7:
            smooth_scroll(hwnd, -(total + 120), speed * 2.5)
            time.sleep(dwell)
            read_down(hwnd, total, speed, chunk, dwell)
        time.sleep(max(dwell, float(c.get("hold", 3))))
        press("Ctrl+Shift+W")     # close the file tab, back to the program tab
        time.sleep(1.0)
    time.sleep(float(c.get("hold", 3)))


# ---------------------------------------------------------------- script checks
def check_review(script, waived=None):
    """The rule: after every finished job (wait_done with "busy") there must be a review_result step before the next typing
    or before the end of the script. Waived only with a reason (script "skip_review", step "no_review", or --skip-review)."""
    if waived or script.get("skip_review"):
        return []
    errors, pending = [], None
    for i, b in enumerate(script["steps"], 1):
        if "wait_done" in b and (b["wait_done"].get("busy") or "") and not b.get("no_review"):
            pending = i
        elif "review_result" in b:
            pending = None
        elif "type" in b and pending:
            errors.append(f"step {pending}: a job finished but there is no review_result before the typing in step {i}")
            pending = None
    if pending:
        errors.append(f"step {pending}: a job finished and the script ends without a review_result")
    return errors


def check_private(script):
    errors = []
    for i, b in enumerate(script["steps"], 1):
        typed = b.get("type") or ((b.get("wait_file") or {}).get("nudge") if "wait_file" in b else None)
        if typed and not b.get("secret"):
            for kind, s in private_in(typed, script.get("private", [])):
                errors.append(f"step {i}: the typed text contains a {kind} ({s[:3]}...); remove it, or mark the step \"secret\": true if it must be typed")
    return errors


def check_jumps(script):
    """An if_text step must name a mark that comes AFTER it; otherwise every remaining step would be skipped silently."""
    errors, steps = [], script["steps"]
    for i, b in enumerate(steps, 1):
        if "if_text" in b:
            c = b["if_text"] or {}
            if not c.get("text") or not c.get("goto_mark"):
                errors.append(f"step {i}: if_text needs \"text\" and \"goto_mark\"")
            elif not any(s.get("mark") == c["goto_mark"] for s in steps[i:]):
                errors.append(f"step {i}: if_text jumps to mark '{c['goto_mark']}', which is not a later step")
    return errors


def check_exit(script):
    """Warnings (not refusals): typing /exit or exit while Claude Code may still run background work (an install, a render)
    shows 'Background work is running'; Enter there picks 'Exit and stop tasks' and kills the work. Before /exit, wait a
    second time for Claude to say it is done (wait_done with a long start_within, or wait_file)."""
    out, last_wait = [], None
    for i, b in enumerate(script["steps"], 1):
        if "wait_done" in b or "wait_file" in b:
            last_wait = i
        if "type" in b and b["type"].strip().lower() in ("/exit", "exit", "/quit"):
            out.append(f"step {i}: types '{b['type'].strip()}'. If the job started background work, Claude Code asks 'Background work is running' "
                       f"and Enter stops it. Make sure a wait before it (the last one is step {last_wait or 'none'}) lasts until Claude reports "
                       "the work is done (wait_done with a long start_within, or wait_file). At the end of a script there is no need to exit: "
                       "the machine stops recording, then closes the window.")
    return out


def find_command(name):
    """Full path of the program. wt.exe runs commands with the PATH of the Windows Terminal process already running, which
    may be stale ('claude' -> 0x80070002), and the npm shim (a small claude.exe + claude.cmd) does not start under wt:
    take the real executable that claude.cmd points to (node_modules/.../bin/claude.exe)."""
    if Path(name).is_absolute():
        return name
    w = shutil.which(name)
    if not w:
        return name
    cmdf = Path(w).with_suffix(".cmd")
    if cmdf.is_file():
        m = re.search(r'"%dp0%\\([^"]+)"', cmdf.read_text(encoding="utf-8", errors="replace"))
        if m and (cmdf.parent / m.group(1)).is_file():
            return str(cmdf.parent / m.group(1))
    return w


def open_window(w, base):
    title = w.get("title") or f"REC-{int(time.time())}"
    cwd = Path(w.get("cwd") or base)
    cwd = cwd if cwd.is_absolute() else base / cwd
    cmd = w.get("command") or ["powershell", "-NoLogo"]
    cmd = list(cmd) if isinstance(cmd, list) else [cmd]
    cmd[0] = find_command(cmd[0])
    # wt.exe opens the tab in the Windows Terminal process that is ALREADY RUNNING, so the PATH and the environment are
    # those of the moment Terminal started, not those of this script: typing 'claude' in PowerShell then says "is not
    # recognized". For a PowerShell window, a small .ps1 runs silently before the prompt (nothing shows on screen): it
    # loads the PATH of this process plus the registry (Machine + User), points 'claude' at the real executable (the npm
    # shim claude.ps1/.cmd is not found inside the Terminal session even with the right PATH) and removes CLAUDE_*.
    if Path(cmd[0]).stem.lower() in ("powershell", "pwsh") and not any(x.lower() in ("-command", "-c", "-file", "-f") for x in cmd[1:]):
        loader = Path(os.environ.get("TEMP", str(base))) / "record_actions_env.ps1"
        path = os.environ.get("PATH", "").replace("'", "''")
        claude = find_command("claude")
        loader.write_text(f"$env:Path = '{path}' + ';' + [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + "
                          "[Environment]::GetEnvironmentVariable('Path','User')\n"
                          + (f"Set-Alias -Name claude -Value '{claude.replace(chr(39), chr(39) * 2)}' -Scope Global\n" if Path(claude).is_absolute() else "")
                          + "Get-ChildItem env: | Where-Object { $_.Name -like 'CLAUDE*' } | ForEach-Object { Remove-Item \"env:$($_.Name)\" }\n"
                          "Clear-Host\n", encoding="utf-8-sig")   # a BOM, so Windows PowerShell 5.1 reads non-ASCII paths right
        cmd = cmd + ["-NoExit", "-ExecutionPolicy", "Bypass", "-File", str(loader)]
    if any(";" in x for x in cmd):
        raise SystemExit("the window command contains ';': wt.exe splits commands at ';'. Put a long command in a .ps1/.cmd file and call that.")
    # a clean environment: the CLAUDE_* variables of the controlling session would leak into claude in the recorded window
    # and show "inherited CLAUDE_CODE_CHILD_SESSION marker" on screen
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("CLAUDE_", "CLAUDECODE"))}
    name = re.sub(r"\W", "_", title)       # a named window, so review_result can open a tab in the SAME window
    subprocess.Popen(["wt.exe", "-w", name, "--title", title, "--suppressApplicationTitle", "-d", str(cwd), *cmd], env=env)
    for _ in range(120):
        time.sleep(0.25)
        acc = []
        win32gui.EnumWindows(lambda h, a: a.append(h) if win32gui.IsWindowVisible(h) and title in win32gui.GetWindowText(h) else None, acc)
        if acc:
            hwnd = acc[0]; break
    else:
        raise SystemExit(f"could not open the terminal window '{title}' (wt.exe)")
    width, height = w.get("size", [1600, 900])
    x, y = w.get("position", [40, 20])
    time.sleep(0.6)
    win32gui.ShowWindow(hwnd, 9)
    win32gui.SetWindowPos(hwnd, 0, int(x), int(y), int(width), int(height), 0x0040)
    time.sleep(0.5); to_front(hwnd); time.sleep(0.4)
    for _ in range(int(w.get("font_zoom", 0))):
        press("Ctrl+="); time.sleep(0.15)
    return hwnd, title, {"name": name, "cwd": cwd, "env": env}


# ---------------------------------------------------------------- run
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("script"); ap.add_argument("--dry-run", dest="dry_run", action="store_true")
    ap.add_argument("--skip-review", dest="skip_review", help="waive the review_result rule, with a REASON")
    a = ap.parse_args()
    sp = Path(a.script).resolve(); base = sp.parent
    if not sp.is_file():
        raise SystemExit(f"action script not found: {sp}")
    try:
        script = json.loads(sp.read_text(encoding="utf-8-sig"))
    except ValueError as e:
        raise SystemExit(f"{sp} is not valid JSON: {e}")
    import preflight
    preflight.need("ffmpeg", "ffprobe")
    errors = check_private(script)
    if errors:
        raise SystemExit("SCRIPT REFUSED (private text in typed strings):\n" + "\n".join(errors))
    errors = check_review(script, a.skip_review)
    if errors:
        raise SystemExit("SCRIPT REFUSED (missing result review: scroll through the whole answer, open the files the job wrote):\n"
                         + "\n".join(errors) + '\nAdd {"review_result": {...}} after the wait_done step; to waive it use --skip-review "<reason>".')
    errors = check_jumps(script)
    if errors:
        raise SystemExit("SCRIPT REFUSED (if_text):\n" + "\n".join(errors))
    for w in check_exit(script):
        print("WARNING:", w)
    waived = a.skip_review or script.get("skip_review")
    if waived:
        print("review_result rule WAIVED, reason:", waived)
    hide = bool(script.get("hide_typing", True)) or any(b.get("secret") for b in script["steps"])
    # The private-text scan (emails, API keys, C:\Users\<name> masked while on screen) reads the terminal through UI Automation,
    # which needs comtypes. Without it nothing would be masked, so a recording is refused unless the script opts out.
    scan_on = bool(script.get("scan_private", True))
    no_uia = ("the terminal text cannot be read (UI Automation), so private text on screen (emails, API keys, C:\\Users\\<name>) would NOT "
              "be masked, prompts would not be answered and a command that is not found would not stop the take. "
              f"Install comtypes: \"{sys.executable}\" -m pip install comtypes (it is in requirements.txt). To record without the scan on "
              "purpose, set \"scan_private\": false in the action script and cover private areas with \"masks\".")
    if scan_on and importlib.util.find_spec("comtypes") is None:
        if not a.dry_run:
            raise SystemExit("RECORDING REFUSED: comtypes is not installed, so " + no_uia)
        print("WARNING (dry run): comtypes is not installed, so " + no_uia)
    if not scan_on:
        print("private-text scan is OFF (\"scan_private\": false): only the fixed \"masks\" of the script are applied")
    out = Path(script["out"]); out = out if out.is_absolute() else base / out
    out.parent.mkdir(parents=True, exist_ok=True)
    hwnd, title, win = open_window(script.get("window") or {}, base)
    tt = TermText(hwnd)
    print(f"window '{title}' {frame_rect(hwnd)}; terminal text: {'yes (UI Automation)' if tt.ok else 'no, still waits only'}")
    if scan_on and not tt.ok and not a.dry_run:
        win32gui.PostMessage(hwnd, 0x10, 0, 0)
        raise SystemExit("RECORDING REFUSED: UI Automation did not start for the recorded window (see the line above), so " + no_uia)
    wait_still(hwnd, 1.5, 20)
    first = tt.read()
    if "when launching" in first or "cannot find the file" in first:
        win32gui.PostMessage(hwnd, 0x10, 0, 0)
        raise SystemExit("THE PROGRAM DID NOT START in the terminal, verbatim:\n" + first.strip())
    hits = private_in(first, script.get("private", []))
    if hits:
        print(f"first frame check: {len(hits)} private strings on screen ({', '.join(sorted({k for k, _ in hits}))}); they will be masked")
    scan, rec = None, None
    if not a.dry_run:
        if tt.ok and script.get("scan_private", True):
            scan = PrivacyScan(hwnd, script.get("private", [])); scan.start()
        cmd = [sys.executable, "-u", str(HERE / "record_screen.py"), str(out), "--window", title, "--seconds", str(script.get("max_seconds", 900)),
               "--size", script.get("out_size", "1920x1080"), "--log-events"] + (["--hide-typing"] if hide else []) + \
            ([] if script.get("cursor", any("click" in b or "move" in b for b in script["steps"])) else ["--no-cursor"])
        rec = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        log = []
        threading.Thread(target=lambda: [log.append(l) or print("  [rec]", l.rstrip()) for l in rec.stdout], daemon=True).start()
        while not any(l.startswith("recording:") for l in log):
            if rec.poll() is not None:
                raise SystemExit("record_screen.py stopped early")
            time.sleep(0.05)
        time.sleep(1.2)
    marks, reading, warnings = [], [], []
    t_start = time.time()
    skip_to = None    # set by if_text: skip every step up to the named mark
    for i, b in enumerate(script["steps"], 1):
        if skip_to is not None:
            if b.get("mark") == skip_to:
                skip_to = None
            else:
                continue
        if "if_text" in b:
            c = b["if_text"]
            # case-sensitive on purpose: the same words in the prompt typed earlier must not trigger the jump
            if tt.ok and c["text"] in tt.read():
                print(f"[{time.time() - t_start:6.1f}s] step {i}: saw '{c['text']}' -> jump to mark '{c['goto_mark']}'")
                skip_to = c["goto_mark"]
            continue
        to_front(hwnd)
        shown = json.dumps(b, ensure_ascii=False) if "type" not in b or not hide else json.dumps({**b, "type": f"<{len(b['type'])} characters>"})
        print(f"[{time.time() - t_start:6.1f}s] step {i}: {shown[:110]}")
        if "pause" in b:
            time.sleep(float(b["pause"]))
        elif "type" in b:
            type_text(b["type"], b.get("pace", [0.025, 0.04]))
        elif "key" in b:
            before = tt.read().count("is not recognized as") if tt.ok else 0
            for _ in range(int(b.get("repeat", 1))):
                press(b["key"]); time.sleep(0.12)
            # a command that does not run (for example 'claude' not on the PATH): STOP NOW, do not type the prompt into the shell
            if tt.ok and b["key"].lower() == "enter" and not b.get("allow_error"):
                time.sleep(1.5)
                if tt.read().count("is not recognized as") > before:
                    print("  visible text (end):", " | ".join(l.strip() for l in tt.read().splitlines() if l.strip())[-600:])
                    if rec:
                        Path(str(out) + ".stop").write_text("x")
                        try:
                            rec.wait(20)
                        except subprocess.TimeoutExpired:
                            pass
                    win32gui.PostMessage(hwnd, 0x10, 0, 0)
                    raise SystemExit(f"STOPPED at step {i}: the shell says 'is not recognized' (the command is not on the PATH). Recording stopped.")
        elif "wait_still" in b:
            wait_still(hwnd, float(b["wait_still"]), float(b.get("max", 60)), float(b.get("threshold", 0.002)))
        elif "wait_text" in b:
            t0 = time.time()
            while time.time() - t0 < float(b.get("max", 30)) and b["wait_text"].lower() not in tt.read().lower():
                time.sleep(0.25)
            if not tt.ok:
                wait_still(hwnd, 2, float(b.get("max", 30)))
        elif "wait_done" in b:
            c = b["wait_done"]; busy = (c.get("busy") or "").lower(); rules = c.get("answer", [])
            t0, answered = time.time(), 0.0
            if busy and tt.ok:   # the busy text must APPEAR first (up to start_within s), otherwise "done" would fire before the start
                while time.time() - t0 < float(c.get("start_within", 15)) and busy not in tt.read().lower():
                    time.sleep(0.2)
                txt = tt.read()
                print(f"  {'saw' if busy in txt.lower() else 'did NOT see'} '{busy}' after {time.time() - t0:.1f} s")
                if busy not in txt.lower():
                    # print the last visible lines (private strings masked) so the script writer can pick the right busy text
                    for _, s in private_in(txt, script.get("private", [])):
                        txt = txt.replace(s, "[masked]")
                    print("  visible text (end):", " | ".join(l.strip() for l in txt.splitlines() if l.strip())[-300:])

            def done():
                nonlocal answered
                txt = tt.read().lower()
                for r in rules:
                    if r["text"].lower() in txt and time.time() - answered > 2.0:
                        print(f"  saw '{r['text']}' -> {r['keys']}")
                        time.sleep(float(r.get("delay", 1.2)))   # let the viewer see the prompt
                        for k in (r["keys"] if isinstance(r["keys"], list) else [r["keys"]]):
                            press(k); time.sleep(0.25)
                        answered = time.time()
                        return False
                return not (busy and busy in txt)
            wait_still(hwnd, float(c.get("still", 3)), float(c.get("max", 600)), float(c.get("threshold", 0.002)), done if tt.ok else None)
            print(f"  done after {time.time() - t0:.0f} s")
        elif "wait_file" in b:
            # very long jobs: Claude Code works in the background and hands the turn back several times, so the screen says
            # "done" long before the job is. Wait for the RESULT FILE instead. Every nudge_every seconds, if the file is still
            # missing AND the screen is not busy, type the nudge (for example "Continue") and Enter.
            c = b["wait_file"]; f = Path(c["file"]); f = f if f.is_absolute() else Path(win["cwd"]) / f
            t0, last_nudge, busy = time.time(), time.time(), (c.get("busy") or "esc to interrupt").lower()
            while not f.exists() and time.time() - t0 < float(c.get("max", 21600)):
                time.sleep(5)
                txt = tt.read() if tt.ok else ""
                for r in c.get("answer", []):
                    if r["text"].lower() in txt.lower():
                        print(f"  saw '{r['text']}' -> {r['keys']}"); to_front(hwnd)
                        for k in (r["keys"] if isinstance(r["keys"], list) else [r["keys"]]):
                            press(k); time.sleep(0.25)
                if c.get("nudge") and time.time() - last_nudge > float(c.get("nudge_every", 900)) and busy not in txt.lower():
                    print(f"  [{time.time() - t_start:6.1f}s] {f.name} not there yet and the screen is idle: nudging")
                    to_front(hwnd); type_text(c["nudge"], [0.008, 0.016]); time.sleep(0.5); press("Enter")
                    last_nudge = time.time()
            print(f"  {'found' if f.exists() else 'TIME IS UP, still no'} {f.name} after {time.time() - t0:.0f} s")
        elif "scroll" in b:
            p = point(hwnd, b.get("at", [0.5, 0.5])); u.SetCursorPos(int(p[0]), int(p[1]))
            n = max(1, int(float(b.get("seconds", 2)) * 60)); step = int(round(-float(b["scroll"]) / n * 1.2))
            for _ in range(n):
                wheel(step); time.sleep(1 / 60)
        elif "click" in b or "move" in b:
            p = point(hwnd, b.get("click") or b.get("move"))
            pt = wintypes.POINT(); u.GetCursorPos(ctypes.byref(pt))
            n = max(1, int(float(b.get("seconds", 0.5)) * 60))
            for k in range(1, n + 1):
                e = k / n; e = e * e * (3 - 2 * e)
                u.SetCursorPos(int(pt.x + (p[0] - pt.x) * e), int(pt.y + (p[1] - pt.y) * e)); time.sleep(1 / 60)
            if "click" in b:
                button(True); time.sleep(0.06); button(False)
        elif "mark" in b:
            marks.append({"name": b["mark"], "wall": time.time()})
        elif "review_result" in b:
            t0 = time.time()
            review_result(hwnd, title, win, b["review_result"] or {}, warnings)
            reading.append({"wall0": t0, "wall1": time.time(), "zoom": (b["review_result"] or {}).get("zoom")})
        else:
            print("  skipping an unknown step:", b)
    if a.dry_run:
        print("dry run finished (nothing recorded)"); return
    time.sleep(float(script.get("hold_end", 1.5)))
    stop = Path(str(out) + ".stop")
    stop.write_text("x")
    rec.wait()
    stop.unlink(missing_ok=True)
    if scan:
        scan.stop = True; scan.join(2)
    if script.get("close_window", True) and win32gui.IsWindow(hwnd):
        win32gui.PostMessage(hwnd, 0x10, 0, 0)
    ev_p = out.with_name(out.stem + ".events.jsonl")
    head = json.loads(ev_p.read_text(encoding="utf-8").splitlines()[0])
    t0w = head["t0_wall"]
    L, T, R, B = head["window_rect"]; w_out, h_out = head["size"]; ct = head.get("crop_top", 0)
    k = min(w_out / (R - L), h_out / (B - T - ct)); ox, oy = (w_out - (R - L) * k) / 2, (h_out - (B - T - ct) * k) / 2
    masks = []
    for t, (x, y, w, h), kind in sorted(scan.hits if scan else [], key=lambda m: m[0]):
        box = [round((x - L) * k + ox - 6), round((y - T - ct) * k + oy - 4), round(w * k + 12), round(h * k + 8)]
        tt_ = t - t0w
        for m in masks:
            if m["type"] == kind and all(abs(p - q) <= 4 for p, q in zip(m["box"], box)) and tt_ - m["to"] <= 0.6:
                m["to"] = round(tt_ + 0.35, 2); break
        else:
            masks.append({"from": round(max(0, tt_ - 0.35), 2), "to": round(tt_ + 0.35, 2), "box": box, "kind": "solid", "type": kind})
    for m in script.get("masks", []):
        masks.append({"from": m.get("from", 0), "to": m.get("to", 1e9), "box": m["box"], "kind": m.get("kind", "solid"), "type": "script"})
    zoom = []
    for d in reading:
        if d.get("zoom"):    # window-relative (0..1) -> clip pixels
            rx, ry, rw, rh = d["zoom"]
            zoom.append({"from": round(d["wall0"] - t0w + 0.5, 2), "to": round(d["wall1"] - t0w, 2), "ease": 0.8,
                         "box": [round(rx * (R - L) * k + ox), round(ry * (B - T - ct) * k + oy), round(rw * (R - L) * k), round(rh * (B - T - ct) * k)]})
    take = {"script": sp.name, "marks": [{"name": m["name"], "t": round(m["wall"] - t0w, 2)} for m in marks], "masks": masks,
            "reading": [[round(d["wall0"] - t0w, 2), round(d["wall1"] - t0w, 2)] for d in reading], "zoom": zoom,
            "warnings": warnings, "skip_review_reason": waived}
    tp = out.with_name(out.stem + ".take.json")
    tp.write_text(json.dumps(take, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {tp.name}: {len(marks)} marks, {len(reading)} reading segments, {len(masks)} masks ({sum(1 for m in masks if m['type'] != 'script')} automatic)")
    subprocess.run([sys.executable, str(HERE / "long_take.py"), "analyse", str(out), "--language", script.get("language", "en")]
                   + (["--mode", script["wait_mode"]] if script.get("wait_mode") else []))


if __name__ == "__main__":
    main()
