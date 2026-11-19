#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
INSERT THE REAL ARTIFACT into a long take (used by long_take.py; not run directly).

When Claude Code reports that a job is done, learners must SEE what it made (the document, the slides, the video), not
only the line in the terminal that says it is done. No extra window is recorded: at render time long_take.py inserts a
piece of picture built from the artifact file itself, right after the result review.

Declared in <clip>.longtake.json, key "inserts" (a list):
  {"after": 72.64 | "mark-name",   where: a SOURCE second of the clip, or a mark name (= the start of the segment with that mark)
   "after_end_of": "mark-name",    (instead of "after") the end of the segment with that mark; "end" = the end of the clip
   "file": "path/to/file",         absolute, or relative to the folder of the config
   "kind": "auto|document|text|slides|image|video",   auto (the default) guesses from the extension
   "seconds": 12,                  natural length in the output. Empty: computed (scrolling at about 200 px/s, at most 24 s;
                                   slides 2.5 s for the overview plus 2.2 s per slide)
   "pages": [1, 2],                document: the pages to show; slides: the slides to show (numbered from 1)
   "lines": [1, 60],               text (md/txt/json/csv): the lines from-to
   "static": true,                 text: ONE still frame (no scrolling) that fits 1080 px, so zoom and outline can point at an exact spot
   "outline": [{"from": 2, "to": 12, "box": [x, y, w, h]}]   orange frame around a region, fading in over 0.3 s; box on the 1920x1080
                                   frame BEFORE the zoom (so it follows the zoom); seconds inside the insert. For still frames
                                   (images, static text); on a scrolling strip the frame does not follow the text
   "start": 0, "length": 10,       video: the part to play (seconds of the inserted video); "volume": 0.35 (default 1 without
                                   narration, 0.35 under narration)
   "zoom": [{"from": 2, "to": 8, "box": [x, y, w], "ease": 0.8}]   seconds INSIDE the insert; box = x, y, width on the 1920x1080
                                   frame of the insert (widened to 16:9); slow-fast-slow moves
   "narration": "What the voice says while the insert runs", "pause_after": 0, "label": "your own label text"}
