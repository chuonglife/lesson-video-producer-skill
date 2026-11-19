#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Composite REAL SCREEN RECORDINGS (how-to, hands-on and software demos) into the rendered slide video.

Usage:
  python composite_clips.py <storyboard.json> <timeline.json> <video.json> <base.mp4> <out.mp4>
  python composite_clips.py --first-frame <clip.mp4> <out.png> [seconds]   # a frame of the clip to put on the slide
  python composite_clips.py --self-test                                    # dry run of the inserted-video sound mix

In video.json, the "clip" of a slide:
  "S07": {"clip": {"file": "clips/S07-chatgpt.mp4", "start": 0, "length": 24, "mode": "frame", "speed": "auto"}}
    file    clip path (relative to the lesson's video folder, or absolute)
    start / length   where to start in the clip and how many seconds to use (no length = to the end)
    mode    "frame": the clip sits inside the slide's frame (clip_frame from the storyboard: the largest rounded box,
            for example the picture frame of a two-column or image slide; or give x, y, w, h);
            "full": the clip covers the whole 1920x1080 picture, the slide only shows while it comes in and goes out
    speed   time factor (1.15 = 15% slower); "auto" stretches 0.8x to 1.25x to fit the slide. Never faster than 1.25x:
            learners cannot follow a sped-up demo.
  A clip shorter than the slide holds its last frame. A clip longer than the slide is cut, with a WARNING: add "hold"
  to that slide or run make_video.py --extend, which adds the hold for you.
The base video's audio (voice, effects, music) is kept; the clip's own audio is dropped. The one exception is a video
inserted into a long take (long_take.py "inserts"): its sound is mixed in, lowered to 0.35 under narration.
The audio always goes through a peak limiter (about -2.5 dBFS) before AAC encoding, so a mixed-in insert cannot push the peak
over the limit; AAC runs with perceptual noise substitution off (it once made a +2.6 dBFS peak out of a limited input).

Timing (clip_window): with a synced storyboard (top-level "sync": 1, plus <name>.events.json next to it) the clip comes in when the
slide's transition has finished. A full-screen clip that covers its slide ("covers_clip": true, the slide picture IS the clip's
first frame) fades in over 0.12 s (nearly instant); the clip goes out gradually INSIDE the transition to the next slide, so the
placeholder slide never shows. Without sync: in = first line of the slide + 0.5 s, out = first line of the next slide - 0.08 s,
0.35 s fades both ends.
Run check_motion.py on every clip first (and smooth_scroll.py if it finds jumps).
"""
import json
import subprocess
import sys
from pathlib import Path

DELAY = 0.5     # the clip appears once the slide transition has nearly finished (old timing, no sync)
FADE = 0.35
COVER_FADE = 0.12     # fade-in of a clip that covers its whole slide (the slide picture is the clip's first frame)
# AAC: perceptual noise substitution off, because on some segments the default encoder pushed the peak +2.6 dBFS even though the input was limited at -2.5
AAC = ["-c:a", "aac", "-b:a", "192k", "-aac_pns", "0"]
LIMITER = "alimiter=limit=0.75:attack=5:release=60:level=false"   # sample peak <= -2.5 dBFS, leaves headroom for AAC (check_video rejects > -1 dBTP)

TRANS_DUR = {"push-left": .68, "fade-up": .6, "iris": .75, "zoom-blur": .7, "diagonal-wipe": .62, "push-up": .62}   # = TRANS_DUR of video.js


def read_sync_events(board_p):
    """<name>.events.json (slide times from render.mjs plan) next to <name>.storyboard.json, or None."""
    p = Path(str(board_p).replace(".storyboard.json", ".events.json"))
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def line_marks(board, tl):
    """The second the PICTURE of each spoken line changes (the group boundaries of a long take).
    Synced storyboard: GROUP_LEAD seconds before the voice starts (the voice starts at "speech_start", falling back to "start"),
    never earlier than 0.2 s before the line's own start. Old storyboard: the start of the line."""
    if board.get("sync"):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from long_take import GROUP_LEAD
        return [max(l["start"] - 0.2, l.get("speech_start", l["start"]) - GROUP_LEAD) for l in tl["lines"]]
    return [l["start"] for l in tl["lines"]]


def clip_window(board, tl, sync, i, c):
    """(second the clip comes in, second it goes out, fade-in seconds, fade-out seconds) of the clip on slide i.
    Shared by the compositing here and by 'long_take.py fit'.
    Synced storyboard (board["sync"] and an events file with one entry per slide): the clip comes in when the slide's transition is
    done; a clip that covers its slide ("covers_clip") fades in over 0.12 s; the clip goes out gradually INSIDE the transition to
    the next slide (the placeholder slide never shows). Old timing: in = first line + DELAY, out = first line of the next slide - 0.08,
    FADE at both ends (the placeholder slide showed for 0.85 s + 0.43 s)."""
    slides = board["slides"]
    starts = [l["start"] for l in tl["lines"]]
    if board.get("sync") and sync and len(sync.get("slides", [])) == len(slides):
        p = sync["slides"][i]
        t_in = p["t0"] + (TRANS_DUR.get(slides[i].get("transition"), .65) if i else 0)
        fade_in = COVER_FADE if slides[i].get("covers_clip") else FADE
        if i + 1 < len(slides):
            tr2 = TRANS_DUR.get(slides[i + 1].get("transition"), .65)
            return t_in, sync["slides"][i + 1]["t0"] + tr2, fade_in, tr2
        return t_in, tl["duration"] - 0.08, fade_in, FADE
    t_in = (0 if i == 0 else starts[slides[i]["from_line"] - 1]) + DELAY
    t_out = (starts[slides[i + 1]["from_line"] - 1] if i + 1 < len(slides) else tl["duration"]) - 0.08
    return t_in, t_out, FADE, FADE


