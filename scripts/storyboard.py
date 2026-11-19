#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Build the STORYBOARD for one lesson video from an existing slide deck
(slides.json + <file_name>.pptx + _preview/slide-NN.png, as produced by the lesson-slide-designer skill).

Usage:
  python storyboard.py <slides.json> [--out <video folder>] [--overrides <video.json>]

Output (default: videos/<course>/<lesson>/, mirrored from slides/<course>/<lesson>/; otherwise <slides folder>/video/):
  <file_name>.narration.txt   clean narration, one spoken beat per line; "|N" at the end of a line = N extra seconds of silence
  <file_name>.storyboard.json for the renderer: per slide the image, transition, the "regions" (groups of shapes measured
                              from the .pptx) and the actions (which region appears on which narration line and how,
                              circles, zooms, countdowns) plus the sound attached to each action
  <file_name>.storyboard.md   a table to review by eye before rendering

How actions are inferred (see references/motion-and-sound.md):
  - A region is a cluster of shapes in the pptx (a card, a row, a step, a column, a table row). Positions come from the
    pptx, not from pixels, so fonts and themes do not matter.
  - Regions appear in step with the narration: K regions spread over the M narration lines of the slide.
  - The transition and the sounds follow the slide type and rotate so two neighbouring slides never look the same.
  - video.json (optional) overrides any slide: {"S06": {"reveal_lines": [2,3,4,5,6,7], "transition": "iris", "hold": 8,
    "circle": "B", "zoom": 2, "ken_burns": false}}