An insert is a SEGMENT of its own in "segments" (the source frame stands still at the insert point; a source segment that
runs across the point is split in two), so: with "narration" it opens a new narration group, without it the group before
carries on; a picture longer or shorter than its narration makes the insert stretch (slower scroll) or shrink (down to
70%, never under 2 s); a video insert never shrinks. The fast-forward and cut rules for waits never touch an insert.
File types: .docx .doc .odt .rtf (headless LibreOffice -> PDF -> pdftoppm), .pdf, .md .txt .json .csv (drawn as large light
text on the dark theme), .pptx .ppt .odp (uses _preview/slide-NN.png and contact-sheet.png next to the deck when present,
or _kiem/slide-NN.png and to-anh.png from the Vietnamese edition, otherwise LibreOffice -> PDF -> images; the overview
first, then each slide full size), .png .jpg .webp, .mp4 .mov .webm .mkv (a video with sound writes "insert_audio" into
<out>.metrics.json; composite_clips.py mixes it under the voice).
Label at the top left: "Opening: <file name>" (en) / "Đang mở: <file name>" (vi), on a 132 px band kept free at the top so
scrolled text never runs under it. Cache: <config folder>/_insert-cache/ (a changed file gets new pages).
"""
import glob
import hashlib
import json
import shutil
import subprocess
import tempfile
import textwrap
import uuid
from pathlib import Path

import numpy as np

OUT_W, OUT_H = 1920, 1080
BG_BGR = (61, 33, 20)          # the dark-blue theme
EDGE_BGR = (150, 120, 90)
ACCENT_RGB = (252, 163, 17)
PAGE_W = 1500                  # width of a page on the 1920 frame (white margins cropped)
SCROLL_SPEED = 200.0           # px/s
SCROLL_MAX = 24.0
OVERVIEW_S, PER_SLIDE_S = 2.5, 2.2
CROSS = 0.3
BAND = 132                     # top band kept for the "Opening: ..." label (drawn at y 48 to 117 by long_take.py)
_CACHE = {}

KIND_BY_EXT = {}
for _k, _exts in {"document": ".docx .doc .odt .rtf .pdf", "text": ".md .txt .json .csv", "slides": ".pptx .ppt .odp",
                  "image": ".png .jpg .jpeg .webp .bmp", "video": ".mp4 .mov .webm .mkv .avi"}.items():
    for _e in _exts.split():
        KIND_BY_EXT[_e] = _k
OPENING = {"en": "Opening: {t}", "vi": "Đang mở: {t}"}


def ease(u):
    u = min(1.0, max(0.0, u))
    return u * u * u * (u * (u * 6 - 15) + 10)


def _font(sz, mono=False, bold=False):
    from PIL import ImageFont
    names = (["C:/Windows/Fonts/consola.ttf", "/System/Library/Fonts/Menlo.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
              "DejaVuSansMono.ttf"] if mono else
             (["C:/Windows/Fonts/seguisb.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"] if bold else [])
             + ["C:/Windows/Fonts/segoeui.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "DejaVuSans.ttf"])
    for f in names:
        try:
            return ImageFont.truetype(f, sz)
        except OSError:
            continue
    return ImageFont.load_default()


def _find(name, *candidates):
    p = shutil.which(name)
    if p:
        return p
    for c in candidates:
        for g in (glob.glob(c) if "*" in c else [c]):
            if Path(g).is_file():
                return g
    return None


def _soffice():
    p = _find("soffice", r"C:\Program Files\LibreOffice\program\soffice.exe", r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
              "/Applications/LibreOffice.app/Contents/MacOS/soffice") or _find("libreoffice")
    if not p:
        raise SystemExit("insert_artifacts: LibreOffice (soffice) not found; it turns office files into pages")
    return p


def _pdftoppm():
    p = _find("pdftoppm", str(Path.home() / "AppData/Local/Microsoft/WinGet/Packages/oschwartz10612.Poppler*/poppler-*/Library/bin/pdftoppm.exe"))
    if not p:
        raise SystemExit("insert_artifacts: pdftoppm (Poppler) not found; on Windows: winget install oschwartz10612.Poppler")
    return p


def _to_pdf(src, dest):
    """Office file -> PDF with headless LibreOffice and a profile of its own (no lock fight with an open LibreOffice)."""
    dest.mkdir(parents=True, exist_ok=True)
    profile = Path(tempfile.gettempdir()) / f"lo-insert-{uuid.uuid4().hex[:8]}"
    try:
        subprocess.run([_soffice(), f"-env:UserInstallation={profile.as_uri()}", "--headless", "--convert-to", "pdf", "--outdir", str(dest), str(src)],
                       check=True, capture_output=True, timeout=240)
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    out = dest / (Path(src).stem + ".pdf")
    if not out.is_file():
        raise SystemExit(f"insert_artifacts: LibreOffice made no PDF for {src}")
    return out


def _pdf_to_images(pdf, dest, dpi):
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run([_pdftoppm(), "-r", str(dpi), "-png", str(pdf), str(dest / "p")], check=True, capture_output=True, timeout=240)
    return sorted(dest.glob("p-*.png"), key=lambda p: int(p.stem.split("-")[-1]))


def _read(p):
    import cv2
    im = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)
    if im is None:
        raise SystemExit(f"insert_artifacts: cannot read the image {p}")
    return im


def _fit(im, w=OUT_W, h=OUT_H, margin=0.0):
    """Fit an image in the frame (below the label band, with a relative margin) on the dark background."""
    import cv2
    s = min(w * (1 - margin) / im.shape[1], (h - BAND - 20) * (1 - margin) / im.shape[0])
    nw, nh = max(1, int(round(im.shape[1] * s))), max(1, int(round(im.shape[0] * s)))
    r = cv2.resize(im, (nw, nh), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    out = np.empty((h, w, 3), np.uint8); out[:] = BG_BGR
    x, y = (w - nw) // 2, BAND + (h - BAND - nh) // 2
    out[y:y + nh, x:x + nw] = r
    cv2.rectangle(out, (x - 2, y - 2), (x + nw + 1, y + nh + 1), EDGE_BGR, 2)
    return out


def _page_strip(images):
    """Stack the pages into one tall 1920-wide strip, pages centred with a light edge, on the dark background."""
    import cv2
    pad, gap = 60, 50
    # crop the white margins (the text area shared by all pages, plus 36 px) so the text is larger on screen
    x0, x1 = images[0].shape[1], 0
    for a in images:
        cols = np.where((a.min(axis=2) < 200).any(axis=0))[0]
        if len(cols):
            x0, x1 = min(x0, int(cols[0])), max(x1, int(cols[-1]))
    if x1 - x0 > 100:
        x0, x1 = max(0, x0 - 36), min(images[0].shape[1], x1 + 36)
        images = [a[:, x0:x1] for a in images]
    pages = [cv2.resize(a, (PAGE_W, int(round(a.shape[0] * PAGE_W / a.shape[1]))), interpolation=cv2.INTER_AREA) for a in images]
    height = pad * 2 + sum(p.shape[0] for p in pages) + gap * (len(pages) - 1)
    strip = np.empty((height, OUT_W, 3), np.uint8); strip[:] = BG_BGR
    y, x = pad, (OUT_W - PAGE_W) // 2
    for p in pages:
        cv2.rectangle(strip, (x - 2, y - 2), (x + PAGE_W + 1, y + p.shape[0] + 1), EDGE_BGR, 2)
        strip[y:y + p.shape[0], x:x + PAGE_W] = p
        y += p.shape[0] + gap
    return strip


def _text_strip(txt, ext, lines=None):
    """md/txt/json/csv -> a tall strip of large light text on the dark background (headings in the accent colour)."""
    from PIL import Image, ImageDraw
    rows = txt.replace("\r\n", "\n").splitlines()
    if ext == ".json":
        try:
            rows = json.dumps(json.loads(txt), ensure_ascii=False, indent=2).splitlines()
        except ValueError:
            pass
    if lines:
        rows = rows[max(0, int(lines[0]) - 1):int(lines[1])]
    mono_all = ext in (".json", ".csv")
    BLOCK_W, X0, PAD = 1480, (OUT_W - 1480) // 2, 70
    bg, fg, accent = tuple(reversed(BG_BGR)), (240, 244, 250), ACCENT_RGB
    items, in_code = [], False        # (font, colour, indent, text, space after)
    f_body, f_mono = _font(32), _font(29, mono=True)
    meas = ImageDraw.Draw(Image.new("RGB", (8, 8)))

    def wrap(t, f, w):
        out, cur = [], ""
        for word in t.split(" "):
            test = (cur + " " + word).strip() if cur else word
            if meas.textlength(test, font=f) <= w or not cur:
                cur = test
            else:
                out.append(cur); cur = word
        out.append(cur)
        return out

    for ln in rows:
        s = ln.rstrip()
        if s.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code or mono_all or s.startswith("|") or (ext == ".txt" and not s.strip()):
            if not s.strip():
                items.append((f_mono, fg, 0, "", 16)); continue
            ind = len(s) - len(s.lstrip())
            cw = max(1, int(meas.textlength("M", font=f_mono)))
            n = max(10, (BLOCK_W - 20) // cw)
            for p in textwrap.wrap(s.replace("\t", "    "), n, subsequent_indent=" " * (ind + 4), break_long_words=True, drop_whitespace=True) or [""]:
                items.append((f_mono, (200, 220, 255) if in_code else fg, 0, p, 6))
            continue
        if not s.strip():
            items.append((f_body, fg, 0, "", 18)); continue
        t = s.replace("**", "").replace("`", "").replace("__", "")
        if t.startswith("#"):
            n = len(t) - len(t.lstrip("#")); t = t.lstrip("#").strip()
            f = _font({1: 56, 2: 46, 3: 40}.get(n, 36), bold=True)
            for p in wrap(t, f, BLOCK_W):
                items.append((f, accent, 0, p, 10))
            items.append((f_body, fg, 0, "", 8)); continue
        ind = (len(t) - len(t.lstrip())) // 2 * 36
        t = t.strip()
        if t[:2] in ("- ", "* "):
            t = "•  " + t[2:]; ind += 12
        for k, p in enumerate(wrap(t, f_body, BLOCK_W - ind - (36 if t.startswith("•") else 0))):
            items.append((f_body, fg, ind + (36 if k and t.startswith("•") else 0), p, 12))
    height = PAD * 2 + sum(int(f.size * 1.32) + g for f, _, _, _, g in items)
    im = Image.new("RGB", (OUT_W, max(height, OUT_H)), bg)
    d = ImageDraw.Draw(im)
    y = PAD
    for f, col, ind, t, g in items:
        if t:
            d.text((X0 + ind, y), t, font=f, fill=col)
        y += int(f.size * 1.32) + g
    return np.asarray(im)[..., ::-1].copy()


def _has_audio(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True)
    return bool(r.stdout.strip())


class Insert:
    """A prepared insert: .seconds (natural), .fixed (never shrinks), .frame(t, dur) -> BGR 1920x1080, .label, .audio."""

    def __init__(self, item, root, lang="en"):
        self.item = item
        f = Path(item["file"])
        f = f if f.is_absolute() else Path(root) / f
        if not f.is_file():
            raise SystemExit(f"insert_artifacts: file not found {f}")
        self.file = f
        ext = f.suffix.lower()
        kind = item.get("kind") or "auto"
        if kind == "auto":
            kind = KIND_BY_EXT.get(ext)
            if not kind:
                raise SystemExit(f"insert_artifacts: cannot tell the kind of {f.name}; set \"kind\"")
        if kind == "document" and ext in (".md", ".txt", ".json", ".csv"):
            kind = "text"
        if kind not in ("document", "text", "slides", "image", "video"):
            raise SystemExit(f"insert_artifacts: unknown kind '{kind}' for {f.name}")
        self.kind, self.zoom = kind, item.get("zoom") or []
        self.label = item.get("label") or OPENING.get(lang, OPENING["en"]).format(t=f.name)
        self.audio, self.fixed = None, False
        h = hashlib.md5(f"{f.resolve()}|{f.stat().st_size}|{f.stat().st_mtime_ns}".encode()).hexdigest()[:10]
        cache = Path(root) / "_insert-cache" / f"{f.stem[:40]}-{h}"
        getattr(self, "_" + kind)(item, f, ext, cache)

    # ---- document / text: one tall strip, scrolled smoothly
    def _set_strip(self, strip, seconds):
        self.strip = strip
        self.ymax = max(0, strip.shape[0] - OUT_H)
        natural = 2.0 + (self.ymax + BAND) / SCROLL_SPEED
        self.seconds = float(seconds) if seconds else min(SCROLL_MAX, max(4.0, natural))
        self.mode = "scroll"

    def _document(self, item, f, ext, cache):
        if ext == ".pdf":
            pdf = f
        else:
            pdf = cache / (f.stem + ".pdf")
            if not pdf.is_file():
                pdf = _to_pdf(f, cache)
        pages = sorted(cache.glob("p-*.png"), key=lambda p: int(p.stem.split("-")[-1])) if cache.is_dir() else []
        if not pages:
            pages = _pdf_to_images(pdf, cache, 200)
        sel = item.get("pages")
        if sel:
            pages = [pages[i - 1] for i in range(int(sel[0]), int(sel[-1]) + 1) if 1 <= i <= len(pages)]
        if not pages:
            raise SystemExit(f"insert_artifacts: no pages in {f.name}")
        self._set_strip(_page_strip([_read(p) for p in pages]), item.get("seconds"))

    def _text(self, item, f, ext, cache):
        # utf-8-sig: a byte order mark (Windows editors, PowerShell) would turn "# Title" into plain text
        strip = _text_strip(f.read_text(encoding="utf-8-sig", errors="replace"), ext, item.get("lines"))
        if item.get("static"):
            # ONE still frame (so zoom and outline can point at an exact spot): the text goes below the label band and must fit 1080 px
            used = np.nonzero((strip != np.array(BG_BGR, np.uint8)).any(axis=2).any(axis=1))[0]
            height = int(used.max()) + 1 if len(used) else 0
            top = BAND - 40
            if height + top > OUT_H:
                raise SystemExit(f"insert_artifacts: \"static\" but the text is {height} px high and does not fit one frame under the label band; use fewer \"lines\"")
            im = np.empty((OUT_H, OUT_W, 3), np.uint8); im[:] = BG_BGR
            im[top:top + height] = strip[:height]
            self.mode, self.im, self.seconds = "still", im, float(item.get("seconds") or 12)
            return
        self._set_strip(strip, item.get("seconds"))

    def _image(self, item, f, ext, cache):
        self.mode, self.im, self.seconds = "still", _fit(_read(f), margin=0.08), float(item.get("seconds") or 6)

    # ---- slides: the overview, then each slide
    def _slides(self, item, f, ext, cache):
        pics, overview = [], None
        for folder, sheet in (("_preview", "contact-sheet.png"), ("_kiem", "to-anh.png")):
            d = f.parent / folder
            if d.is_dir() and sorted(d.glob("slide-*.png")):
                pics = sorted(d.glob("slide-*.png"))
                overview = d / sheet if (d / sheet).is_file() else None
                break
        if not pics:
            pdf = cache / (f.stem + ".pdf")
            if not pdf.is_file():
                pdf = _to_pdf(f, cache)
            pics = sorted(cache.glob("p-*.png"), key=lambda p: int(p.stem.split("-")[-1])) if cache.is_dir() else []
            if not pics:
                pics = _pdf_to_images(pdf, cache, 120)
        sel = item.get("pages")
        if sel:
            pics = [pics[i - 1] for i in range(int(sel[0]), int(sel[-1]) + 1) if 1 <= i <= len(pics)]
        if not pics:
            raise SystemExit(f"insert_artifacts: no slides in {f.name}")
        self.slides = [_fit(_read(p), margin=0.06) for p in pics]
        self.overview = _fit(_read(overview) if overview is not None and not sel else self._grid(pics), margin=0.06)
        self.mode = "slides"
        self.seconds = float(item.get("seconds") or (OVERVIEW_S + PER_SLIDE_S * len(pics)))

    @staticmethod
    def _grid(pics):
        import cv2
        n = len(pics)
        cols = 1 if n == 1 else 2 if n <= 4 else 3 if n <= 9 else 4 if n <= 16 else 5
        rows = -(-n // cols)
        tw = 640 if cols <= 3 else 480; th = int(tw * 9 / 16)
        g = np.empty((rows * (th + 12) + 12, cols * (tw + 12) + 12, 3), np.uint8); g[:] = BG_BGR
        for i, p in enumerate(pics):
            im = cv2.resize(_read(p), (tw, th), interpolation=cv2.INTER_AREA)
            r, c = divmod(i, cols)
            g[12 + r * (th + 12):12 + r * (th + 12) + th, 12 + c * (tw + 12):12 + c * (tw + 12) + tw] = im
        return g

    # ---- video
    def _video(self, item, f, ext, cache):
        import cv2
        cap = cv2.VideoCapture(str(f))
        n, fps = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 1, cap.get(cv2.CAP_PROP_FPS) or 30
        src_len = n / fps
        start = float(item.get("start") or 0)
        length = float(item.get("length") or item.get("seconds") or min(15.0, max(1.0, src_len - start)))
        length = min(length, max(0.5, src_len - start))
        self.cap, self.start, self.fps, self.mode, self.seconds, self.fixed, self._cur, self._f = cap, start, fps, "video", length, True, -1, None
        if _has_audio(f):
            self.audio = {"file": str(f), "start": start, "length": length, "volume": item.get("volume")}

    def _video_frame(self, s):
        idx = int(round((self.start + s) * self.fps))
        if idx != self._cur:
            if idx < self._cur or idx > self._cur + 30:
                self.cap.set(1, idx); self._cur = idx - 1
            while self._cur < idx:
                ok, f = self.cap.read()
                if not ok:
                    break
                self._cur += 1; self._f = f
        return self._f

    # ---- the frame at time t of an insert lasting dur
    def frame(self, t, dur):
        import cv2
        dur = max(0.2, dur)
        if self.mode == "scroll":
            h0 = min(1.0, dur * 0.12)
            u = (t - h0) / max(0.1, dur - 2 * h0)
            y = -BAND + (self.ymax + BAND) * ease(u)
            M = np.float32([[1, 0, 0], [0, 1, -y]])
            out = cv2.warpAffine(self.strip, M, (OUT_W, OUT_H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=BG_BGR)
        elif self.mode == "still":
            out = self.im.copy()
        elif self.mode == "slides":
            ts = min(OVERVIEW_S, dur * 0.25)
            per = (dur - ts) / len(self.slides)
            if t < ts:
                out = self.overview.copy()
            else:
                i = min(len(self.slides) - 1, int((t - ts) / per))
                a = (t - ts) - i * per
                cur = self.slides[i]
                prev = self.overview if i == 0 else self.slides[i - 1]
                al = ease(a / CROSS) if a < CROSS else 1.0
                out = cur.copy() if al >= 1 else cv2.addWeighted(cur, al, prev, 1 - al, 0)
        else:
            f = self._video_frame(min(t, self.seconds))
            out = _fit(f) if f is not None else np.full((OUT_H, OUT_W, 3), BG_BGR, np.uint8)
        out = self._outline(out, t)
        out = self._zoom(out, t)
        out[:BAND - 8] = BG_BGR          # the label band: scrolled text never runs under the label
        return out

    def _outline(self, out, t):
        """"outline": [{"from", "to", "box": [x, y, w, h]}]: an orange frame around a region, fading in over 0.3 s. Drawn on the
        1920x1080 frame BEFORE the zoom, so it follows the zoom. For still frames; on a scrolling strip it does not follow the text."""
        import cv2
        for o in self.item.get("outline") or []:
            a, b = float(o.get("from", 0)), float(o.get("to", 1e9))
            if not a <= t <= b:
                continue
            alpha = min(1.0, (t - a) / 0.3)
            x, y, w, h = (int(v) for v in o["box"])
            ov = out.copy()
            cv2.rectangle(ov, (x, y), (x + w, y + h), tuple(reversed(ACCENT_RGB)), 6, cv2.LINE_AA)
            out = cv2.addWeighted(ov, alpha, out, 1 - alpha, 0)
        return out

    def _zoom(self, out, t):
        import cv2
        if not self.zoom:
            return out
        full = (0.0, 0.0, float(OUT_W))
        frm, to, t_set, ease_s = full, full, -1e9, 0.8
        moves = []
        for z in self.zoom:
            x, y, w = z["box"][0], z["box"][1], z["box"][2]
            h = z["box"][3] if len(z["box"]) > 3 else w * 9 / 16
            cx, cy = x + w / 2, y + h / 2
            w = max(w, h * 16 / 9); h = w * 9 / 16
            x = min(max(0.0, cx - w / 2), OUT_W - w); y = min(max(0.0, cy - h / 2), OUT_H - h)
            moves.append((float(z["from"]), (x, y, w), float(z.get("ease", 0.8))))
            moves.append((float(z["to"]), full, float(z.get("ease", 0.8))))
        moves.sort(key=lambda m: m[0])
        for a, target, e in moves:
            if a > t:
                break
            p = min(1.0, (a - t_set) / ease_s) if ease_s > 0 else 1.0
            frm = tuple(q + (r - q) * ease(p) for q, r in zip(frm, to))
            to, t_set, ease_s = target, a, e
        p = min(1.0, (t - t_set) / ease_s) if ease_s > 0 else 1.0
        zx, zy, zw = (q + (r - q) * ease(p) for q, r in zip(frm, to))
        if zw >= OUT_W - 0.01:
            return out
        sc = OUT_W / zw
        M = np.float32([[sc, 0, -zx * sc], [0, sc, -zy * sc]])
        return cv2.warpAffine(out, M, (OUT_W, OUT_H), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=BG_BGR)


def prepare(item, root, lang):
    """Prepare (and remember) an insert."""
    k = (json.dumps(item, sort_keys=True, ensure_ascii=False), str(root), lang)
    if k not in _CACHE:
        _CACHE[k] = Insert(item, root, lang)
    return _CACHE[k]


def fingerprint(cfg):
    """Size and modification time of every inserted file, so the hash of the rendered clip changes when a file changes."""
    out = []
    for it in cfg.get("inserts") or []:
        p = Path(it.get("file", "")); p = p if p.is_absolute() else Path(cfg.get("_dir", ".")) / p
        out.append(f"{p}:{p.stat().st_size}:{p.stat().st_mtime_ns}" if p.is_file() else f"{p}:missing")
    return "|".join(out)


def expand(cfg):
    """Turn cfg["inserts"] into insert segments inside cfg["segments"]; split a source segment when the point falls inside it.
    Every segment gets "_orig" (its index in the file) and every insert segment "_insert" (its index in "inserts"), so
    long_take.py fit can write pause_after back to the right place."""
    segs = cfg["segments"]
    for i, d in enumerate(segs):
        d["_orig"] = i
    items = cfg.get("inserts") or []
    if not items:
        return
    at = {idx: _insert_point(it, segs) for idx, it in enumerate(items)}
    pending = sorted(at, key=lambda idx: (at[idx], idx))
    out = []

    def insert_segment(idx):
        it = items[idx]
        return {"from": at[idx], "to": at[idx], "narration": it.get("narration", ""), "pause_after": it.get("pause_after", 0),
                "insert": it, "_insert": idx, "what": f"insert {Path(it['file']).name}"}

    for d in segs:
        while pending and at[pending[0]] <= d["from"] + 1e-6:
            out.append(insert_segment(pending.pop(0)))
        a, b = d["from"], d["to"]
        cuts = [i for i in pending if a + 1e-6 < at[i] < b - 1e-6]
        if not cuts:
            out.append(d); continue
        cur = dict(d); cur["to"] = at[cuts[0]]; out.append(cur)
        for j, i in enumerate(cuts):
            out.append(insert_segment(i)); pending.remove(i)
            nxt = {k: v for k, v in d.items() if k != "mark"}
            nxt["narration"], nxt["pause_after"] = "", 0
            nxt["from"] = at[i]; nxt["to"] = at[cuts[j + 1]] if j + 1 < len(cuts) else b
            out.append(nxt)
    for i in pending:
        out.append(insert_segment(i))
    cfg["segments"] = out


def _insert_point(it, segs):
    v = it.get("after", it.get("after_end_of"))
    if v is None:
        raise SystemExit("insert_artifacts: every insert needs \"after\" (seconds or a mark name) or \"after_end_of\"")
    if isinstance(v, (int, float)):
        return float(v)
    if v == "end":
        return float(segs[-1]["to"]) if segs else 0.0
    for d in segs:
        if d.get("mark") == v:
            return float(d["to"] if "after_end_of" in it else d["from"])
    raise SystemExit(f"insert_artifacts: no segment has the mark '{v}'")


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print(__doc__)   # a library of long_take.py: nothing to run, the docstring lists every field of an insert
