#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Write .srt and .vtt subtitles from timeline.json (exact times of every narration line). Udemy accepts .vtt only.
Subtitles are separate files on purpose: slides are full of text, burned-in captions would cover it, and learners can
switch separate captions on and off.

Usage:  python make_subtitles.py <timeline.json> <out-without-extension>
        e.g. make_subtitles.py videos/c/L01/L01.timeline.json videos/c/L01/L01.en  -> L01.en.srt and L01.en.vtt
Each narration line becomes cues of at most 2 lines x 42 characters, timed by character count. The text comes from the
timeline (the script as written, before any pronunciation respelling), so captions are spelled correctly even when the
voice was given a phonetic spelling.
"""
import json
import math
import re
import sys
from pathlib import Path

MAXL = 42
TAGS = re.compile(r"\s*\[(?:laugh|chuckle|sigh|clear throat|cười|thở dài|hắng giọng)\]", re.I)


def tc(t, sep=","):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def split(text, maxc=MAXL * 2):
    words = text.split()
    n = max(1, math.ceil(len(text) / maxc))
    if n == 1:
        return [text]
    target = len(text) / n
    out, cur = [], ""
    for w in words:
        nxt = (cur + " " + w).strip()
        if cur and (len(nxt) > maxc or (len(cur) >= target and len(out) < n - 1)):
            out.append(cur); cur = w
        else:
            cur = nxt
    if cur:
        out.append(cur)
    return out


def two_lines(text):
    if len(text) <= MAXL:
        return text
    mid = len(text) // 2
    best = min((i for i, c in enumerate(text) if c == " "), key=lambda i: abs(i - mid), default=None)
    return text if best is None else text[:best] + "\n" + text[best + 1:]


def main():
    tl = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = sys.argv[2]
    cues, n = [], 1
    for line in tl["lines"]:
        text = TAGS.sub("", line.get("text", "")).strip()
        if not text.strip(" .,?"):
            continue
        parts = split(text)
        total = sum(len(p) for p in parts) or 1
        t, span = line["start"], max(0.4, line["end"] - line["start"])
        for p in parts:
            d = span * len(p) / total
            cues.append((n, t, t + d - 0.04, two_lines(p)))
            t += d; n += 1
    Path(out + ".srt").write_text("\n".join(f"{i}\n{tc(a)} --> {tc(b)}\n{x}\n" for i, a, b, x in cues), encoding="utf-8")
    Path(out + ".vtt").write_text("WEBVTT\n\n" + "\n".join(f"{i}\n{tc(a, '.')} --> {tc(b, '.')}\n{x}\n" for i, a, b, x in cues), encoding="utf-8")
    print(f"{len(cues)} cues -> {out}.srt / .vtt")


if __name__ == "__main__":
    main()
