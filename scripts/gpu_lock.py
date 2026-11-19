#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
A tiny GPU queue based on a lock file: only one heavy GPU job at a time (text-to-speech, Whisper), the next one waits.
Useful on small GPUs (4 to 8 GB) where two models at once make both crawl.

Usage:
  python gpu_lock.py -- <command and arguments...>     run the command while holding the lock, release it afterwards
  python gpu_lock.py --show                             who holds the lock
  python gpu_lock.py --release                          remove a stale lock (only when no job is running)
The lock lives in ~/.gpu-lock/gpu.lock. A lock left by a process that no longer exists is ignored.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

LOCK = Path.home() / ".gpu-lock" / "gpu.lock"


def alive(pid):
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return bool(ok) and code.value == 259
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def read():
    try:
        return json.loads(LOCK.read_text(encoding="utf-8"))
    except Exception:
        return None


def acquire(job):
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    told = False
    while True:
        cur = read()
        if cur and alive(int(cur.get("pid", 0))) and cur.get("pid") != os.getpid():
            if not told:
                print(f"[gpu_lock] waiting: GPU busy with {cur.get('job')} since {cur.get('since')}", flush=True); told = True
            time.sleep(5); continue
        try:
            fd = os.open(str(LOCK) + ".tmp", os.O_CREAT | os.O_WRONLY | os.O_TRUNC)
            os.write(fd, json.dumps({"pid": os.getpid(), "job": job[:120], "since": time.strftime("%H:%M:%S")}).encode())
            os.close(fd)
            os.replace(str(LOCK) + ".tmp", LOCK)
        except OSError:
            time.sleep(1); continue
        if (read() or {}).get("pid") == os.getpid():
            return


def release():
    cur = read()
    if cur and cur.get("pid") == os.getpid():
        LOCK.unlink(missing_ok=True)


def main():
    a = sys.argv[1:]
    if a[:1] == ["--show"]:
        print(read() or "free"); return 0
    if a[:1] == ["--release"]:
        LOCK.unlink(missing_ok=True); print("released"); return 0
    if a[:1] in (["-h"], ["--help"]):
        print(__doc__); return 0
    if "--" not in a or not a[a.index("--") + 1:]:
        print(__doc__); return 2
    cmd = a[a.index("--") + 1:]
    acquire(" ".join(cmd))
    try:
        return subprocess.run(cmd).returncode
    except FileNotFoundError:
        print(f"[gpu_lock] program not found: {cmd[0]}"); return 127
    finally:
        release()


if __name__ == "__main__":
    sys.exit(main())
