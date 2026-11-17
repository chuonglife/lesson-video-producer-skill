#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CLOSE LEFTOVER RECORDING WINDOWS (Windows) before recording a new clip: every visible window whose title contains
"REC-" (the default title prefix of record_actions.py) or the text given with --match.

Closing a Windows Terminal window that has several tabs with WM_CLOSE shows "Do you want to close all tabs?", and that
dialog ends up in the next clip. So this closes ONE TAB AT A TIME with Ctrl+Shift+W (Windows Terminal does not ask
when a single tab closes), sending Ctrl+C twice first so a running Claude Code stops cleanly. A window that cannot be
brought to the front is closed as a whole instead (no keys go to another window).

Usage:  python close_recording_windows.py [--match "REC-"]
"""
import argparse
import os
import sys
import time

if sys.platform != "win32":
    raise SystemExit("close_recording_windows.py needs Windows.")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import record_actions as ra  # noqa: E402  (sets DPI awareness, then imports win32gui)
import win32gui  # noqa: E402


def recording_windows(match):
    hs = []
    win32gui.EnumWindows(lambda h, a: a.append(h) if win32gui.IsWindowVisible(h) and match in win32gui.GetWindowText(h) else None, hs)
    return hs


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--match", default="REC-", help='text in the window title (default "REC-")')
    a = ap.parse_args()
    for h in recording_windows(a.match):
        for _ in range(12):           # at most 12 tabs per window
            if not win32gui.IsWindow(h):
                break
            try:
                ra.to_front(h, tries=2)
            except SystemExit:
                win32gui.PostMessage(h, 0x10, 0, 0)   # cannot bring it up: close the whole window, never type elsewhere
                break
            ra.press("Ctrl+c"); time.sleep(0.3); ra.press("Ctrl+c"); time.sleep(0.5)
            ra.press("Ctrl+Shift+w"); time.sleep(1.0)
    time.sleep(1)
    left = [win32gui.GetWindowText(h) for h in recording_windows(a.match)]
    print("recording windows left:", left or "none")


if __name__ == "__main__":
    main()