"""
import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    from pptx import Presentation
except ImportError:
    raise SystemExit("python-pptx is missing: pip install python-pptx")

EMU_PER_INCH = 914400.0
W, H = 1920, 1080
PX = W / 13.3333  # pixels per inch on a 16:9 deck rendered at 1920 wide

THEMES = {
    "navy": dict(bg="14213D", text="FFFFFF", accent="FCA311", card="1F2F55", muted="A9B4CC"),
    "light": dict(bg="FFFFFF", text="1E2761", accent="E05A2B", card="EEF2FA", muted="6B7A99"),
    "forest": dict(bg="0F3D2E", text="F5F5F5", accent="97BC62", card="19523E", muted="B7C9BF"),
    "plum": dict(bg="2D1B4E", text="FFFFFF", accent="F9C846", card="3C2A63", muted="BDB0D6"),
}
THEME_ALIASES = {"xanh-dam": "navy", "sang": "light", "xanh-la": "forest", "tim": "plum"}

# Decks written with the Vietnamese edition of the slide skill use other key and type names: map them once here.
TYPE_ALIASES = {"bia": "title", "muc-tieu": "objectives", "noi-dung": "agenda", "tieu-de-muc": "section", "the": "cards",
                "hai-cot": "two-column", "quy-trinh": "process", "so-sanh": "compare", "so-lon": "big-numbers",
                "cau-hoi": "question", "chot": "key-message", "hinh": "image", "bang": "table", "tom-tat": "summary",
                "ket": "closing", "bieu-do": "chart"}
KEY_ALIASES = {"kieu": "type", "loi_doc": "narration", "ghi_chu": "notes", "thoi_gian": "timer", "tieu_de": "title",
               "cau_hoi": "question", "noi_dung": "message", "ten_tep": "file_name", "giang_vien": "instructor",
               "lien_he": "contact", "khoa": "course", "ten_bai": "lesson_title", "ma_bai": "lesson_code"}

# Transition into a slide, by slide type (preferred first); neighbours never share one.
# Names: push-left (push with a light streak), fade-up, iris (circle opening from the centre), zoom-blur,
# diagonal-wipe, push-up.
TRANSITION_BY_TYPE = {
    "section": ["zoom-blur", "diagonal-wipe"],
    "question": ["iris"],
    "key-message": ["push-up", "iris"],
    "closing": ["zoom-blur"],
    "summary": ["diagonal-wipe", "push-up"],
    "agenda": ["fade-up"],
}
TRANSITION_DEFAULT = ["push-left", "fade-up", "diagonal-wipe", "push-left", "fade-up", "zoom-blur"]
TRANSITION_SOUND = {"push-left": "whoosh", "fade-up": "swoosh", "iris": "transition", "zoom-blur": "transition",
                    "diagonal-wipe": "whoosh", "push-up": "swoosh"}

# How regions appear, by slide type, and the sound that goes with it
REVEAL_BY_TYPE = {
    "cards": ("pop", "pop"), "big-numbers": ("pop", "pop"), "process": ("slide-up", "ui"),
    "objectives": ("slide-up", "ui"), "agenda": ("fade", None), "compare": ("slide-side", "ui"),
    "question": ("slide-up", "click"), "summary": ("pop", "pop"), "table": ("slide-up", "ui"),
    "two-column": ("fade", "swoosh"), "key-message": ("scale-in", "ting"), "closing": ("scale-in", "success"),
    "title": ("fade", None), "section": ("scale-in", None), "image": ("fade", "swoosh"), "chart": ("fade", "swoosh"),
}
# Types whose regions appear one by one with the narration; other types reveal everything at the start, staggered.
# A slide that shows everything at once and then holds still for half a minute is what puts learners to sleep.
STEPPED_TYPES = {"cards", "big-numbers", "process", "objectives", "compare", "question", "summary", "table", "agenda",
                 "two-column", "chart", "key-message", "closing"}
# Attention circles drawn automatically when the line that reveals a region carries an emphasis word
AUTO_CIRCLE_TYPES = {"cards", "process", "objectives", "big-numbers", "table", "compare", "summary", "question", "two-column", "agenda",
                     "chart", "key-message"}
EMPHASIS = re.compile(
    r"(?<![\w])(remember|important|never|don't|do not|mistake|the key|key point|must|always|the point|note that|watch out|"
    r"notice|look at|this one|the answer|only|watch|that is why|this is why|"
    r"careful|critical|essential|crucial|nhớ|quan trọng|đừng|không bao giờ|lỗi|chính là|mấu chốt|lưu ý|cốt lõi|chú ý|"
    r"bắt buộc|tuyệt đối|phải|đáng nhớ|then chốt)(?![\w])", re.I)

PAUSE_PHRASE = re.compile(r"pause (the|this) video|t[ạa]m\s+d[ừu]ng\s+video", re.I)
SELF_PAUSE_HOLD = 3.0   # narration tells learners to press pause: the video only holds 3 s, no countdown
MAX_HOLD = 60.0         # otherwise the video waits for the stated time itself, never longer than this


def px(v):
    return v / EMU_PER_INCH * PX


def normalise(spec):
    """Accept both the English and the Vietnamese slides.json schema."""
    for k, v in list(spec.items()):
        if k in KEY_ALIASES and KEY_ALIASES[k] not in spec:
            spec[KEY_ALIASES[k]] = v
    for d in spec.get("slides", []):
        for k, v in list(d.items()):
            if k in KEY_ALIASES and KEY_ALIASES[k] not in d:
                d[KEY_ALIASES[k]] = v
        d["type"] = TYPE_ALIASES.get(d.get("type"), d.get("type"))
    spec["theme"] = THEME_ALIASES.get(spec.get("theme", "navy"), spec.get("theme", "navy"))
    return spec


class Shape:
    def __init__(self, sh):
        self.name = sh.name
        self.x, self.y, self.w, self.h = px(sh.left or 0), px(sh.top or 0), px(sh.width or 0), px(sh.height or 0)
        self.text = sh.text_frame.text.strip() if sh.has_text_frame else ""
        self.table = sh.table if getattr(sh, "has_table", False) and sh.has_table else None
        self.container = "Rounded Rectangle" in sh.name or ("Oval" in sh.name and self.w >= 36)

    @property
    def cx(self):
        return self.x + self.w / 2

    @property
    def cy(self):
        return self.y + self.h / 2

    def contains(self, o):
        return self.x - 2 <= o.cx <= self.x + self.w + 2 and self.y - 2 <= o.cy <= self.y + self.h + 2

    def bbox(self):
        return [round(self.x), round(self.y), round(self.w), round(self.h)]


def union(bb):
    x0 = min(b[0] for b in bb); y0 = min(b[1] for b in bb)
    x1 = max(b[0] + b[2] for b in bb); y1 = max(b[1] + b[3] for b in bb)
    return [x0, y0, x1 - x0, y1 - y0]


def regions_of_slide(shapes, spec, d):
    """Split the shapes of one slide into static ones (background, title, footer) and regions that will appear."""
    footer = f"{spec.get('instructor', '')} · {spec.get('contact', '')}".strip(" ·")
    stype = d["type"]
    items, static, cands = [], [], []
    for s in shapes:
        if s.w >= W - 4 and s.h >= H - 4:
            continue  # background
        if s.y >= 6.9 * PX or (footer and s.text == footer):
            static.append(s); continue
        if s.w < 14 or s.h < 14:
            static.append(s); continue  # thin decoration
        # label + title band at the top (types without a title band keep their top shapes)
        if stype not in ("title", "section", "key-message", "closing", "question", "image") and s.y < 1.0 * PX \
                and s.y + s.h <= 1.95 * PX and s.text:
            static.append(s); continue
        if stype == "question" and s.y < 1.0 * PX and s.y + s.h <= 1.6 * PX:
            static.append(s); continue  # label and icon in the top corner of a question slide
        cands.append(s)
    if stype == "table":
        for s in cands:
            if s.table is not None:
                y = s.y
                for row in s.table.rows:
                    rh = px(row.height)
                    items.append({"bbox": [round(s.x), round(y), round(s.w), round(rh)],
                                  "text": " | ".join(c.text.strip() for c in row.cells), "shapes": [s.name]})
                    y += rh
            else:
                items.append({"bbox": s.bbox(), "text": s.text, "shapes": [s.name]})
        return static, items
    # 1) containers (rounded rectangles, big ovals) take every shape whose centre is inside them
    conts = sorted([s for s in cands if s.container], key=lambda s: -(s.w * s.h))
    owner = {}
    for s in cands:
        owner[id(s)] = next((c for c in conts if c is not s and c.contains(s) and c.w * c.h > s.w * s.h), None)

    def root(s):
        for _ in range(10):
            if owner.get(id(s)) is None:
                break
            s = owner[id(s)]
        return s

    clusters = {}
    for s in cands:
        r = root(s)
        clusters.setdefault(id(r), {"root": r, "members": []})["members"].append(s)
    cl = list(clusters.values())
    # small ovals (step numbers) are not real containers: treat them as loose shapes joining the row beside them
    for c in cl:
        c["box"] = c["root"].container and not ("Oval" in c["root"].name and c["root"].w < 130)
    boxes = [c for c in cl if c["box"]]
    merged = []
    for c in cl:
        if c["box"] or not boxes:
            merged.append(c); continue
        s = c["root"]
        best = None
        for k in boxes:
            r = k["root"]
            overlap = min(s.y + s.h, r.y + r.h) - max(s.y, r.y)
            if overlap >= 0.5 * min(s.h, r.h):
                gap = max(r.x - (s.x + s.w), s.x - (r.x + r.w), 0)
                if gap < 0.35 * PX and (best is None or gap < best[0]):
                    best = (gap, k)
        if best:
            best[1]["members"].extend(c["members"])
        else:
            merged.append(c)
    # 2) loose shapes on the same row and close together (icon + line of text) become one region
    changed = True
    while changed:
        changed = False
        for i1 in range(len(merged)):
            for i2 in range(i1 + 1, len(merged)):
                a, b = merged[i1], merged[i2]
                if a["box"] or b["box"]:
                    continue
                ba, bb = union([m.bbox() for m in a["members"]]), union([m.bbox() for m in b["members"]])
                overlap = min(ba[1] + ba[3], bb[1] + bb[3]) - max(ba[1], bb[1])
                gap = max(bb[0] - (ba[0] + ba[2]), ba[0] - (bb[0] + bb[2]), 0)
                if overlap >= 0.5 * min(ba[3], bb[3]) and gap < 0.3 * PX:
                    a["members"].extend(b["members"]); merged.pop(i2); changed = True; break
            if changed:
                break
    for c in merged:
        items.append({"bbox": union([m.bbox() for m in c["members"]]),
                      "text": " / ".join(m.text for m in sorted(c["members"], key=lambda m: (m.y, m.x)) if m.text),
                      "shapes": [m.name for m in c["members"]]})
    # 3) reading order: rows, then columns
    items.sort(key=lambda it: (round(it["bbox"][1] / 40), it["bbox"][0]))
    return static, items


# ---- Voice-picture sync helpers ------------------------------------------------------------------------------------
# Transition durations: COPY of TRANS_DUR in assets/engine/video.js. ENTER_SETTLE = rest after the picture has arrived,
# then the voice starts (the slide enters BEFORE its first line, never together with it).
TRANS_SECONDS = {"push-left": .68, "fade-up": .6, "iris": .75, "zoom-blur": .7, "diagonal-wipe": .62, "push-up": .62}
ENTER_SETTLE = 0.4
MAX_CIRCLES = 3
STOPWORDS = set("""the a an and or of to in on at for with by from is are was were be been it its this that these those you your i we our they their
he she his her as but if so not no do does did can will just than then there here what which who how when also into about up out one more all any""".split())
NUM_WORDS = {str(n): w for n, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
                                              "seventeen eighteen nineteen".split())}
for _n in range(20, 100):
    NUM_WORDS[str(_n)] = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()[_n // 10]


def _tokens(txt):
    """(set of content words, set of adjacent word pairs) of a text; numbers are spelled, plurals trimmed."""
    out = []
    for x in re.findall(r"[\w]+", (txt or "").lower()):
        x = NUM_WORDS.get(x, x)
        if len(x) > 3 and x.endswith("s") and not x.endswith("ss"):
            x = x[:-1]
        out.append(x)
    single = {x for x in out if x not in STOPWORDS and (len(x) >= 3 or x.isdigit())}
    pairs = {f"{a} {b}" for a, b in zip(out, out[1:]) if not (a in STOPWORDS and b in STOPWORDS)}
    return single, pairs


def _mid_sentence(word, sentence):
    """True when `word` (capitalised) appears in the MIDDLE of a sentence, i.e. it is a proper name, not a sentence start."""
    for m in re.finditer(r"(?<![\w])" + re.escape(word) + r"(?![\w])", sentence):
        before = sentence[:m.start()].rstrip()
        if before and before[-1] not in ".!?":
            return True
    return False


def match_regions(items, lines, default, first_line=0, ordered=False):
    """On which narration line each region appears: the FIRST line that mentions the region's own words (rare words weigh more,
    a pair of words weighs 1.5x); regions with several ideas (a card with a title and bullets) take the first line that clearly
    mentions ANY of their ideas; a capitalised name or a number that opens an idea counts on its own. A region that no line
    mentions keeps its even-spread default but never appears before a region that IS mentioned and sits earlier in the slide.
    ordered=True (process, table rows, numbered lists): a later region never appears before an earlier one, and it only matches
    lines from the earlier region's line on (a step label "6" would otherwise match the word "six" in the opening sentence)."""
    import math
    K, M = len(items), len(lines)
    if K == 0 or M == 0:
        return default
    fractional = any(not isinstance(x, int) for x in default)   # fewer lines than regions: spread over time
    lt = [_tokens(l) for l in lines]
    df = {}
    for a, b in lt:
        for x in a | b:
            df[x] = df.get(x, 0) + 1
    nums = set(NUM_WORDS.values())
    weight = lambda x: (math.log(1 + M / df.get(x, M)) + 0.3) * (0.3 if (x in nums or x.isdigit()) else 1.0)
    score = lambda a, b, j: sum(weight(x) for x in a & lt[j][0]) + 1.5 * sum(weight(x) for x in b & lt[j][1])
    first = []
    lo = first_line
    for k, it in enumerate(items):
        ideas = [x for x in re.split(r"\n| / | · ", it["text"]) if x.strip()] or [it["text"]]
        table = [[score(*_tokens(x), j) for j in range(M)] for x in ideas]
        cands = []
        for x_, row in zip(ideas, table):
            top = max(row[lo:] or [0])
            j0 = next((j for j in range(lo, M) if row[j] >= max(math.log(1 + M) + 0.35, 0.6 * top)), None)   # one shared word is not enough
            m_ = re.match(r"\W*([A-Z][\w]+|\d+)", x_.strip())
            if m_:
                t_ = NUM_WORDS.get(m_.group(1), m_.group(1).lower())
                if m_.group(1).isdigit() or (t_ not in STOPWORDS and len(t_) >= 3 and m_.group(1)[0].isupper()):
                    one_word = len(re.findall(r"[\w]+", x_)) == 1       # a one-word label ("Next"): the first line that has the word
                    has = lambda j: (re.search(r"(?<![\w])" + re.escape(t_) + r"(?![\w])", lines[j], re.I) is not None) \
                        if (m_.group(1).isdigit() or one_word) else (t_ in lt[j][0] and _mid_sentence(m_.group(1), lines[j]))
                    jr = next((j for j in range(lo, M) if has(j)), None)
                    if jr is not None and (j0 is None or jr < j0):
                        j0 = jr
            if j0 is not None:
                cands.append(j0)
        first.append(min(cands) if cands else None)
        if ordered:
            if first[-1] is not None:
                lo = max(lo, first[-1])
            elif isinstance(default[k], int) and not fractional:
                lo = max(lo, min(default[k], M - 1))
    out, floor = [], first_line
    for k in range(K):
        if first[k] is not None:
            out.append(first[k]); floor = max(floor, first[k]) if not fractional else floor
        else:
            m = default[k]
            out.append(m if fractional else max(m, floor) if m < M else M - 1)
    if ordered:
        for k in range(1, K):
            out[k] = max(out[k], out[k - 1])
    return out


