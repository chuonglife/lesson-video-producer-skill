#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CHECK THE FINISHED LESSON VIDEO with measurements, then write a report. Exit code 1 when a hard rule fails.

Usage:  python check_video.py <video.mp4> [--timeline <timeline.json>] [--events <events.json>] [--out <report.md>]

Measures against the thresholds in references/quality-checks.md:
  1. Picture: 1920x1080, 30 fps, H.264 yuv420p, length matches the timeline (within 1 s).
  2. Sound: integrated loudness -20 to -15 LUFS, true peak at most -1 dBTP, both channels present, no silence over 12 s
     except the pauses left for learners (gaps over 3 s between narration lines).
  3. Motion: nothing stands still for more than 25 s (frame difference sampled every second, learner pauses excepted);
     no jumpy scrolling (check_motion.py, ignoring 0.9 s around each slide change).
  4. Density: 4 to 16 sound effects per minute; 1 to 6 slides per minute.
  5. Contact sheets: _check/contact-NN.png, three frames per slide (arriving, settled, about to leave). LOOK at them
     before reporting the video as done.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
HERE = Path(__file__).resolve().parent


def ff_log(args):
    return subprocess.run(["ffmpeg", "-hide_banner", "-nostats", *args], capture_output=True, text=True, encoding="utf-8", errors="replace").stderr


def probe(f):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,r_frame_rate,pix_fmt,codec_name,channels:format=duration",
                        "-of", "json", str(f)], capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def loudness(f):
    e = ff_log(["-i", str(f), "-af", "ebur128=peak=true", "-vn", "-f", "null", "-"])
    s = e[e.rfind("Summary:"):]
    lufs = float(re.search(r"I:\s+(-?[\d.]+) LUFS", s).group(1))
    lra = float(re.search(r"LRA:\s+([\d.]+) LU", s).group(1))
    peak = float(re.search(r"Peak:\s+(-?[\d.]+) dBFS", s).group(1))
    chans = []
    for c in (0, 1):
        m = re.search(r"mean_volume:\s+(-?[\d.]+) dB", ff_log(["-i", str(f), "-af", f"pan=mono|c0=c{c},volumedetect", "-vn", "-f", "null", "-"]))
        chans.append(float(m.group(1)) if m else -99.0)
    sil = ff_log(["-i", str(f), "-af", "silencedetect=noise=-40dB:d=4", "-vn", "-f", "null", "-"])
    silences = [(float(a), float(b)) for a, b in re.findall(r"silence_start: ([\d.]+)[\s\S]*?silence_duration: ([\d.]+)", sil)]
    return lufs, lra, peak, chans, silences


def grey_frames(f, every=1.0):
    p = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-i", str(f), "-vf", f"fps=1/{every},scale=160:90,format=gray", "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
    out = []
    while True:
        b = p.stdout.read(160 * 90)
        if len(b) < 160 * 90:
            break
        out.append(np.frombuffer(b, np.uint8).reshape(90, 160).astype(np.float32))
    return out


