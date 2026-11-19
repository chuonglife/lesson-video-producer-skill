#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Shared checks for the programs a run needs (used by the other scripts; nothing to run here).

  need("ffmpeg", "ffprobe")   stop with a clear message when a program is not on the PATH
  tool_message("node")        the message for one missing program: its name, the install command for Windows, macOS
                              and Linux, and the reminder to open a new terminal
  find_browser()              the Chrome, Chromium or Edge executable render.mjs will use (CHROME_PATH first), or None
  browser_message()           the message when no browser is found

Usage:  python preflight.py            check node, ffmpeg, ffprobe and the browser, print what was found
"""
import os
import shutil
import sys
from pathlib import Path

INSTALL = {
    "node": ("Node.js 18 or newer", "winget install OpenJS.NodeJS.LTS", "brew install node",
             "sudo apt install nodejs npm (or https://nodejs.org when the packaged version is older than 18)"),
    "ffmpeg": ("ffmpeg (with ffprobe)", "winget install Gyan.FFmpeg", "brew install ffmpeg", "sudo apt install ffmpeg"),
    "ffprobe": ("ffprobe (it comes with ffmpeg)", "winget install Gyan.FFmpeg", "brew install ffmpeg", "sudo apt install ffmpeg"),
    "soffice": ("LibreOffice", "winget install TheDocumentFoundation.LibreOffice", "brew install --cask libreoffice",
                "sudo apt install libreoffice"),
    "pdftoppm": ("Poppler (pdftoppm)", "winget install oschwartz10612.Poppler", "brew install poppler", "sudo apt install poppler-utils"),
}
BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/chromium", "/usr/bin/chromium-browser", "/snap/bin/chromium",
    str(Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "Application" / "chrome.exe"),
]   # the same list as assets/engine/render.mjs


def tool_message(name):
    label, win, mac, linux = INSTALL.get(name, (name, "", "", ""))
    msg = f"{label} was not found on the PATH (the program `{name}`)."
    if win:
        msg += f" Install it. Windows: {win}. macOS: {mac}. Linux: {linux}."
    return msg + " Then open a new terminal, so the new PATH is picked up, and run the command again."


def missing_tools(*names):
    """The names that are not on the PATH (ffprobe is left out when ffmpeg is missing too: one install brings both)."""
    missing = [n for n in names if not shutil.which(n)]
    return [n for n in missing if not (n == "ffprobe" and "ffmpeg" in missing)]


def need(*names):
    """Stop before any work when a program is missing, instead of a FileNotFoundError traceback in the middle of a run."""
    missing = missing_tools(*names)
    if missing:
        raise SystemExit("\n".join(tool_message(n) for n in missing))


def find_browser():
    for p in [os.environ.get("CHROME_PATH")] + BROWSERS:
        if p and os.path.isfile(p):
            return p
    return None


def browser_message():
    env = os.environ.get("CHROME_PATH")
    head = (f"CHROME_PATH is set to {env}, but that file does not exist, and no" if env else "No")
    return (f"{head} Chrome, Chromium or Edge was found (the frames are rendered in a headless browser). Install one. "
            "Windows: Edge is normally there, or winget install Google.Chrome. macOS: brew install --cask google-chrome. "
            "Linux: sudo apt install chromium. If the browser is installed somewhere else, set CHROME_PATH to its executable "
            "(PowerShell: $env:CHROME_PATH = \"C:\\path\\to\\chrome.exe\"; bash: export CHROME_PATH=/path/to/chrome). "
            "Then open a new terminal and run the command again.")


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        print(__doc__); return 0
    ok = True
    for n in ("node", "ffmpeg", "ffprobe"):
        p = shutil.which(n)
        print(f"{n}: {p}" if p else tool_message(n)); ok = ok and bool(p)
    b = find_browser()
    print(f"browser: {b}" if b else browser_message())
    return 0 if ok and b else 1


if __name__ == "__main__":
    sys.exit(main())
