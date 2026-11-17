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
AUTO_CIRCLE_TYPES = {"cards", "process", "objectives", "big-numbers", "table", "compare", "summary", "question"}
EMPHASIS = re.compile(
    r"(?<![\w])(remember|important|never|don't|do not|mistake|the key|key point|must|always|the point|note that|watch out|"
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
    with open(src, encoding="utf-8") as f:
        spec = normalise(json.load(f))
    name = spec.get("file_name") or os.path.splitext(os.path.basename(src))[0]
    if "--out" in args:
        out = os.path.abspath(args[args.index("--out") + 1])
    else:
        parts = base.replace("\\", "/").split("/")
        out = "/".join(parts[:parts.index("slides")] + ["videos"] + parts[parts.index("slides") + 1:]) if "slides" in parts \
            else os.path.join(base, "video")
    os.makedirs(out, exist_ok=True)
    ov_path = os.path.abspath(args[args.index("--overrides") + 1]) if "--overrides" in args else os.path.join(out, "video.json")
    overrides = json.load(open(ov_path, encoding="utf-8")) if os.path.isfile(ov_path) else {}
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
        lt_info, lt_pause = long_take_of_slide(sid, ov, out)
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
            count = 0
            for a in [x for x in actions if x["kind"] == "reveal" and isinstance(x["line"], int)]:
                if count >= 3:
                    break
                bb = items[a["region"]]["bbox"]
                if bb[3] > 260 and bb[2] >= 700:
                    continue  # a tall loose text block: the box would hug empty space
                if EMPHASIS.search(lines[a["line"]] if a["line"] < len(lines) else ""):
                    actions.append({"kind": "circle", "region": a["region"], "line": a["line"], "auto": True, "sound": "circle",
                                    "shape": shape_of(items[a["region"]])})
                    count += 1
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
        kb = ov.get("ken_burns")
        out_slides.append({
            "id": sid, "type": stype, "image": os.path.relpath(png, out).replace("\\", "/"),
            "from_line": first_line, "to_line": n_line, "transition": transition,
            "transition_sound": TRANSITION_SOUND.get(transition) if transition else None,
            "ken_burns": kb if kb is not None else (stype not in ("question", "table")),
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
             "colors": colors, "cursor": bool((overrides.get("_all") or {}).get("cursor", False)),
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