def contact_sheets(video, slides, folder):
    folder.mkdir(parents=True, exist_ok=True)
    marks = []
    for s in slides:
        t0, t1 = s["t0"], s["t1"]
        marks += [(s["id"], "in", t0 + 0.3), (s["id"], "settled", min(t1 - 0.2, t0 + 1.6)), (s["id"], "end", max(t0, t1 - 0.4))]
    tiles = []
    for sid, label, t in marks:
        png = folder / "_tmp.png"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1", "-vf", "scale=480:270", str(png)], check=True)
        if png.exists():
            tiles.append((f"{t:.1f} s · {sid} · {label}", Image.open(png).convert("RGB").copy())); png.unlink()
    files = []
    for i in range(0, len(tiles), 9):
        chunk = tiles[i:i + 9]
        sheet = Image.new("RGB", (3 * 484, ((len(chunk) + 2) // 3) * 300), (17, 17, 17))
        d = ImageDraw.Draw(sheet)
        for k, (lab, im) in enumerate(chunk):
            x, y = (k % 3) * 484, (k // 3) * 300
            sheet.paste(im, (x + 2, y + 2)); d.text((x + 8, y + 276), lab, fill=(255, 255, 255))
        f = folder / f"contact-{i // 9 + 1:02d}.png"; sheet.save(f); files.append(f)
    return files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video"); ap.add_argument("--timeline"); ap.add_argument("--events"); ap.add_argument("--out")
    a = ap.parse_args()
    v = Path(a.video)
    errors, warnings, facts = [], [], []
    info = probe(v)
    vs = next(s for s in info["streams"] if s["codec_type"] == "video")
    au = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    dur = float(info["format"]["duration"])
    num, den = vs["r_frame_rate"].split("/"); fps = float(num) / float(den)
    facts.append(f"Picture: {vs['width']}x{vs['height']} {fps:.0f} fps {vs['codec_name']} {vs.get('pix_fmt')}, {dur:.1f} s ({int(dur // 60)} min {int(dur % 60)} s)")
    if (vs["width"], vs["height"]) != (1920, 1080):
        errors.append("not 1920x1080")
    if abs(fps - 30) > 0.5:
        errors.append(f"{fps:.1f} fps instead of 30")
    if not au:
        errors.append("no audio track")
    pauses = []
    if a.timeline:
        tl = json.loads(Path(a.timeline).read_text(encoding="utf-8"))
        if abs(tl["duration"] - dur) > 1.0:
            errors.append(f"video length {dur:.1f} s differs from the timeline {tl['duration']:.1f} s")
        ls = tl["lines"]
        pauses = [(ls[i]["end"], ls[i + 1]["start"]) for i in range(len(ls) - 1) if ls[i + 1]["start"] - ls[i]["end"] > 3]
    if au:
        lufs, lra, peak, chans, silences = loudness(v)
        facts.append(f"Sound: {lufs:.1f} LUFS, LRA {lra:.1f}, peak {peak:.1f} dBTP, left {chans[0]:.1f} dB / right {chans[1]:.1f} dB")
        if not (-20 <= lufs <= -15):
            errors.append(f"loudness {lufs:.1f} LUFS outside -20..-15")
        if peak > -1.0:
            errors.append(f"true peak {peak:.1f} dBTP above -1")
        if min(chans) < -60 or abs(chans[0] - chans[1]) > 6:
            errors.append("one channel weak or empty")
        for st, d in silences:
            if d > 12 and not any(p0 - 1 <= st <= p1 for p0, p1 in pauses):
                warnings.append(f"{d:.0f} s of silence from {st:.0f} s (not a learner pause)")
    frames = grey_frames(v)
    run, start = 0, 0
    for i in range(1, len(frames)):
        if np.abs(frames[i] - frames[i - 1]).mean() < 0.6:
            run += 1
            continue
        if run >= 25 and not any(p0 - 1 <= start <= p1 for p0, p1 in pauses):
            warnings.append(f"picture stands still for {run} s from {start} s")
        run, start = 0, i
    if run >= 25:
        warnings.append(f"picture stands still for {run} s from {start} s")
    plan = json.loads(Path(a.events).read_text(encoding="utf-8")) if a.events and Path(a.events).is_file() else None
    try:
        sys.path.insert(0, str(HERE))
        from check_motion import find_jumps
        cuts = [s["t0"] for s in plan["slides"]] if plan else []
        n_frames, jumps = find_jumps(str(v))
        real = [(t, d) for t, d in jumps if not any(-0.9 <= t - b <= 0.9 for b in cuts)]
        # long takes: fast-forwards and cuts carry a label on purpose, they are not jumpy scrolls
        ltp = v.parent / "_check" / "long-take.json"
        lt = json.loads(ltp.read_text(encoding="utf-8")) if ltp.is_file() else None
        if lt and lt.get("video") == v.name:
            skip = [x for t in lt["takes"] for x in t.get("skip_jumps", [])]
            n0 = len(real)
            real = [(t, d) for t, d in real if not any(a <= t <= b for a, b in skip)]
            for t in lt["takes"]:
                facts.append(f"Long take {t['slide']} ({t['clip']}): source {t['source_s']} s -> {t['out_s']} s; {t['cuts']} waits cut ({t['cut_s']} s), "
                             f"{len(t['fast'])} fast-forwards (saved {t['fast_saved_s']} s, speeds {', '.join(str(x['speed']) + 'x' for x in t['fast']) or '-'}), "
                             f"held {t['hold_s']} s; {t['zoom']} zoom boxes (max {t['zoom_max']}x, step {t['zoom_step_max_px']} px/frame, jerk {t['zoom_jerk_max_px']} px/frame²); "
                             f"{t['clicks']} clicks, {t['key_labels']} key labels{' (typing hidden)' if t.get('hide_typing') else ''}, {t.get('masks', 0)} masks; "
                             f"fastest action piece {t['action_fastest']}x" + (f"; {n0 - len(real)} jumps inside fast/cut pieces ignored" if n0 != len(real) else ""))
                if t["action_fastest"] > 1.251:
                    errors.append(f"long take {t['slide']}: an action piece runs at {t['action_fastest']}x > 1.25x")
                if t.get("zoom_jerk_max_px", 0) > 20:
                    warnings.append(f"long take {t['slide']}: the zoom jolts (velocity changes {t['zoom_jerk_max_px']} px between frames; raise 'ease' or move the boxes apart)")
                for g in t.get("groups", []):
                    if g.get("short", 0) > 0.3:
                        warnings.append(f"long take {t['slide']} group {g['group']}: the picture is {g['short']} s longer than the narration, its end is cut")
        facts.append(f"Motion: {n_frames} frames, {len(real)} scroll jumps" + (f" at {real[:8]}" if real else ""))
        if real:
            errors.append(f"{len(real)} jumpy scrolls (see the list)")
    except Exception as e:
        warnings.append(f"could not measure scroll jumps: {e}")
    if plan:
        n_ev, n_sl = len(plan.get("events", [])), len(plan.get("slides", []))
        epm, spm = n_ev / dur * 60, n_sl / dur * 60
        facts.append(f"Density: {n_ev} sound effects ({epm:.1f}/min), {n_sl} slides ({spm:.1f}/min), learner pauses: {len(pauses)}")
        if epm > 16:
            warnings.append("too many sound effects (> 16/min)")
        if epm < 4:
            warnings.append("very few sound effects (< 4/min)")
        if spm > 6:
            warnings.append("slides change too fast (> 6/min)")
        if spm < 1:
            warnings.append("slides change too slowly (< 1/min)")
        files = contact_sheets(v, plan["slides"], v.parent / "_check")
        facts.append("Contact sheets: " + ", ".join(f.name for f in files))
    verdict = "PASS" if not errors else "FAIL"
    lines = [f"# Video check: {v.name}", "", f"Verdict: **{verdict}**", ""] + [f"- {x}" for x in facts]
    if errors:
        lines += ["", "Hard failures:"] + [f"- {x}" for x in errors]
    if warnings:
        lines += ["", "Warnings (look and decide):"] + [f"- {x}" for x in warnings]
    txt = "\n".join(lines) + "\n"
    out = Path(a.out) if a.out else v.parent / "_check" / (v.stem + ".report.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(txt, encoding="utf-8")
    print(txt)
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