def is_ordered(stype, items):
    """A slide whose regions have a fixed order: process, table rows, numbered lists (3+ regions starting 1, 2, 3...)."""
    if stype in ("process", "table"):
        return True
    nums = [m.group(1) for m in (re.match(r"\s*(\d+)[.)]?(?:\s|$)", it["text"] or "") for it in items) if m]
    return len(nums) >= 3 and nums == [str(n) for n in range(int(nums[0]), int(nums[0]) + len(nums))]


def check_order(sid, stype, when):
    """Machine check: in an ordered slide a later region must not appear before an earlier one."""
    for k in range(1, len(when)):
        if when[k] < when[k - 1]:
            raise SystemExit(f"SHOW ORDER ERROR: {sid} ({stype}) region {k + 1} appears on line {when[k] + 1:g} before region {k} on line "
                             f"{when[k - 1] + 1:g}. In an ordered slide a later region never appears before an earlier one; fix the narration "
                             f"so it mentions them in order, or set \"{sid}\": {{\"order\": false}} in video.json if that is intended.")


def cap_per_line(when, M, cap=2, start=0):
    """closing / question / key-message: at most `cap` regions on the SAME line (the third moves to the next line). The renderer
    staggers regions of one line by 0.25 s and finishes the last 0.3 s before the voice; too many on one line would finish
    AFTER the voice."""
    count, out = {}, list(when)
    for k in range(start, len(out)):
        d = out[k]
        if not isinstance(d, int):
            continue
        while count.get(d, 0) >= cap and d < M - 1:
            d += 1
        count[d] = count.get(d, 0) + 1
        out[k] = d
    return out


