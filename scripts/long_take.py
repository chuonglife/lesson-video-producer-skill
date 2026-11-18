#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
LONG TAKE: the mode for long how-to lessons that are mostly screen recording (for example Claude Code doing a real
job for 10-20 minutes). Workflow: RECORD FIRST, WRITE THE NARRATION AFTER. Record in one go -> analyse into an action
table -> write the narration for each segment -> render: waits are cut or fast-forwarded, text areas are zoomed,
clicks and keys are highlighted, each piece of narration lands on its own piece of picture.

Usage:
  python long_take.py analyse <clip.mp4> [--threshold 0.004] [--min-wait 4] [--allow-blips 1]
                                         [--mode fast|cut] [--language en|vi] [--overwrite]
      -> <clip>.longtake.json   the config (a draft: segments, waits, zoom suggestions; the writer fills "narration")
         <clip>.action-table.md + .action-table-NN.png   the action table: times, events, waits, key frames
  python long_take.py render <clip.mp4> <out.mp4> [--config <longtake.json>] [--group-seconds 12.5,30,8] [--stage-label "Step 2"]
      a test render of the edited clip (without --group-seconds each group gets its preferred length) + <out>.metrics.json
  python long_take.py first-frame <clip.mp4> [--config <longtake.json>]
      writes and prints the path of the FIRST FRAME of the edited clip (letterboxed 1920x1080, masks applied)
  python long_take.py fit <storyboard.json> <timeline.json> <video.json>
      called by make_video.py after the voice step: a group whose picture cannot shrink to its narration gets
      "pause_after" added to the config; exit code 3 means "changed, run the voice again"