def duration(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def first_frame(clip, out, sec="0.3"):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(sec), "-i", clip, "-frames:v", "1", out], check=True)
    print("wrote", out)


def frame_of(slide, c):
    if all(k in c for k in ("x", "y", "w", "h")):
        return c["x"], c["y"], c["w"], c["h"]
    bb = slide.get("clip_frame") or (max(slide["regions"], key=lambda v: v["bbox"][2] * v["bbox"][3])["bbox"] if slide.get("regions") else None)
    if not bb:
        return 320, 262, 1280, 720
    x, y, w, h = bb
    if w / h > 16 / 9:          # keep 16:9 inside the frame, centred
        w2 = int(h * 16 / 9); x += (w - w2) // 2; w = w2
    else:
        h2 = int(w * 9 / 16); y += (h - h2) // 2; h = h2
    return x, y, w // 2 * 2, h // 2 * 2


def self_test():
    """Dry run of the inserted-video sound mix: build an 8 s base + a clip + a fake insert sound in a temp folder, composite them,
    and ffprobe must find both video and audio in the result. Exit code 1 if the filtergraph is broken."""
    import tempfile
    import long_take
    d = Path(tempfile.mkdtemp(prefix="composite-self-test-"))
    f = lambda *a: subprocess.run(["ffmpeg", "-y", "-v", "error", *a], check=True, cwd=d)
    f("-f", "lavfi", "-i", "color=c=navy:s=1920x1080:r=30:d=8", "-f", "lavfi", "-i", "sine=f=440:d=8", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "base.mp4")
    f("-f", "lavfi", "-i", "color=c=green:s=1920x1080:r=30:d=4", "clip.mp4")
    f("-f", "lavfi", "-i", "sine=f=880:d=3", "insert.wav")
    long_take.render_for_slide = lambda *a: (d / "clip.mp4", {"scenes": [], "groups": [], "insert_audio": [
        {"file": str(d / "insert.wav"), "start": 0, "length": 2.5, "volume": 0.35, "out_from": 0.5}]})
    (d / "t.storyboard.json").write_text(json.dumps({"slides": [{"id": "S01", "from_line": 1, "to_line": 1, "transition": None, "long_take": {"groups": []}}]}))
    (d / "t.timeline.json").write_text(json.dumps({"duration": 8.0, "lines": [{"start": 0.6, "end": 2.0, "text": "x"}]}))
    (d / "video.json").write_text(json.dumps({"S01": {"clip": {"file": "clip.mp4", "long_take": True}}}))
    sys.argv = ["x", str(d / "t.storyboard.json"), str(d / "t.timeline.json"), str(d / "video.json"), str(d / "base.mp4"), str(d / "out.mp4")]
    main()
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(d / "out.mp4")], capture_output=True, text=True)
    ok = "video" in r.stdout and "audio" in r.stdout
    print("SELF-TEST insert sound mix:", "PASS" if ok else "FAIL", d)
    sys.exit(0 if ok else 1)