def split_paragraphs(items, png, M):
    """One text box holding a whole bullet list is ONE region, so the whole list would appear at once while the voice reads it item by
    item. Split it into one region per paragraph: measure the real text lines on the slide image (rows with ink), then assign
    lines to paragraphs by text length. If that does not fit, keep the single region."""
    try:
        from PIL import Image
        import numpy as np
    except ImportError:
        return items
    im = None
    out = []
    for it in items:
        paras = [x for x in it["text"].split("\n") if x.strip()] if len(it["shapes"]) == 1 else []
        if len(paras) < 3 or M < len(paras):
            out.append(it); continue
        if im is None:
            im = np.asarray(Image.open(png).convert("RGB")).astype(np.int16)
        x, y, w, h = it["bbox"]
        crop = im[max(0, y):y + h, max(0, x):x + w]
        bg = np.median(crop.reshape(-1, 3), 0)
        ink = (np.abs(crop - bg).max(2) > 60).sum(1) > 2
        rows, i = [], 0
        while i < len(ink):
            if ink[i]:
                j = i
                while j + 1 < len(ink) and (ink[j + 1] or (j + 4 < len(ink) and ink[j + 2:j + 5].any())):
                    j += 1
                rows.append((i, j)); i = j + 1
            else:
                i += 1
        rows = [r for r in rows if r[1] - r[0] >= 8]
        n = len(rows)
        per = None
        if n == len(paras):
            per = [1] * n
        elif n > len(paras):
            for cpl in range(10, 200):                 # characters per line: find the width that explains the number of lines
                est = [max(1, -(-len(t) // cpl)) for t in paras]
                if sum(est) == n:
                    per = est; break
        if not per:
            out.append(it); continue
        k = 0
        for t, c in zip(paras, per):
            a, b = rows[k][0], rows[k + c - 1][1]
            out.append({"bbox": [x, y + a - 8, w, b - a + 16], "text": t, "shapes": it["shapes"]})
            k += c
    return out


def long_take_of_slide(sid, ov, out):
    """A slide with a long-take clip (video.json clip.long_take): its narration comes from segments[].narration of
    <clip>.longtake.json, in groups (long_take.py); each group keeps its first and last line so the picture can follow.
    Returns (info, extra pause at the end of the slide)."""
    c = ov.get("clip") or {}
    if not c.get("long_take"):
        return None, 0.0
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from long_take import config_path, narration_groups, read_config
    clip = c["file"] if os.path.isabs(c["file"]) else os.path.join(out, c["file"])
    cfg_p = config_path(clip, c["long_take"])
    if not cfg_p.is_file():
        raise SystemExit(f"{sid}: {cfg_p} is missing; run long_take.py analyse {clip}, then write segments[].narration")
    groups = narration_groups(read_config(cfg_p))
    if not any(g["lines"] for g in groups):
        raise SystemExit(f"{sid}: {cfg_p.name} has no narration yet. Record first, write after: read the action table, then write.")
    lines, info = [], []
    for k, g in enumerate(groups):
        a0 = len(lines)
        gl = list(g["lines"]) or ["."]
        if g["pause"] > 0 and k < len(groups) - 1:
            gl[-1] += f" |{g['pause']:g}"
        lines += gl
        info.append({"segments": [i + 1 for i in g["segments"]], "_a": a0, "_b": len(lines)})
    print(f"{sid}: long take {cfg_p.name}: {len(groups)} narration groups, {len(lines)} lines (instead of the slide's narration)")
    return {"config": str(cfg_p), "groups": info, "_lines": lines}, groups[-1]["pause"]


def narration_lines(d):
    return [l.strip() for l in (d.get("narration") or "").splitlines() if l.strip()]


def seconds_in(txt):
    m = re.search(r"(\d+(?:[,.]\d+)?)\s*(seconds?|secs?|s\b|minutes?|mins?|gi[âa]y|ph[úu]t)", txt or "", re.I)
    if not m:
        return None
    v = float(m.group(1).replace(",", "."))
    return v * 60 if m.group(2).lower().startswith(("min", "ph")) else v


def hold_seconds(d, ov):
    """Silence after the last narration line of a slide, in seconds.
    video.json "hold" wins. A question whose narration says "pause the video" holds SELF_PAUSE_HOLD (the learner presses
    pause; a timer next to a "60 seconds" label would disagree with it). Otherwise the stated timer, capped at MAX_HOLD,
    or 6 s for a question without one. Other slides hold only when the notes ask for it ("hold 5 seconds")."""
    if ov.get("hold") is not None:
        return float(ov["hold"])
    notes = d.get("notes") or ""
    note_hold = re.search(r"(hold|silence|wait|pause for|l[ặa]ng)\s+(\d+(?:[,.]\d+)?)\s*(seconds?|secs?|s\b|gi[âa]y)", notes, re.I)
    if d["type"] == "question":
        if PAUSE_PHRASE.search(d.get("narration") or ""):
            return SELF_PAUSE_HOLD
        t = seconds_in(d.get("timer")) or (float(note_hold.group(2).replace(",", ".")) if note_hold else None)
        return min(t, MAX_HOLD) if t else 6.0
    return min(float(note_hold.group(2).replace(",", ".")), MAX_HOLD) if note_hold else 0.0


def pick_transition(stype, previous, ov):
    if ov.get("transition"):
        return ov["transition"]
    cands = TRANSITION_BY_TYPE.get(stype, TRANSITION_DEFAULT)
    return next((c for c in cands if c != previous), cands[0])


def reveal_lines(K, M):
    """On which narration line (0..M-1) region k (0..K-1) appears. Line 0 is usually a lead-in, so start at line 1."""
    if K == 0:
        return []
    if M >= K + 1:
        return [1 + int(k * (M - 1) / K) for k in range(K)]
    if M == K:
        return list(range(K))
    return [round(k * M / K, 2) for k in range(K)]  # fewer lines than regions: spread over time (fractional line)


def find_region(items, key):
    """Find a region by number (1-based) or by its first letters / any part of its text."""
    if key is None:
        return None
    if isinstance(key, int) or (isinstance(key, str) and key.isdigit()):
        i = int(key) - 1
        return i if 0 <= i < len(items) else None
    k = str(key).strip().lower()
    for i, it in enumerate(items):
        t = it["text"].lower()
        if t == k or t.startswith(k + " ") or t.startswith(k + "/") or t.startswith(k + " /"):
            return i
    return next((i for i, it in enumerate(items) if k in it["text"].lower()), None)


def circle_target(notes):
    m = re.search(r"circle\s+(?:the\s+)?(?:answer|option)\s+([A-Da-d])(?![\w])", notes, re.I) or \
        re.search(r"khoanh\s+(?:đáp án\s+)([A-Da-d])(?![\w])", notes, re.I) or \
        re.search(r"(?:circle|khoanh)\s+(?:the\s+|đáp án\s+)?(\"[^\"]+\"|[^,.;]+?)(?=\s+after|\s+when|\s+and|\s+sau|\s+khi|\s+và|,|\.|;|$)", notes, re.I)
    return m.group(1).strip().strip('"') if m else None


def zoom_target(notes):
    m = re.search(r"(?:zoom(?:\s+in)?(?:\s+on|\s+into)?|ph[óo]ng to)\s+(?:the\s+|ô\s+|vùng\s+)?(?:card\s+|step\s+|cell\s+|thẻ\s+|bước\s+)?([^,.;]+?)(?=\s+when|\s+as|\s+khi|,|\.|;|$)", notes, re.I)
    return m.group(1).strip() if m else None


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__); sys.exit(0 if len(sys.argv) > 1 else 2)
    src = os.path.abspath(sys.argv[1])
    args = sys.argv[2:]
    base = os.path.dirname(src)
    if not os.path.isfile(src):
        raise SystemExit(f"slides.json not found: {src}")
    try:
        with open(src, encoding="utf-8-sig") as f:
            spec = normalise(json.load(f))
    except ValueError as e:
        raise SystemExit(f"{src} is not valid JSON: {e}")
    name = spec.get("file_name") or os.path.splitext(os.path.basename(src))[0]
    if "--out" in args:
        out = os.path.abspath(args[args.index("--out") + 1])
    else:
        parts = base.replace("\\", "/").split("/")
        out = "/".join(parts[:parts.index("slides")] + ["videos"] + parts[parts.index("slides") + 1:]) if "slides" in parts \
            else os.path.join(base, "video")
    os.makedirs(out, exist_ok=True)
    # video.json: --overrides, else the output folder, else next to slides.json. Clip paths in it are relative to its own folder.
    if "--overrides" in args:
        ov_path = os.path.abspath(args[args.index("--overrides") + 1])
    else:
        ov_path = next((p for p in (os.path.join(out, "video.json"), os.path.join(base, "video.json")) if os.path.isfile(p)),
                       os.path.join(out, "video.json"))
    ov_dir = os.path.dirname(ov_path)
    try:
        overrides = json.load(open(ov_path, encoding="utf-8-sig")) if os.path.isfile(ov_path) else {}
    except ValueError as e:
        raise SystemExit(f"{ov_path} is not valid JSON: {e}")
    if overrides:
        print(f"overrides: {ov_path}")
    pptx = os.path.join(base, name + ".pptx")
    if not os.path.isfile(pptx):
        raise SystemExit(f"Missing {pptx}: build the deck first (lesson-slide-designer: build_slides.py).")
    preview = next((p for p in (os.path.join(base, "_preview"), os.path.join(base, "_kiem")) if os.path.isfile(os.path.join(p, "slide-01.png"))), None)
    if not preview:
        raise SystemExit(f"Missing slide images in {base}/_preview: run render_slides.py on the deck first.")
    pslides = list(Presentation(pptx).slides)
    slides = spec["slides"]
    if len(pslides) != len(slides):
        raise SystemExit(f"The pptx has {len(pslides)} slides and slides.json {len(slides)}: rebuild the deck so they match.")
    colors = THEMES.get(spec.get("theme", "navy"), THEMES["navy"])

    lines_all, out_slides, rows = [], [], []
    previous, n_line, n_regions = None, 0, 0
    for i, d in enumerate(slides, 1):
        sid = f"S{i:02d}"
        ov = overrides.get(sid, {})
        png = os.path.join(preview, f"slide-{i:02d}.png")
        if not os.path.isfile(png):
            raise SystemExit(f"Missing {png}: run render_slides.py again.")
        lines = narration_lines(d)
        lt_info, lt_pause = long_take_of_slide(sid, ov, ov_dir)
        if lt_info:
            lines = lt_info.pop("_lines")
        lines = lines or ["."]   # a silent slide gets a short silence from the voice step
        stype = d["type"]
        hold = hold_seconds(d, ov) + lt_pause
        notes = d.get("notes") or ""
        wants_circle = ov.get("circle") is not None or circle_target(notes) is not None
        extra = 2.4 if (hold > 0 and wants_circle) else 0.0   # time for the circle to be drawn after the wait
        if hold > 0:
            lines[-1] += f" |{hold + extra:g}"
        first_line = n_line + 1
        lines_all.extend(lines)
        n_line += len(lines)
        shapes = [Shape(sh) for sh in pslides[i - 1].shapes]
        static, items = regions_of_slide(shapes, spec, d)
        if stype in STEPPED_TYPES and stype != "table" and not ov.get("reveal_lines"):
            items = split_paragraphs(items, png, len(lines))
        # a clip that covers the whole slide: the slide picture IS the first frame of the edited clip (private areas already masked),
        # so the transition goes straight into the clip and no placeholder slide flashes before or after it
        clip_cfg = ov.get("clip") or {}
        covers_clip = bool(lt_info) and clip_cfg.get("mode", "full") == "full"
        if covers_clip:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from long_take import first_frame
            clip_path = clip_cfg["file"] if os.path.isabs(clip_cfg["file"]) else os.path.join(ov_dir, clip_cfg["file"])
            png = str(first_frame(clip_path, lt_info["config"]))
            items, static = [], []
        transition = None if i == 1 else pick_transition(stype, previous, ov)
        previous = transition or previous
        effect, sound = REVEAL_BY_TYPE.get(stype, ("fade", None))
        effect = ov.get("effect", effect)
        M = len(lines)
        stepped = stype in STEPPED_TYPES or bool(re.search(r"reveal (each|one by one|in turn)|one by one|hi[ệe]n (t[ừu]ng|l[ầa]n l[ưu][ợo]t|d[ầa]n)", notes, re.I))
        if ov.get("stepped") is not None:
            stepped = bool(ov["stepped"])
        actions = []
        if items and len(items) > 1 and not stepped and M >= 4 and stype not in ("title", "section", "closing", "image"):
            print(f"WARNING: {sid} ({stype}) shows {len(items)} regions at once and then holds for {M} lines: add "
                  f"\"stepped\": true or \"reveal_lines\" in video.json")
        if items:
            if stepped and len(items) > 1:
                when = ov.get("reveal_lines")
                if when:
                    when = [x - 1 for x in when]   # 1-based in video.json
                else:
                    when = reveal_lines(len(items), M)
                    if stype in ("question", "key-message", "closing"):
                        # the question (or icon and label) shows as the slide arrives; the rest follow the voice
                        when = [0] + [(1 + x) if isinstance(x, int) else round(1 + x, 2) for x in reveal_lines(len(items) - 1, max(1, M - 1))]
                        if M == 1:
                            when = [round(k * 0.6, 2) for k in range(len(items))]
                    ordered = is_ordered(stype, items) and ov.get("order", True) is not False
                    if not lt_info:
                        # each region appears on the FIRST line that mentions it (the voice never talks about a region before it shows)
                        if stype == "table" and M > 1 and len(items) > 1:
                            # header row with the first beat; each data row on the line that mentions it
                            new = [0] + match_regions(items[1:], lines, [min(M - 1, x) for x in reveal_lines(len(items) - 1, M)], 0, ordered)
                        elif stype in ("question", "key-message", "closing") and M > 1:
                            new = cap_per_line([0] + match_regions(items[1:], lines, when[1:], 0), M)   # at most 2 regions per line
                        else:
                            new = match_regions(items, lines, when, ordered=ordered)
                        if new != when:
                            print(f"{sid}: regions appear on the line that mentions them: {[x + 1 if isinstance(x, int) else x for x in when]} -> {[x + 1 for x in new]}")
                            when = new
                        if ordered:
                            check_order(sid, stype, [when[k] if k < len(when) else when[-1] for k in range(len(items))])
                for k in range(len(items)):
                    actions.append({"kind": "reveal", "region": k, "line": when[min(k, len(when) - 1)], "effect": effect, "sound": sound})
            else:
                for k in range(len(items)):
                    actions.append({"kind": "reveal", "region": k, "line": 0, "stagger": k, "effect": effect,
                                    "sound": sound if k == 0 else None})
        # an ellipse only fits regions that are roughly square; a wide card circled with an ellipse cuts its corners
        shape_of = lambda it: "ellipse" if (it["bbox"][2] < 700 and it["bbox"][3] > 150 and it["bbox"][2] / max(1, it["bbox"][3]) < 1.8) else "box"
        target = ov.get("circle") if ov.get("circle") is not None else circle_target(notes)
        ci = find_region(items, target) if target is not None else None
        if ci is not None:
            actions.append({"kind": "circle", "region": ci, "line": M - 1, "after_hold": hold > 0, "sound": "circle",
                            "shape": shape_of(items[ci])})
        elif ov.get("auto_circle", True) and stype in AUTO_CIRCLE_TYPES:
            # attention circles: score every region, circle 1-2 per slide (3 when at least 3 lines carry an emphasis word).
            # Score: emphasis word in the line that reveals it > big number of a big-numbers slide > last row of a table > the region
            # whose words match the line being read best. A circle is drawn while the voice mentions the region, never ahead of it.
            scored = []
            for a in [x for x in actions if x["kind"] == "reveal" and isinstance(x["line"], int)]:
                sentence = lines[a["line"]] if a["line"] < len(lines) else ""
                it = items[a["region"]]
                bb = it["bbox"]
                if bb[3] > 260 and bb[2] >= 700:
                    continue  # a tall loose text block: the box would hug empty space
                if not it["text"].strip() and stype != "big-numbers":
                    continue  # a picture or empty frame: nothing to circle
                w1, w2 = _tokens(it["text"])
                l1, l2 = _tokens(sentence)
                score = 0.3 * len(w1 & l1) + 0.5 * len(w2 & l2)
                if EMPHASIS.search(sentence):
                    score += 3
                if stype == "big-numbers" and re.search(r"\d", it["text"]):
                    score += 2
                if stype == "table" and a["region"] == len(items) - 1 and len(items) > 2:
                    score += 1.5
                if score >= 0.6:
                    scored.append((score, a))
            emphatic = sum(1 for sc, _ in scored if sc >= 3)
            one_per_line = {}
            for sc, a in sorted(scored, key=lambda x: -x[0]):
                one_per_line.setdefault(a["line"], (sc, a))     # at most one circle per line (two at once is confusing)
            chosen = sorted(one_per_line.values(), key=lambda x: -x[0])[:max(1, min(MAX_CIRCLES, 2 if emphatic < 3 else 3))] if M >= 2 else []
            for _sc, a in sorted(chosen, key=lambda x: x[1]["line"]):
                actions.append({"kind": "circle", "region": a["region"], "line": a["line"], "auto": True, "sound": "circle",
                                "shape": shape_of(items[a["region"]])})
        zt = ov.get("zoom") if ov.get("zoom") is not None else zoom_target(notes)
        zi = find_region(items, zt) if zt is not None else None
        if zi is not None:
            actions.append({"kind": "zoom", "region": zi, "line": max(0, M - 1)})
        if hold > SELF_PAUSE_HOLD and stype == "question":
            actions.append({"kind": "countdown", "line": M - 1, "seconds": hold, "end_sound": "ting"})
        # frame for a screen recording: the largest rounded box below the title band, else the largest region
        boxes = [s for s in shapes if "Rounded Rectangle" in s.name and s.y >= 1.5 * PX]
        clip_frame = max(boxes, key=lambda s: s.w * s.h).bbox() if boxes else \
            (max(items, key=lambda it: it["bbox"][2] * it["bbox"][3])["bbox"] if items else None)
        if covers_clip:
            clip_frame = None
        kb = ov.get("ken_burns")
        out_slides.append({
            "id": sid, "type": stype, "image": os.path.relpath(png, out).replace("\\", "/"),
            "from_line": first_line, "to_line": n_line, "transition": transition,
            "lead_wait": round(TRANS_SECONDS.get(transition, .65) + ENTER_SETTLE, 2) if transition else None,
            "covers_clip": covers_clip,
            # the slide's own message is lost when its frame is replaced by the clip: its label and title show over the start of the clip
            "clip_label": (" - ".join(x for x in (str(d.get("label") or "").split(" · ")[0].strip(), str(d.get("title") or "").strip()) if x) or None) if covers_clip else None,
            "transition_sound": TRANSITION_SOUND.get(transition) if transition else None,
            "ken_burns": False if covers_clip else kb if kb is not None else (stype not in ("question", "table")),
            "regions": items, "static": [s.bbox() for s in static], "actions": actions, "clip_frame": clip_frame,
            "notes": notes, "summary": str(d.get("title") or d.get("question") or d.get("message") or spec.get("lesson_title") or "")[:60],
        })
        if lt_info:
            for g in lt_info["groups"]:
                g["from_line"], g["to_line"] = first_line + g.pop("_a"), first_line + g.pop("_b") - 1
            out_slides[-1]["long_take"] = lt_info
        n_regions += len(items)
        when_txt = ",".join(str((a["line"] + 1) if isinstance(a["line"], int) else a["line"]) for a in actions if a["kind"] == "reveal")
        others = ", ".join(a["kind"] + (" (auto)" if a.get("auto") else "") for a in actions if a["kind"] != "reveal")
        rows.append(f"| {sid} | {stype} | {transition or '-'} | {len(items)} | {M} | {when_txt or '-'} | "
                    f"{format(hold + extra, 'g') + ' s' if hold else '-'} | {others or '-'} |")

    board = {"file_name": name, "course": spec.get("course"), "lesson_title": spec.get("lesson_title"),
             "lesson_code": spec.get("lesson_code"), "language": spec.get("language", "en"), "theme": spec.get("theme", "navy"),
             "colors": colors, "sync": 1,
             # the teaching pointer is ON by default for English lessons; set video.json "_all": {"cursor": false} to turn it off
             "cursor": bool((overrides.get("_all") or {}).get("cursor", str(spec.get("language", "en")).lower().startswith("en"))),
             "slides": out_slides, "line_count": n_line}
    with open(os.path.join(out, name + ".narration.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines_all) + "\n")
    with open(os.path.join(out, name + ".storyboard.json"), "w", encoding="utf-8") as f:
        json.dump(board, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out, name + ".storyboard.md"), "w", encoding="utf-8") as f:
        f.write(f"# Storyboard: {spec.get('lesson_code', '')} {spec.get('lesson_title', '')}\n\n")
        f.write("| Slide | Type | Transition | Regions | Narration lines | Regions appear on line | Hold | Other actions |\n"
                "|---|---|---|---|---|---|---|---|\n")
        f.write("\n".join(rows) + "\n")
        f.write(f"\nTotal: {len(out_slides)} slides, {n_line} narration lines, {n_regions} regions.\n")
        f.write("To change anything, write video.json next to this file (reveal_lines, transition, hold, circle, zoom, "
                "ken_burns, stepped, effect, auto_circle, clip) and run again.\n")
    print(f"{name}: {len(out_slides)} slides, {n_line} lines, {n_regions} regions -> {out}")
    flat = [s["id"] for s in out_slides if not s["regions"] and s["type"] != "image"]
    if flat:
        print("WARNING: no regions found (the whole slide appears at once):", ", ".join(flat))


if __name__ == "__main__":
    main()