In video.json (the slide should be an "image" slide whose picture is the clip's first frame):
  "S03": {"clip": {"file": "clips/S03-claude.mp4", "mode": "full", "long_take": true}}
  long_take: true = <clip>.longtake.json next to the clip, or a path to the config. A long-take slide takes its
  NARRATION from "segments"[].narration of the config (instead of the slide's narration); storyboard.py stores the
  line range of each group in the storyboard.

The config <clip>.longtake.json (seconds are seconds of the ORIGINAL clip, read them from the action table):
  "waits":  [{"from": 20.4, "to": 81.2, "mode": "fast"}]        "fast" (fast-forward, "8x speed" label) | "cut" ("4 min later")
  "wait_defaults": {"mode": "fast", "speed": 8, "max_speed": 16, "min_speed": 2, "keep_head": 1, "keep_tail": 1, "cut_seconds": 2.4}
  "segments": [{"from": 0, "to": 20.4, "narration": "First line.\\nSecond line.", "pause_after": 0}]
          a segment with narration opens a GROUP; a segment without narration joins the group before it. The narration
          starts exactly when the picture of its group starts. "reading": true marks a result-review segment (never a wait).
  "zoom": [{"from": 3, "to": 18, "box": [x, y, w, h], "ease": 0.8}]   pixels of the original clip, widened to 16:9;
          in, out and the pan between two neighbouring boxes follow a slow-fast-slow curve over "ease" seconds of output
  "masks": [{"from": 0, "to": 12, "box": [x, y, w, h], "kind": "solid" | "blur" | "bg"}]   privacy masks (record_actions.py writes them);
          "bg" paints the terminal background colour with no border (for an obstacle such as an OS dialog)
  "callouts": [{"from": 40, "to": 45, "box": [x, y, w, h]}]   an accent frame drawn around a region (original clip pixels, seconds of the
          original clip). Not written: every reading segment gets an automatic frame around the text that appeared in the 6 s before it
          (too big or too small regions are skipped); "auto_callouts": false switches the automatic ones off
  "highlight": {"clicks": true, "keys": true, "hide_typing": true}   hide_typing: never show typed text, only key combos
  "inserts": [{"after": 72.6, "file": "D:/demo-course/program.docx", "pages": [1, 2], "narration": "..."}]
          the REAL ARTIFACT shown right after a result: a document, text file, deck, image or video built from the file
          itself (no extra recording), with an "Opening: <file>" label; see insert_artifacts.py for every field
Fitting narration and picture, group by group: narration longer than the picture -> the fast-forward slows down (never
below min_speed) and then the last frame holds; narration shorter -> waits shrink (fast-forward up to max_speed, a cut down
to 2 s), then action pieces speed up by at most 1.25x; still too long -> "fit" adds pause_after so the picture can run.
A piece with on-screen actions is NEVER faster than 1.25x.
No flicker (a scene = the picture between two changes of picture): a cut is never under 2 s, the core of a wait under 3 s is played
normally (no fast-forward, no cut), a fast-forward is never under 1.5 s, and an action fragment under 1.5 s squeezed between a
cut / fast-forward / insert / the clip edge is merged into its neighbour. The label "N min later" becomes "N hours later" from 90 minutes.
render(..., stage_label="Step 2") shows a pill at the top for the first 3.8 s of the clip.
"""
import argparse
import bisect
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
HERE = Path(__file__).resolve().parent

WAIT_DEFAULTS = {"mode": "fast", "speed": 8, "max_speed": 16, "min_speed": 2, "keep_head": 1.0, "keep_tail": 1.0, "cut_seconds": 2.4}
DETECT_DEFAULTS = {"threshold": 0.004, "min_wait": 4.0, "allow_blips": 1.0}
HIGHLIGHT_DEFAULTS = {"clicks": True, "keys": True, "hide_typing": True}
ACTION_FASTEST = 0.8          # output length / source length of an action piece: 0.8 = 1.25x faster (the old rule)
# SHORT SCENES (a cut shrunk to 0.8 s made its label flash and vanish): a cut is never under CUT_MIN, a wait core under
# WAIT_CORE_MIN is not fast-forwarded or cut, a fast-forward is never under FAST_MIN, an action fragment under CRUMB seconds that is
# squeezed between a cut / fast-forward / insert / the clip edge is merged into its neighbour (no 1 s flash of a screen).
CUT_MIN, CUT_MAX = 2.0, 3.0
WAIT_CORE_MIN = 3.0
FAST_MIN = 1.5
CRUMB = 1.5
SCENE_MIN = 1.5               # machine check: a scene (between two changes of picture) shorter than this is a defect
GROUP_LEAD = 0.4              # the picture of a narration group changes this many seconds before its voice starts (seconds)
ZOOM_MAX = 3.0
OUT_W, OUT_H, FPS = 1920, 1080, 30
LABELS = {"en": {"hour": "{n} hours later", "min": "{n} min later", "sec": "{n} sec later", "fast": "{x}× speed  »"},
          "vi": {"hour": "{n} giờ sau", "min": "{n} phút sau", "sec": "{n} giây sau", "fast": "Tua {x}×  »"}}
ACCENT = (252, 163, 17)       # the accent of the dark-blue theme (RGB)
LABEL_BG = (20, 33, 61)
FONTS = ["C:/Windows/Fonts/seguisb.ttf", "C:/Windows/Fonts/segoeui.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "DejaVuSans.ttf"]


# ---------------------------------------------------------------- helpers
def probe(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,r_frame_rate:format=duration",
                        "-of", "json", str(p)], capture_output=True, text=True, check=True)
    j = json.loads(r.stdout); s = j["streams"][0]
    n, d = s["r_frame_rate"].split("/")
    return int(s["width"]), int(s["height"]), float(n) / float(d), float(j["format"]["duration"])


def read_events(p):
    if not p or not Path(p).is_file():
        return {}, []
    head, ev = {}, []
    for line in Path(p).read_text(encoding="utf-8").splitlines():
        if line.strip():
            e = json.loads(line)
            (head.update(e) if e.get("kind") == "head" else ev.append(e))
    return head, sorted(ev, key=lambda e: e["t"])


def config_path(clip, value=True):
    clip = Path(clip)
    if value is True or value in ("", None):
        return clip.with_name(clip.stem + ".longtake.json")
    p = Path(value)
    return p if p.is_absolute() else clip.parent / p


def read_config(p):
    cfg = json.loads(Path(p).read_text(encoding="utf-8"))
    cfg["wait_defaults"] = {**WAIT_DEFAULTS, **(cfg.get("wait_defaults") or {})}
    cfg["highlight"] = {**HIGHLIGHT_DEFAULTS, **(cfg.get("highlight") or {})}
    cfg.setdefault("waits", []); cfg.setdefault("zoom", []); cfg.setdefault("masks", [])
    cfg["segments"] = sorted(cfg.get("segments") or [], key=lambda d: d["from"])
    cfg["_dir"] = str(Path(p).resolve().parent)
    sys.path.insert(0, str(HERE))
    import insert_artifacts
    insert_artifacts.expand(cfg)     # inserts of the real artifacts (if any) become segments of their own
    return cfg


def cut_label(sec, lang):
    b = LABELS.get(lang, LABELS["en"])
    if sec >= 5400:      # from 90 minutes: "3.5 hours later" (rounded to half an hour)
        return b["hour"].format(n="%g" % (round(sec / 1800) / 2))
    return b["min"].format(n=max(1, round(sec / 60))) if sec >= 90 else b["sec"].format(n=max(5, int(round(sec / 5)) * 5))


def ease(u):
    """smootherstep: slow - fast - slow, first and second derivatives are 0 at both ends (no jolt in or out)."""
    u = min(1.0, max(0.0, u))
    return u * u * u * (u * (u * 6 - 15) + 10)


# ---------------------------------------------------------------- narration groups
def narration_groups(cfg):
    """Group = a segment with narration + the narration-less segments after it. [{"segments": [i...], "lines": [...], "pause": s}]."""
    gs = []
    for i, d in enumerate(cfg["segments"]):
        lines = [l.strip() for l in (d.get("narration") or "").splitlines() if l.strip()]
        if lines or not gs:
            gs.append({"segments": [i], "lines": lines, "pause": float(d.get("pause_after") or 0)})
        else:
            gs[-1]["segments"].append(i); gs[-1]["pause"] += float(d.get("pause_after") or 0)
    if gs and not gs[0]["lines"] and len(gs) > 1:
        gs[1]["segments"] = gs[0]["segments"] + gs[1]["segments"]; gs[1]["pause"] += gs[0]["pause"]; gs.pop(0)
    return gs


# ---------------------------------------------------------------- pieces and fitting
def pieces_of_segment(cfg, d):
    """Split a segment into 'act' pieces (actions, normal speed) and 'wait' pieces (the core of a wait, after keep_head/keep_tail)."""
    wd = cfg["wait_defaults"]
    a, b = d["from"], d["to"]
    out, cur = [], a
    if d.get("insert") is not None:     # an insert of the real artifact: the source frame stands still, the picture is the file
        import insert_artifacts
        r = insert_artifacts.prepare(d["insert"], cfg["_dir"], cfg.get("language") or "en")
        return [{"kind": "insert", "s0": a, "s1": a, "r": r, "item": d["insert"]}]
    if d.get("reading"):      # a reading segment: actions only (the 1.25x rule), any wait written over it is ignored
        return [{"kind": "act", "s0": a, "s1": b}]
    for w in sorted(cfg["waits"], key=lambda w: w["from"]):
        wa, wb = max(w["from"], a), min(w["to"], b)
        if wb - wa <= 0:
            continue
        c0 = wa + (float(wd["keep_head"]) if w["from"] >= a - 1e-6 else 0)
        c1 = wb - (float(wd["keep_tail"]) if w["to"] <= b + 1e-6 else 0)
        if c1 - c0 < WAIT_CORE_MIN:      # too short to fast-forward or cut: it plays at normal speed inside the action piece
            continue
        if c0 > cur:
            out.append({"kind": "act", "s0": cur, "s1": c0})
        out.append({"kind": "wait", "s0": c0, "s1": c1, "mode": w.get("mode") or wd["mode"]})
        cur = c1
    if b > cur + 1e-6:
        out.append({"kind": "act", "s0": cur, "s1": b})
    return out


def fit_group(pieces, D, wd):
    """Give every piece an output length so the group lasts D seconds. Returns (pieces with 'out', held seconds, missing seconds)."""
    sp, smax, smin = float(wd["speed"]), float(wd["max_speed"]), float(wd["min_speed"])
    for m in pieces:
        L = m["s1"] - m["s0"]
        if m["kind"] == "act":
            m["pref"], m["lo"], m["hi"] = L, L * ACTION_FASTEST, L
        elif m["kind"] == "insert":     # shrinks to 70% (never under 2 s); a video insert never shrinks
            g = m["r"].seconds
            m["pref"], m["lo"], m["hi"] = g, (g if m["r"].fixed else max(min(2.0, g), g * 0.7)), g
        elif m["mode"] == "cut":
            pref = max(CUT_MIN, float(wd["cut_seconds"]))      # an old config with cut_seconds 1.6 still gives >= 2 s
            m["pref"], m["lo"], m["hi"] = pref, CUT_MIN, max(CUT_MAX, pref)
        else:
            lo = max(L / smax, min(FAST_MIN, L / smin))
            m["pref"], m["lo"], m["hi"] = max(L / sp, lo), lo, L / smin
        m["out"] = m["pref"]
    P = sum(m["pref"] for m in pieces)
    hold, short = 0.0, 0.0
    if D is None:
        return pieces, 0.0, 0.0
    waits = [m for m in pieces if m["kind"] == "wait"]
    if D >= P:
        extra = D - P
        room = sum(m["hi"] - m["pref"] for m in waits)
        used = min(extra, room)
        for m in waits:
            if room > 0:
                m["out"] += (m["hi"] - m["pref"]) * used / room
        hold = extra - used
    else:
        need = P - D
        for pool in (waits, [m for m in pieces if m["kind"] == "act"], [m for m in pieces if m["kind"] == "insert"]):
            room = sum(m["out"] - m["lo"] for m in pool)
            used = min(need, room)
            for m in pool:
                if room > 0:
                    m["out"] -= (m["out"] - m["lo"]) * used / room
            need -= used
        short = max(0.0, need)
    return pieces, hold, short


def merge_crumbs(grouped):
    """Action crumbs: a run of 'act' pieces shorter than CRUMB seconds in all, whose two ends are both a change of picture (cut,
    fast-forward, insert, clip edge) -> drop the crumb and add its output length (and source seconds) to the neighbouring wait or insert
    of the same group. The length of the group stays the same. grouped: [(k, D, pieces, hold, short)], changed in place."""
    flat = [(k, m) for k, D, pieces, hold, short in grouped for m in pieces]
    hard = lambda m: m is None or m["kind"] in ("wait", "insert")
    drop = set()
    i = 0
    while i < len(flat):
        if flat[i][1]["kind"] != "act":
            i += 1; continue
        j = i
        while j + 1 < len(flat) and flat[j + 1][1]["kind"] == "act" and flat[j + 1][0] == flat[i][0]:
            j += 1
        run = [flat[x][1] for x in range(i, j + 1)]
        out = sum(m["out"] for m in run)
        before = flat[i - 1] if i > 0 else None
        after = flat[j + 1] if j + 1 < len(flat) else None
        soft_before = before is not None and before[1]["kind"] == "act"    # an act of another group next to it is a seamless join
        soft_after = after is not None and after[1]["kind"] == "act"
        k = flat[i][0]
        near = [x for x in (after, before) if x is not None and x[0] == k and x[1]["kind"] in ("wait", "insert")]
        if out < CRUMB and not soft_before and not soft_after and hard(before and before[1]) and hard(after and after[1]) and near:
            target = (sorted(near, key=lambda x: x[1]["kind"] != "wait")[0])[1]
            if target["kind"] == "wait":
                if target is (after and after[1]):
                    target["s0"] = run[0]["s0"]
                else:
                    target["s1"] = run[-1]["s1"]
            target["out"] += out
            drop |= {id(m) for m in run}
        i = j + 1
    for x in range(len(grouped)):
        k, D, pieces, hold, short = grouped[x]
        grouped[x] = (k, D, [m for m in pieces if id(m) not in drop], hold, short)


def scenes(plan):
    """The scenes (between two changes of picture) in output seconds: normal action (act + hold side by side), cut, fast, insert."""
    sc = []
    for m in plan:
        k = "cut" if m.get("mode") == "cut" and m["kind"] == "wait" else "fast" if m["kind"] == "wait" else "insert" if m["kind"] == "insert" else "normal"
        if sc and sc[-1]["kind"] == k == "normal":
            sc[-1]["out_to"] = round(m["o1"], 2)
        else:
            sc.append({"kind": k, "out_from": round(m["o0"], 2), "out_to": round(m["o1"], 2)})
    return sc


def schedule(cfg, group_seconds=None):
    """The whole clip as ordered pieces with o0/o1 (output seconds). group_seconds: the wanted output length of each group."""
    gs = narration_groups(cfg)
    wd = cfg["wait_defaults"]
    plan, report, o = [], [], 0.0
    fitted = []
    for k, g in enumerate(gs):
        pieces = [m for i in g["segments"] for m in pieces_of_segment(cfg, cfg["segments"][i])]
        D = group_seconds[k] if group_seconds and k < len(group_seconds) else None
        fitted.append((k, D) + fit_group(pieces, D, wd))
    merge_crumbs(fitted)
    for k, D, pieces, hold, short in fitted:
        g = gs[k]
        o_group = o
        if hold > 1e-3 and any(m["kind"] == "insert" for m in pieces):   # a group with an insert stretches the insert (slower scroll)
            [m for m in pieces if m["kind"] == "insert"][-1]["out"] += hold   # instead of holding the source frame
            hold = 0.0
        for m in pieces:
            m["o0"], m["o1"] = o, o + m["out"]; o = m["o1"]; m["group"] = k; plan.append(m)
        if hold > 1e-3:
            s = pieces[-1]["s1"] if pieces else 0
            plan.append({"kind": "hold", "s0": s, "s1": s, "o0": o, "o1": o + hold, "out": hold, "group": k}); o += hold
        report.append({"group": k + 1, "segments": [i + 1 for i in g["segments"]], "D": None if D is None else round(D, 2),
                       "video": round(o - o_group, 2), "hold": round(hold, 2), "short": round(short, 2)})
    return plan, report


def source_to_out(plan, s):
    """Source second -> output second (None inside a cut)."""
    for m in plan:
        if m["kind"] in ("act", "wait") and m["s0"] - 1e-6 <= s <= m["s1"] + 1e-6 and m["s1"] > m["s0"]:
            if m["kind"] == "wait" and m["mode"] == "cut":
                return None
            return m["o0"] + (s - m["s0"]) / (m["s1"] - m["s0"]) * (m["o1"] - m["o0"])
    return None


# ---------------------------------------------------------------- analysis
def activity(clip, fps=10, w=240):
    W, H, _, _ = probe(clip)
    h = int(round(w * H / W / 2)) * 2
    p = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-i", str(clip), "-vf", f"fps={fps},scale={w}:{h},format=gray",
                         "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
    prev, frac, masks, i = None, [], [], 0
    while True:
        b = p.stdout.read(w * h)
        if len(b) < w * h:
            break
        f = np.frombuffer(b, np.uint8).reshape(h, w).astype(np.int16)
        if prev is not None:
            d = np.abs(f - prev) > 24
            frac.append(float(d.mean()))
            sec = int(i / fps)
            while len(masks) <= sec:
                masks.append(np.zeros((h, w), bool))
            masks[sec] |= d
        prev = f; i += 1
    return np.array(frac), masks, (w, h), (W, H)


def find_waits(frac, fps, ev, thr, min_s, blips, marks=(), reading=()):
    still = frac < thr
    hard = [False] * len(still)
    # reading segments (review_result in the action script): the viewer reads the result, NEVER a wait, never fast, never cut
    for a0, a1 in reading:
        for j in range(max(0, int((a0 - 0.3) * fps)), min(len(still), int((a1 + 0.3) * fps) + 1)):
            still[j] = False; hard[j] = True
    # marks of the action script ("result"...): the 3 s after a mark are for reading, never a wait
    for t in marks:
        for j in range(max(0, int((t - 0.5) * fps)), min(len(still), int((t + 3.0) * fps) + 1)):
            still[j] = False; hard[j] = True
    for e in ev:
        if e.get("kind") in ("key", "type", "click", "wheel"):
            for j in range(max(0, int((e["t"] - 0.5) * fps)), min(len(still), int((e["t"] + 1.5) * fps) + 1)):
                still[j] = False; hard[j] = True
    runs, j = [], 0
    while j < len(still):
        if still[j]:
            k = j
            while k < len(still) and still[k]:
                k += 1
            runs.append([j, k]); j = k
        else:
            j += 1
    merged = []
    for r in runs:
        if merged and (r[0] - merged[-1][1]) / fps <= blips and not any(hard[merged[-1][1]:r[0]]):
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    return [((a + 1) / fps, (b + 1) / fps) for a, b in merged if (b - a) / fps >= min_s]


def suggest_zoom(masks, a, b, small, size):
    import cv2
    w, h = small
    W, H = size
    secs = range(int(a), min(len(masks), int(math.ceil(b))))
    if not secs:
        return None
    m = np.zeros((h, w), np.uint8)
    for s in secs:
        m |= masks[s].astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    if m.sum() < 12:
        return None
    ys, xs = np.nonzero(m)
    x0, x1 = np.percentile(xs, 1) * W / w, (np.percentile(xs, 99) + 1) * W / w
    y0, y1 = np.percentile(ys, 1) * H / h, (np.percentile(ys, 99) + 1) * H / h
    return fit_169([x0 - 0.04 * W, y0 - 0.04 * H, x1 - x0 + 0.08 * W, y1 - y0 + 0.08 * H], W, H, min_w=W / 2.5, drop_if_wider=0.85)


def fit_169(box, W, H, min_w=None, drop_if_wider=None):
    """Widen a box to the clip's aspect ratio, no smaller than W/ZOOM_MAX, inside the picture."""
    x, y, w, h = box
    cx, cy = x + w / 2, y + h / 2
    w = max(w, h * W / H, min_w or W / ZOOM_MAX)
    w = min(w, W); h = w * H / W
    if drop_if_wider and w >= drop_if_wider * W:
        return None
    x = min(max(0, cx - w / 2), W - w); y = min(max(0, cy - h / 2), H - h)
    return [round(x), round(y), round(w), round(h)]


def describe_events(ev, a, b, hidden):
    inside = [e for e in ev if a <= e["t"] < b]
    typed = [e for e in inside if e.get("kind") == "type"]
    keys = [e["name"] for e in inside if e.get("kind") == "key"]
    clicks = sum(1 for e in inside if e.get("kind") == "click")
    wheel = sum(1 for e in inside if e.get("kind") == "wheel")
    p = []
    if typed:
        text = "".join(e.get("char", "") for e in typed)
        p.append(f"typed {len(typed)} keys" + (f" \"{text[:40]}\"" if text and not hidden else ""))
    if keys:
        p.append(", ".join(dict.fromkeys(keys)))
    if clicks:
        p.append(f"{clicks} click{'s' if clicks > 1 else ''}")
    if wheel:
        p.append(f"{wheel} wheel steps")
    return "; ".join(p)


def analyse(a):
    clip = Path(a.clip).resolve()
    cfg_p = config_path(clip)
    ev_p = clip.with_name(clip.stem + ".events.jsonl")
    head, ev = read_events(ev_p)
    hidden = bool(head.get("hide_typing", True)) if head else True
    tp = clip.with_name(clip.stem + ".take.json")       # record_actions.py: marks, reading segments, masks, zoom
    take = json.loads(tp.read_text(encoding="utf-8")) if tp.is_file() else {}
    fps = 10
    frac, masks, small, size = activity(clip, fps)
    W, H, _, length = probe(clip)
    reading = [tuple(x) for x in take.get("reading", [])]
    waits = find_waits(frac, fps, ev, a.threshold, a.min_wait, a.allow_blips, [m["t"] for m in take.get("marks", [])], reading)
    # segment edges: start and end of every wait, marks, reading segments; long action stretches are also split at Enter
    edges = {0.0, round(length, 2)}
    for w0, w1 in waits:
        edges |= {round(w0, 2), round(w1, 2)}
    for e in ev:
        if e.get("kind") == "key" and e.get("name") == "Enter":
            t = round(e["t"] + 0.3, 2)
            if all(abs(t - r) >= 5 for r in edges) and not any(w0 < t < w1 for w0, w1 in waits):
                edges.add(t)
    marks = {round(m["t"], 2): m["name"] for m in take.get("marks", []) if 0 < m["t"] < length}
    edges |= set(marks)
    for a0, a1 in reading:
        edges |= {round(a0, 2), round(min(a1, length), 2)}
    edges = sorted(r for r in edges if 0 <= r <= round(length, 2))   # round(): a last edge of 27.87 > 27.8667 once dropped the last segment
    segs = []
    for x0, x1 in zip(edges, edges[1:]):
        if x1 - x0 < 0.3:
            continue
        is_wait = any(abs(x0 - w0) < 0.05 and abs(x1 - w1) < 0.05 for w0, w1 in waits)
        what = describe_events(ev, x0, x1, hidden)
        if is_wait:
            what = f"wait {x1 - x0:.0f} s ({a.mode})" + (f"; {what}" if what else "")
        d = {"from": x0, "to": x1, "narration": "", "what": what or "the screen changes, no recorded input"}
        if x0 in marks:
            d["mark"] = marks[x0]
        if any(a0 - 0.05 <= x0 and x1 <= a1 + 0.05 for a0, a1 in reading):
            d["reading"] = True
            d["what"] = "READING (result review: the narration explains the result; never fast, never cut)" + ("; " + what if what else "")
        segs.append(d)
    sug = []
    for d in segs:
        z = suggest_zoom(masks, d["from"], d["to"], small, size)
        if z:
            sug.append({"from": d["from"], "to": d["to"], "box": z, "ease": 0.8})
    cfg = {"_how_to": "Write the narration into segments[].narration (one spoken beat per line). Edit or delete waits in 'waits'. Copy the zoom boxes you want from zoom_suggestions to zoom. See long_take.py.",
           "source": clip.name, "events": ev_p.name if ev_p.is_file() else None, "language": a.language,
           "detect": {"threshold": a.threshold, "min_wait": a.min_wait, "allow_blips": a.allow_blips},
           "wait_defaults": {**WAIT_DEFAULTS, "mode": a.mode},
           "waits": [{"from": round(w0, 2), "to": round(w1, 2), "mode": a.mode} for w0, w1 in waits],
           "segments": segs, "zoom": list(take.get("zoom", [])), "zoom_suggestions": sug, "highlight": dict(HIGHLIGHT_DEFAULTS),
           "masks": list(take.get("masks", []))}
    if cfg_p.is_file() and not a.overwrite:
        old = json.loads(cfg_p.read_text(encoding="utf-8"))
        old["zoom_suggestions"] = sug
        if take.get("masks"):
            old["masks"] = cfg["masks"]     # masks always come from the latest take
        cfg_p.write_text(json.dumps(old, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{cfg_p.name} exists: narration, segments and waits kept; only zoom_suggestions refreshed (--overwrite to start again)")
    else:
        cfg_p.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
        print("wrote", cfg_p)
    action_table(clip, read_config(cfg_p), ev, hidden, (W, H, length), scripted=bool(take))


def check_ime(ev, scripted=False):
    """After recording: typed characters with Vietnamese diacritics (an input method such as UniKey/EVKey in Telex/VNI was on)
    or characters sent as VK_PACKET (an input method, or a typing tool)."""
    import unicodedata
    accented = [e for e in ev if e.get("kind") == "type" and any(c in "đĐ" or any(unicodedata.combining(x) for x in unicodedata.normalize("NFD", c))
                                                                   for c in e.get("char", ""))]
    packets = [e for e in ev if e.get("packet")]
    out = []
    if accented:
        out.append(f"INPUT METHOD WARNING: {len(accented)} accented characters in the key log (from second {accented[0]['t']:.1f}): was a Vietnamese "
                   f"input method on while recording? Look at the typed line in the picture; if it is wrong, switch the input method to E/English and record again.")
    elif packets and not scripted:   # record_actions.py types with VK_PACKET on purpose: no warning
        out.append(f"Input method note: {len(packets)} characters arrived as Unicode packets (VK_PACKET, from second {packets[0]['t']:.1f}): "
                   f"an input method or a typing tool sent them. Check the typed text in the picture.")
    return out


def action_table(clip, cfg, ev, hidden, info, scripted=False):
    from PIL import Image, ImageDraw
    W, H, length = info
    thumbs = clip.with_name(clip.stem + ".action-table"); thumbs.mkdir(exist_ok=True)
    reading_n = len([d for d in cfg["segments"] if d.get("reading")])
    md = [f"# Action table: {clip.name}", "",
          f"Clip {length:.1f} s, {W}x{H}. Action log: {'yes' if ev else 'NO (waits are guessed from the picture only, check them)'}"
          f"{', typed text hidden' if ev and hidden else ''}. Waits: {len(cfg['waits'])}, {sum(w['to'] - w['from'] for w in cfg['waits']):.0f} s in all.",
          *[f"**{x}**" for x in check_ime(ev, scripted)],
          *([f"Reading segments (result review): {reading_n}; write narration that EXPLAINS the result for them."] if reading_n else []),
          *([f"Masks: {len(cfg['masks'])} (emails, keys, paths with the user name, boxes from the action script); check the last frame of each segment."]
            if cfg["masks"] else []),
          "", "Write the narration for each segment into `segments[].narration` of " + config_path(clip).name
          + " (one spoken beat per line; a segment left empty joins the one before).",
          "Say what is on screen; a wait is the place to explain why. Pictures: start / middle / end of the segment, orange box = suggested zoom.", "",
          "| # | Source seconds | Length | Actions, waits | Suggested zoom [x, y, w, h] | Pictures |", "|---|---|---|---|---|---|"]
    sug = {(round(z["from"], 2), round(z["to"], 2)): z["box"] for z in cfg.get("zoom_suggestions") or []}
    rows = []
    for k, d in enumerate(cfg["segments"], 1):
        a, b = d["from"], d["to"]
        pics = []
        for tag, t in (("start", a + 0.3), ("mid", (a + b) / 2), ("end", max(a, b - 0.3))):
            f = thumbs / f"seg-{k:02d}-{tag}.jpg"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{min(t, length - 0.05):.2f}", "-i", str(clip), "-frames:v", "1",
                            "-vf", "scale=480:-2", "-q:v", "4", str(f)])
            pics.append(f)
        z = sug.get((round(a, 2), round(b, 2)))
        md.append(f"| {k} | {a:.1f} - {b:.1f} | {b - a:.1f} s | {('[' + d['mark'] + '] ') if d.get('mark') else ''}{d.get('what', '')} | {z or '-'} | {thumbs.name}/seg-{k:02d}-*.jpg |")
        rows.append((k, a, b, d.get("what", ""), pics, z))
    md += ["", "Waits found (source seconds; change mode in the config: fast | cut; delete any that is not a wait):"]
    md += [f"- {w['from']:.1f} - {w['to']:.1f} ({w['to'] - w['from']:.0f} s, {w.get('mode')})" for w in cfg["waits"]] or ["- none"]
    clip.with_name(clip.stem + ".action-table.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    tw, th = 480, int(480 * H / W)
    for t in range(0, len(rows), 6):
        chunk = rows[t:t + 6]
        sheet = Image.new("RGB", (360 + 3 * (tw + 6), len(chunk) * (th + 8)), (17, 17, 17))
        dr = ImageDraw.Draw(sheet)
        f18, f15 = font(18), font(15)
        for r, (k, a, b, what, pics, z) in enumerate(chunk):
            y = r * (th + 8)
            dr.text((10, y + 10), f"Segment {k}: {a:.1f} - {b:.1f} s", fill=ACCENT, font=f18)
            for li, part in enumerate([what[i:i + 40] for i in range(0, len(what), 40)][:8]):
                dr.text((10, y + 38 + li * 20), part, fill=(230, 230, 230), font=f15)
            for c, f in enumerate(pics):
                if f.is_file():
                    im = Image.open(f).convert("RGB").resize((tw, th))
                    if z and c == 2:
                        d2 = ImageDraw.Draw(im); s = tw / W
                        d2.rectangle([z[0] * s, z[1] * s, (z[0] + z[2]) * s, (z[1] + z[3]) * s], outline=ACCENT, width=3)
                    sheet.paste(im, (360 + c * (tw + 6), y))
        sheet.save(clip.with_name(f"{clip.stem}.action-table-{t // 6 + 1:02d}.png"))
    for x in check_ime(ev, scripted):
        print(x)
    print(f"action table: {clip.with_name(clip.stem + '.action-table.md')} ({len(rows)} segments, {len(cfg['waits'])} waits) + sheets {clip.stem}.action-table-NN.png")


# ---------------------------------------------------------------- rendering
class Reader:
    """Read frames in increasing time order (skips quickly with grab)."""

    def __init__(self, path):
        import cv2
        self.cap = cv2.VideoCapture(str(path))
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30
        self.n = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
        self.cur, self.f = -1, None

    def at(self, s):
        idx = max(0, min(self.n - 1, int(round(s * self.fps))))
        if idx <= self.cur and self.f is not None:
            return self.f
        while self.cur < idx - 1:
            if not self.cap.grab():
                return self.f
            self.cur += 1
        ok, f = self.cap.read()
        if ok:
            self.cur += 1; self.f = f
        return self.f


def font(sz):
    from PIL import ImageFont
    for f in FONTS:
        try:
            return ImageFont.truetype(f, sz)
        except OSError:
            continue
    return ImageFont.load_default()


_LABEL_CACHE = {}


def label_image(text, sz=40, bg=LABEL_BG, fg=(255, 255, 255), edge=ACCENT):
    from PIL import Image, ImageDraw
    key = (text, sz, bg, fg)
    if key not in _LABEL_CACHE:
        f = font(sz)
        x0, y0, x1, y1 = f.getbbox(text)
        pw, ph = int(sz * 0.7), int(sz * 0.38)
        w, h = x1 - x0 + 2 * pw, int(sz * 1.25) + 2 * ph
        im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([1, 1, w - 2, h - 2], radius=h // 2, fill=bg + (232,), outline=edge + (255,), width=3)
        d.text((pw - x0, (h - (y1 - y0)) / 2 - y0), text, font=f, fill=fg + (255,))
        a = np.asarray(im).astype(np.float32)
        _LABEL_CACHE[key] = (a[..., [2, 1, 0]], a[..., 3:4] / 255.0)
    return _LABEL_CACHE[key]


def paste(frame, label, x, y, alpha=1.0):
    rgb, a = label
    h, w = rgb.shape[:2]
    x, y = int(x), int(y)
    if alpha <= 0.01 or x >= frame.shape[1] or y >= frame.shape[0]:
        return
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(frame.shape[1], x + w), min(frame.shape[0], y + h)
    sub = frame[y0:y1, x0:x1].astype(np.float32)
    aa = a[y0 - y:y1 - y, x0 - x:x1 - x] * alpha
    frame[y0:y1, x0:x1] = (sub * (1 - aa) + rgb[y0 - y:y1 - y, x0 - x:x1 - x] * aa).astype(np.uint8)


def click_ripple(frame, x, y, u):
    """A ripple where the click happened: grows 14 -> 64 px in 0.6 s and fades; a dot in the first quarter."""
    import cv2
    r = int(14 + 50 * ease(u)); a = (1 - u) ** 1.3
    x0, y0 = int(x) - 80, int(y) - 80
    x1, y1 = x0 + 160, y0 + 160
    H, W = frame.shape[:2]
    if x1 <= 0 or y1 <= 0 or x0 >= W or y0 >= H:
        return
    cx0, cy0, cx1, cy1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
    roi = frame[cy0:cy1, cx0:cx1]
    layer = roi.copy()
    c = (int(x) - cx0, int(y) - cy0)
    col = ACCENT[::-1]
    cv2.circle(layer, c, r, col, 5, cv2.LINE_AA)
    if u < 0.4:
        cv2.circle(layer, c, 9, col, -1, cv2.LINE_AA)
    cv2.addWeighted(layer, a, roi, 1 - a, 0, dst=roi)


def apply_masks(f, masks, s):
    """Mask private areas on the ORIGINAL frame (before the zoom, so a mask follows the zoom): a solid box or a strong blur."""
    import cv2
    out = None
    H, W = f.shape[:2]
    for a, b, (x, y, w, h), kind in masks:
        if a <= s <= b:
            if out is None:
                out = f.copy()
            x0, y0, x1, y1 = max(0, int(x)), max(0, int(y)), min(W, int(x + w)), min(H, int(y + h))
            if x1 <= x0 or y1 <= y0:
                continue
            if kind == "bg":      # the terminal background colour, no border (an obstacle such as an OS dialog got into the frame)
                cv2.rectangle(out, (x0, y0), (x1 - 1, y1 - 1), (8, 8, 8), -1)
            elif kind == "blur":
                roi = out[y0:y1, x0:x1]
                small = cv2.resize(roi, (max(1, (x1 - x0) // 12), max(1, (y1 - y0) // 12)), interpolation=cv2.INTER_AREA)
                out[y0:y1, x0:x1] = cv2.GaussianBlur(cv2.resize(small, (x1 - x0, y1 - y0), interpolation=cv2.INTER_LINEAR), (0, 0), 6)
            else:
                cv2.rectangle(out, (x0, y0), (x1 - 1, y1 - 1), (61, 33, 20), -1)
                cv2.rectangle(out, (x0, y0), (x1 - 1, y1 - 1), ACCENT[::-1], 2)
    return f if out is None else out


def first_frame(clip, cfg_path):
    """The FIRST FRAME of the edited clip exactly as render() draws it (letterboxed 1920x1080, private areas masked) ->
    <clip folder>/_longtake/<clip>.first.png. The storyboard uses it as the picture of a slide that the full-screen clip covers, so
    the transition goes straight from the previous slide into the clip (no placeholder slide shows). Cached by hash; returns the path."""
    import cv2
    clip = Path(clip)
    out = clip.parent / "_longtake" / f"{clip.stem}.first.png"
    cfg = read_config(cfg_path)
    s0 = cfg["segments"][0]["from"] if cfg["segments"] else 0.0
    key = hashlib.md5(json.dumps([cfg.get("masks"), s0, clip.stat().st_size, clip.stat().st_mtime_ns], sort_keys=True).encode()).hexdigest()[:10]
    stamp = out.with_suffix(".txt")
    if out.is_file() and stamp.is_file() and stamp.read_text(encoding="utf-8") == key:
        return out
    W, H, _, _ = probe(clip)
    f = Reader(clip).at(s0)
    masks = [(c["from"], c["to"], c["box"], c.get("kind", "solid")) for c in cfg["masks"]]
    f = apply_masks(f, masks, s0)
    k0 = min(OUT_W / W, OUT_H / H); ox, oy = (OUT_W - W * k0) / 2, (OUT_H - H * k0) / 2
    img = cv2.warpAffine(f, np.float32([[k0, 0, ox], [0, k0, oy]]), (OUT_W, OUT_H), borderValue=(0, 0, 0))
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), img)
    stamp.write_text(key, encoding="utf-8")
    return out


def callouts_of_clip(clip, cfg, W, H):
    """Accent frames in the long take, in ORIGINAL seconds: [(s_from, s_to, [x, y, w, h])].
    "callouts": [{"from", "to", "box"}] in the config is used as written. Not written (and "auto_callouts" not false): every READING
    segment gets a frame around the text that appeared in the 6 s before it (the result Claude Code just printed); a region that is too
    big (the whole screen scrolled) or too small is skipped."""
    import cv2
    if cfg.get("callouts") is not None:
        return [(float(k["from"]), float(k["to"]), k["box"]) for k in cfg["callouts"]]
    if cfg.get("auto_callouts") is False:
        return []
    out = []
    rd = None
    for d in cfg["segments"]:
        if not d.get("reading") or d.get("insert") is not None:
            continue
        t = float(d["from"]) + 0.3
        if rd is None:
            rd = cv2.VideoCapture(str(clip))
        pics = []
        for s in (max(0.0, t - 6.0), t):
            rd.set(cv2.CAP_PROP_POS_MSEC, s * 1000)
            ok, f = rd.read()
            if not ok:
                break
            pics.append(cv2.cvtColor(cv2.resize(f, (480, int(480 * H / W))), cv2.COLOR_BGR2GRAY).astype(np.int16))
        if len(pics) < 2:
            continue
        m = (np.abs(pics[1] - pics[0]) > 28).astype(np.uint8)
        h_ = m.shape[0]
        m[int(h_ * 0.86):] = 0          # the bottom strip: the prompt box and the status line, always changing
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        if m.sum() < 40:
            continue
        ys, xs = np.nonzero(m)
        sx = W / 480
        x0, x1 = np.percentile(xs, 2) * sx, (np.percentile(xs, 98) + 1) * sx
        y0, y1 = np.percentile(ys, 2) * sx, (np.percentile(ys, 98) + 1) * sx
        # follow the real LINES of text in the last frame: grow up and down to a blank line, left and right to the text edge (never cut a line)
        rd.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, f = rd.read()
        if not ok:
            continue
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.int16)
        ink = np.abs(g - int(np.median(g))) > 60
        rows = ink.any(1)
        y0, y1 = int(y0), min(int(y1), int(H * 0.86) - 1)
        blank = lambda y: not rows[max(0, y - 5):y + 6].any()
        while y0 > 0 and not blank(y0):
            y0 -= 1
        while y1 < int(H * 0.86) - 1 and not blank(y1):
            y1 += 1
        cols = np.nonzero(ink[y0:y1 + 1].any(0))[0]
        if len(cols) < 2:
            continue
        x0, x1 = float(cols[0]), float(cols[-1] + 1)
        share = (x1 - x0) * (y1 - y0) / (W * H)
        if share > 0.45 or share < 0.01:
            continue
        out.append((t + 0.3, min(float(d["to"]), t + 5.0), [round(x0 - 14), round(y0 - 10), round(x1 - x0 + 28), round(y1 - y0 + 20)]))
    return out


def draw_callout(frame, x, y, w, h, u, alpha=1.0):
    """A rounded frame drawn along its outline (u 0..1), accent colour, 6 px thick."""
    import cv2
    r = int(min(28, h / 2, w / 2))
    pts = []
    for (cx, cy, a0) in ((x + w - r, y + r, -90), (x + w - r, y + h - r, 0), (x + r, y + h - r, 90), (x + r, y + r, 180)):
        for a in range(a0, a0 + 91, 10):
            pts.append((cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a))))
    pts.append(pts[0])
    n = max(2, int(len(pts) * ease(u)))
    layer = frame.copy()
    cv2.polylines(layer, [np.int32(pts[:n])], False, ACCENT[::-1], 6, cv2.LINE_AA)
    cv2.addWeighted(layer, alpha, frame, 1 - alpha, 0, dst=frame)


def key_labels(ev, plan, hl):
    """(o0, o1, text) for the key label in the bottom right corner, in output seconds."""
    out, buf, last = [], "", None
    for e in ev:
        k = e.get("kind")
        if k not in ("key", "type"):
            continue
        o = source_to_out(plan, e["t"])
        if o is None:
            continue
        if k == "type":
            if hl["hide_typing"] or not e.get("char"):
                continue
            if last is None or o - last > 1.5:
                buf = ""
            buf += e["char"]; last = o
            if out and out[-1][3] == "type" and o - out[-1][1] < 1.5:
                out[-1] = (out[-1][0], o + 1.5, buf[-28:], "type")
            else:
                out.append((o, o + 1.5, buf[-28:], "type"))
        else:
            buf, last = "", None
            out.append((o, o + 1.4, e["name"].replace("+", " + "), "key"))
    for i in range(len(out) - 1):            # a newer label cuts the older one short
        if out[i][1] > out[i + 1][0]:
            out[i] = (out[i][0], out[i + 1][0], out[i][2], out[i][3])
    return [(a, b, t) for a, b, t, _ in out if b - a > 0.05]


def render(clip, cfg_p, out_path, group_seconds=None, stage_label=None):
    import cv2
    clip, out_path = Path(clip), Path(out_path)
    cfg = read_config(cfg_p)
    lang = cfg.get("language") or "en"
    W, H, _, length = probe(clip)
    plan, report = schedule(cfg, group_seconds)
    if not plan:
        raise SystemExit(f"{cfg_p}: no segments yet")
    n_frames = int(round(plan[-1]["o1"] * FPS))
    ends = [m["o1"] for m in plan]
    _, ev = read_events(clip.parent / cfg["events"]) if cfg.get("events") else ({}, [])
    hl = cfg["highlight"]
    k0 = min(OUT_W / W, OUT_H / H); ox, oy = (OUT_W - W * k0) / 2, (OUT_H - H * k0) / 2   # source -> 1920x1080, letterboxed
    full = (0.0, 0.0, float(OUT_W))
    zooms = []
    for z in cfg["zoom"]:
        b = fit_169(z["box"], W, H)
        zooms.append((z["from"], z["to"], (b[0] * k0 + ox, b[1] * k0 + oy, b[2] * k0), float(z.get("ease", 0.8))))

    def target(s):
        for a, b, r, e in zooms:
            if a <= s < b:
                return r, e
        return full, (zooms[0][3] if zooms else 0.8)

    masks = [(c["from"], c["to"], c["box"], c.get("kind", "solid")) for c in cfg["masks"]]
    clicks = []
    if hl["clicks"]:
        for e in ev:
            if e.get("kind") == "click" and "x" in e:
                o = source_to_out(plan, e["t"])
                if o is not None:
                    clicks.append((o, e["x"] * k0 + ox, e["y"] * k0 + oy))
    keys = key_labels(ev, plan, hl) if hl["keys"] else []
    callouts = []
    for a_, b_, (x_, y_, w_, h_) in callouts_of_clip(clip, cfg, W, H):
        oa, ob = source_to_out(plan, a_), source_to_out(plan, b_)
        if oa is None:
            continue
        if ob is None or ob < oa + 2.2:
            ob = oa + 3.0
        callouts.append((oa, ob, x_ * k0 + ox, y_ * k0 + oy, w_ * k0, h_ * k0))
    wait_labels = []
    for m in plan:
        if m["kind"] == "wait":
            if m["mode"] == "cut":
                wait_labels.append((m["o0"], m["o1"] + 0.8, cut_label(m["s1"] - m["s0"], lang), "mid"))
            else:
                x = (m["s1"] - m["s0"]) / max(1e-3, m["o1"] - m["o0"])
                wait_labels.append((m["o0"], m["o1"], LABELS.get(lang, LABELS["en"])["fast"].format(x=f"{x:.0f}" if x >= 3 else f"{x:.1f}"), "right"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(out_path.stem + ".tmp.mp4")
    enc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{OUT_W}x{OUT_H}",
                            "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
                            "-movflags", "+faststart", str(tmp)], stdin=subprocess.PIPE)
    rd = Reader(clip)
    from_r, to_r, t_start, ease_s = full, full, -1e9, 0.8
    step_max, jerk_max, zoom_max, frame_a = 0.0, 0.0, 1.0, None
    prev_r, prev_v = full, (0.0, 0.0, 0.0)
    for n in range(n_frames):
        t = n / FPS
        m = plan[min(len(plan) - 1, bisect.bisect_right(ends, t))]
        u = 0.0 if m["o1"] <= m["o0"] else (t - m["o0"]) / (m["o1"] - m["o0"])
        if m["kind"] == "wait" and m["mode"] == "cut":
            if u < 0.35:
                f = rd.at(m["s0"]); frame_a = f.copy(); s_now = m["s0"]
            else:
                fb = rd.at(m["s1"]); s_now = m["s1"]
                al = ease((u - 0.35) / 0.3)
                f = fb if al >= 1 or frame_a is None else cv2.addWeighted(frame_a, 1 - al, fb, al, 0)
        else:
            s_now = m["s0"] + u * (m["s1"] - m["s0"]) if m["kind"] != "hold" else m["s0"]
            f = rd.at(s_now)
        if masks:
            f = apply_masks(f, masks, s_now)
        # zoom: the target follows source seconds, the motion follows output seconds (smooth even inside a 16x fast-forward)
        tr, te = target(s_now)
        if tr != to_r:
            p = min(1.0, (t - t_start) / ease_s) if ease_s > 0 else 1.0
            from_r = tuple(a + (b - a) * ease(p) for a, b in zip(from_r, to_r))
            to_r, t_start, ease_s = tr, t, te
        p = min(1.0, (t - t_start) / ease_s) if ease_s > 0 else 1.0
        cur = tuple(a + (b - a) * ease(p) for a, b in zip(from_r, to_r))
        zx, zy, zw = cur
        sc = OUT_W / zw
        v = tuple((a - b) * sc for a, b in zip(cur, prev_r))                 # zoom box velocity, output px per frame
        step_max = max(step_max, max(abs(x) for x in v))
        jerk_max = max(jerk_max, max(abs(x - y) for x, y in zip(v, prev_v)))  # velocity change between frames: big = a jolt
        prev_r, prev_v = cur, v; zoom_max = max(zoom_max, sc)
        M = np.float32([[k0 * sc, 0, (ox - zx) * sc], [0, k0 * sc, (oy - zy) * sc]])
        if abs(sc - 1) < 1e-4 and abs(zx) < 1e-3 and abs(zy) < 1e-3 and (W, H) == (OUT_W, OUT_H):
            out = f.copy()
        else:
            out = cv2.warpAffine(f, M, (OUT_W, OUT_H), flags=cv2.INTER_CUBIC if k0 * sc > 1.02 else cv2.INTER_LINEAR,
                                 borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))
        if m["kind"] == "insert":
            # the real artifact, cross-faded in and out over 0.35 s, with the "Opening: <file>" label at the top left
            tl, dr = t - m["o0"], m["o1"] - m["o0"]
            al = min(1.0, tl / 0.35, (m["o1"] - t) / 0.35)
            cf = m["r"].frame(tl, dr)
            paste(cf, label_image(m["r"].label, 34), 48, 48, min(1.0, tl / 0.5))
            out = cf if al >= 0.999 else cv2.addWeighted(cf, max(0.0, al), out, 1 - max(0.0, al), 0)
            enc.stdin.write(out.tobytes())
            continue
        for o, x, y in clicks:
            if 0 <= t - o < 0.6:
                click_ripple(out, (x - zx) * sc, (y - zy) * sc, (t - o) / 0.6)
        for oa, ob, x, y, w, h in callouts:
            if oa <= t < ob + 0.35:
                draw_callout(out, (x - zx) * sc, (y - zy) * sc, w * sc, h * sc, (t - oa) / 0.7, 1.0 if t < ob else 1 - (t - ob) / 0.35)
        for a, b, txt in keys:
            if a <= t < b:
                lb = label_image(txt, 40)
                paste(out, lb, OUT_W - lb[0].shape[1] - 48, OUT_H - lb[0].shape[0] - 48, min(1.0, (t - a) / 0.15, (b - t) / 0.25))
        if stage_label and t < 3.8:      # the stage label, top centre, for the first 3.8 s of the clip
            lb = label_image(stage_label, 46)
            al = min(1.0, (t - 0.15) / 0.3, (3.8 - t) / 0.4)
            if al > 0:
                paste(out, lb, (OUT_W - lb[0].shape[1]) / 2, 64, al)
        for a, b, txt, where in wait_labels:
            if a <= t < b:
                lb = label_image(txt, 44 if where == "mid" else 36)
                x = (OUT_W - lb[0].shape[1]) / 2 if where == "mid" else OUT_W - lb[0].shape[1] - 48
                paste(out, lb, x, 48, min(1.0, (t - a) / 0.2, (b - t) / 0.3))
        enc.stdin.write(out.tobytes())
    enc.stdin.close(); enc.wait()
    if enc.returncode:
        raise SystemExit("ffmpeg failed to encode the long-take clip")
    tmp.replace(out_path)
    cuts = [m for m in plan if m["kind"] == "wait" and m["mode"] == "cut"]
    fasts = [m for m in plan if m["kind"] == "wait" and m["mode"] != "cut"]
    acts = [m for m in plan if m["kind"] == "act"]
    inserts = [m for m in plan if m["kind"] == "insert"]
    groups = narration_groups(cfg)
    insert_audio = []
    for m in inserts:
        if m["r"].audio:
            au = dict(m["r"].audio)
            if au.get("volume") is None:
                au["volume"] = 0.35 if groups[m["group"]]["lines"] else 1.0
            insert_audio.append({**au, "out_from": round(m["o0"], 3), "out_to": round(m["o1"], 3)})
    metrics = {"clip": clip.name, "source_s": round(length, 2), "out_s": round(n_frames / FPS, 2),
               "cuts": len(cuts), "cut_s": round(sum(m["s1"] - m["s0"] - (m["o1"] - m["o0"]) for m in cuts), 1),
               "fast": [{"out_from": round(m["o0"], 2), "out_to": round(m["o1"], 2), "source_s": round(m["s1"] - m["s0"], 1),
                         "speed": round((m["s1"] - m["s0"]) / max(1e-3, m["o1"] - m["o0"]), 1)} for m in fasts],
               "fast_saved_s": round(sum(m["s1"] - m["s0"] - (m["o1"] - m["o0"]) for m in fasts), 1),
               "action_fastest": round(max([(m["s1"] - m["s0"]) / max(1e-3, m["o1"] - m["o0"]) for m in acts] or [1]), 3),
               "hold_s": round(sum(m["o1"] - m["o0"] for m in plan if m["kind"] == "hold"), 1),
               "zoom": len(zooms), "zoom_max": round(zoom_max, 2), "zoom_step_max_px": round(step_max, 1), "zoom_jerk_max_px": round(jerk_max, 1),
               "clicks": len(clicks), "key_labels": len(keys), "hide_typing": bool(hl["hide_typing"]), "masks": len(masks),
               "groups": report, "scenes": scenes(plan), "callouts": len(callouts),
               "skip_jumps": [[round(m["o0"] - 0.2, 2), round(m["o1"] + 0.2, 2)] for m in cuts + fasts]}
    if inserts:      # only when there are inserts, so a long take without them writes the same metrics as before
        metrics["inserts"] = [{"out_from": round(m["o0"], 2), "out_to": round(m["o1"], 2), "file": m["r"].file.name, "kind": m["r"].kind} for m in inserts]
        metrics["insert_audio"] = insert_audio
        metrics["skip_jumps"] += [r for m in inserts for r in ([round(m["o0"] - 0.2, 2), round(m["o0"] + 0.6, 2)],
                                                               [round(m["o1"] - 0.6, 2), round(m["o1"] + 0.2, 2)])]
    Path(str(out_path) + ".metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"rendered {out_path.name}: source {length:.1f} s -> {metrics['out_s']:.1f} s; {metrics['cuts']} cuts ({metrics['cut_s']} s), "
          f"{len(fasts)} fast-forwards (saved {metrics['fast_saved_s']} s), held {metrics['hold_s']} s, {len(zooms)} zoom boxes "
          f"(max {zoom_max:.2f}x, step {step_max:.1f} px/frame, jerk {jerk_max:.1f} px/frame²), {len(clicks)} clicks, {len(keys)} key labels, "
          f"{len(callouts)} callouts, {len(masks)} masks, {len(inserts)} artifact inserts; fastest action piece {metrics['action_fastest']}x")
    for b in report:
        if b["short"] > 0.05:
            print(f"WARNING group {b['group']}: the picture is still {b['short']} s longer than the narration at full squeeze; "
                  f"run 'fit' (make_video.py does) to add pause_after")
    return metrics


# ---------------------------------------------------------------- the slide pipeline
def group_seconds(sl_lt, starts, t_in, t_out):
    """Output length of each group: from the start of its first narration line to the start of the next group."""
    edges = [t_in] + [starts[g["from_line"] - 1] for g in sl_lt["groups"][1:]] + [t_out]
    return [max(0.1, b - a) for a, b in zip(edges, edges[1:])]


def render_for_slide(sl, c, root, starts, t_in, t_out):
    """Called by composite_clips.py: render (or reuse, by hash) the edited clip for the slide; returns (path, metrics)."""
    clip = Path(c["file"]); clip = clip if clip.is_absolute() else root / clip
    cfg_p = config_path(clip, c.get("long_take"))
    if not cfg_p.is_file():
        raise SystemExit(f"{sl['id']}: {cfg_p} is missing (run long_take.py analyse {clip})")
    if not sl.get("long_take"):
        raise SystemExit(f"{sl['id']}: the storyboard has no long-take narration groups; run storyboard.py again")
    D = group_seconds(sl["long_take"], starts, t_in, t_out)
    cfg = read_config(cfg_p)
    ev_p = clip.parent / cfg["events"] if cfg.get("events") else None
    h = hashlib.md5()
    for x in (json.dumps(cfg, sort_keys=True, ensure_ascii=False), ",".join(f"{d:.3f}" for d in D), f"{clip.stat().st_size}:{clip.stat().st_mtime_ns}",
              ev_p.read_text(encoding="utf-8") if ev_p and ev_p.is_file() else "", __import__("insert_artifacts").fingerprint(cfg),
              Path(__file__).read_text(encoding="utf-8"), sl.get("clip_label") or ""):
        h.update(x.encode("utf-8"))
    out = clip.parent / "_longtake" / f"{clip.stem}-{h.hexdigest()[:10]}.mp4"
    mp = Path(str(out) + ".metrics.json")
    if out.is_file() and mp.is_file():
        print(f"{sl['id']}: reusing {out.name} (config, narration and clip unchanged)")
        return out, json.loads(mp.read_text(encoding="utf-8"))
    return out, render(clip, cfg_p, out, D, sl.get("clip_label"))


def fit(board_p, tl_p, ov_p):
    sys.path.insert(0, str(HERE))
    from composite_clips import clip_window, line_marks, read_sync_events
    board = json.loads(Path(board_p).read_text(encoding="utf-8"))
    tl = json.loads(Path(tl_p).read_text(encoding="utf-8"))
    ov = json.loads(Path(ov_p).read_text(encoding="utf-8"))
    root = Path(ov_p).resolve().parent
    sync = read_sync_events(board_p)
    slides = board["slides"]
    changed = False
    for i, sl in enumerate(slides):
        c = (ov.get(sl["id"]) or {}).get("clip") or {}
        if not c.get("long_take") or not sl.get("long_take"):
            continue
        clip = Path(c["file"]); clip = clip if clip.is_absolute() else root / clip
        cfg_p = config_path(clip, c.get("long_take"))
        cfg = read_config(cfg_p)
        t_in, t_out, _, _ = clip_window(board, tl, sync, i, c)
        _, report = schedule(cfg, group_seconds(sl["long_take"], line_marks(board, tl), t_in, t_out))
        raw = json.loads(Path(cfg_p).read_text(encoding="utf-8"))
        raw["segments"] = sorted(raw.get("segments") or [], key=lambda d: d["from"])
        for b, g in zip(report, narration_groups(cfg)):
            print(f"{sl['id']} group {b['group']} (segments {b['segments']}): narration {b['D']} s, picture {b['video']} s, held {b['hold']} s"
                  + (f", SHORT {b['short']} s" if b["short"] > 0.05 else ""))
            if b["short"] > 0.05:
                e0 = cfg["segments"][g["segments"][0]]       # expanded segments: map back to the file (an insert or a source segment)
                d0 = raw["inserts"][e0["_insert"]] if "_insert" in e0 else raw["segments"][e0["_orig"]]
                d0["pause_after"] = round(float(d0.get("pause_after") or 0) + math.ceil((b["short"] + 0.1) * 10) / 10, 1)
                print(f"  -> pause_after = {d0['pause_after']} s on segment {g['segments'][0] + 1}")
                changed = True
        if changed:
            Path(cfg_p).write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
    sys.exit(3 if changed else 0)


def main():
    ap = argparse.ArgumentParser(description="Long take: how-to lessons that are mostly screen recording")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("analyse"); p.add_argument("clip")
    p.add_argument("--threshold", type=float, default=DETECT_DEFAULTS["threshold"], help="share of pixels changing between two frames 0.1 s apart below which the screen counts as still")
    p.add_argument("--min-wait", dest="min_wait", type=float, default=DETECT_DEFAULTS["min_wait"], help="shortest wait (seconds)")
    p.add_argument("--allow-blips", dest="allow_blips", type=float, default=DETECT_DEFAULTS["allow_blips"], help="bridge short changes (a spinner, a log line) up to N seconds")
    p.add_argument("--mode", default="fast", choices=["fast", "cut"])
    p.add_argument("--language", default="en", choices=["en", "vi"])
    p.add_argument("--overwrite", action="store_true")
    p = sub.add_parser("render"); p.add_argument("clip"); p.add_argument("out"); p.add_argument("--config"); p.add_argument("--group-seconds", dest="group_seconds")
    p.add_argument("--stage-label", dest="stage_label", help="a label shown at the top for the first 3.8 s of the clip")
    p = sub.add_parser("first-frame"); p.add_argument("clip"); p.add_argument("--config")
    p = sub.add_parser("fit"); p.add_argument("board"); p.add_argument("timeline"); p.add_argument("video_json")
    a = ap.parse_args()
    if a.cmd == "analyse":
        analyse(a)
    elif a.cmd == "render":
        render(a.clip, a.config or config_path(a.clip), a.out, [float(x) for x in a.group_seconds.split(",")] if a.group_seconds else None,
               a.stage_label)
    elif a.cmd == "first-frame":
        print(first_frame(a.clip, a.config or config_path(a.clip)))
    else:
        fit(a.board, a.timeline, a.video_json)


if __name__ == "__main__":
    main()