def main():
    if len(sys.argv) < 2 or (len(sys.argv) < 6 and sys.argv[1] not in ("--first-frame", "--self-test")):
        print(__doc__); sys.exit(0 if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help") else 2)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import preflight
    preflight.need("ffmpeg", "ffprobe")
    if sys.argv[1] == "--self-test":
        self_test(); return
    if sys.argv[1] == "--first-frame":
        first_frame(*sys.argv[2:5]); return
    board_p, tl_p, ov_p, base, out = sys.argv[1:6]
    board = json.loads(Path(board_p).read_text(encoding="utf-8"))
    tl = json.loads(Path(tl_p).read_text(encoding="utf-8"))
    ov = json.loads(Path(ov_p).read_text(encoding="utf-8")) if Path(ov_p).is_file() else {}
    root = Path(ov_p).resolve().parent
    slides = board["slides"]
    clips = [(sid, o["clip"]) for sid, o in ov.items() if isinstance(o, dict) and o.get("clip")]
    if not clips:
        print("no clips in video.json: copying the video, audio through the peak limiter")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", base, "-c:v", "copy", "-af", LIMITER, *AAC, "-movflags", "+faststart", out], check=True)
        return
    inputs, chains, last, errors = ["-i", base], [], "[0:v]", []
    long_takes, insert_audio = [], []    # insert_audio: the sound of video inserts in long takes, mixed under the narration
    sync = read_sync_events(board_p)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    for k, (sid, c) in enumerate(clips):
        i = next(j for j, s in enumerate(slides) if s["id"] == sid)
        t_in, t_out, fade_in, fade_out = clip_window(board, tl, sync, i, c)
        span = t_out - t_in
        f = Path(c["file"]); f = f if f.is_absolute() else root / f
        if not f.is_file():
            errors.append(f"{sid}: clip not found {f}"); continue
        if c.get("long_take"):
            # long take: render the edited clip (waits cut or fast, zoom, clicks, keys, masks) to the narration of each group,
            # then lay it over 1:1
            from long_take import render_for_slide
            f, m = render_for_slide(slides[i], c, root, line_marks(board, tl), t_in, t_out)
            # the placeholder slide shows alone (not the first frame of the clip) from the end of its transition until the clip is clearly
            # visible, and again while the clip fades out; a slide that the clip covers shows nothing of itself
            if slides[i].get("covers_clip"):
                exposed = 0.0
            else:
                slide_t0 = sync["slides"][i]["t0"] if sync and board.get("sync") else t_in - DELAY
                exposed = round(max(0.0, t_in + fade_in * 0.5 - slide_t0), 2)
            m = dict(m, slide=sid, t_in=round(t_in, 3), t_out=round(t_out, 3), slide_exposed_s=exposed,
                     skip_jumps=[[a + t_in, b + t_in] for a, b in m.get("skip_jumps", [])])
            long_takes.append(m)
            insert_audio += [dict(x, out_from=x["out_from"] + t_in) for x in m.get("insert_audio", [])]
            c = {**c, "start": 0, "length": None, "speed": 1.0, "mode": c.get("mode", "full")}
        ss = float(c.get("start", 0))
        length = float(c.get("length") or max(0.1, duration(f) - ss))
        speed = c.get("speed", 1.0)
        if speed == "auto":
            speed = min(1.25, max(0.8, (span - 0.4) / length))
        played = length * speed
        if played > span + 0.2:
            print(f"WARNING {sid}: the clip is {played - span:.1f} s longer than the slide and gets cut (add a hold or use --extend)")
        full = c.get("mode", "frame") == "full"
        x, y, w, h = (0, 0, 1920, 1080) if full else frame_of(slides[i], c)
        inputs += ["-i", str(f)]
        n = k + 1
        chains.append(
            f"[{n}:v]trim=start={ss}:duration={length},setpts=(PTS-STARTPTS)*{speed},fps=30,scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,tpad=stop_mode=clone:stop_duration={max(0, span - played) + 1:.2f},"
            f"trim=duration={span:.3f},format=yuva420p,fade=t=in:st=0:d={fade_in}:alpha=1,fade=t=out:st={max(0, span - fade_out):.3f}:d={fade_out}:alpha=1,"
            f"setpts=PTS+{t_in:.3f}/TB[c{n}]")
        chains.append(f"{last}[c{n}]overlay=x={x}:y={y}:eof_action=pass:enable='between(t,{t_in:.3f},{t_out:.3f})'[v{n}]")
        last = f"[v{n}]"
        print(f"clip {sid}: {t_in:.2f} to {t_out:.2f} s ({'full screen' if full else f'{w}x{h} at {x},{y}'}), {length:.1f} s x {speed:.2f}")
    if errors:
        raise SystemExit("\n".join(errors))
    lt = Path(out).resolve().parent / "_check" / "long-take.json"
    if long_takes:
        lt.parent.mkdir(exist_ok=True)
        lt.write_text(json.dumps({"video": Path(out).name, "takes": long_takes}, ensure_ascii=False, indent=1), encoding="utf-8")
    elif lt.is_file():
        lt.unlink()
    # always through the peak limiter: before, only the copied audio was used, and a real video insert with sound peaked at -0.1 dBTP
    amap, acodec = [], AAC
    if insert_audio:
        mixed = []
        for j, x in enumerate(insert_audio):
            idx = inputs.count("-i"); inputs += ["-i", x["file"]]
            ms = int(round(x["out_from"] * 1000))
            chains.append(f"[{idx}:a]atrim=start={x['start']}:duration={x['length']},asetpts=PTS-STARTPTS,aresample=48000,"
                          f"aformat=channel_layouts=stereo,volume={x['volume']},adelay={ms}|{ms}[ax{j}]")
            mixed.append(f"[ax{j}]")
        # the base audio needs its own label before amix: "[0:a]aformat=...[ax0]amix" is a filtergraph syntax error; the limit comes AFTER the mix
        chains.append(f"[0:a]aformat=channel_layouts=stereo[a0];[a0]{''.join(mixed)}amix=inputs={len(mixed) + 1}:normalize=0:duration=first,{LIMITER}[alim]")
        print(f"mixing the sound of {len(insert_audio)} video inserts")
    else:
        chains.append(f"[0:a]{LIMITER}[alim]")
    amap = ["-map", "[alim]"]
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(chains), "-map", last, *amap,
                    "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", *acodec, "-movflags", "+faststart", out], check=True)
    print("wrote", out)


if __name__ == "__main__":
    main()
