#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Mix the THREE-LAYER SOUNDTRACK of a lesson: narration + sound effects locked to the on-screen actions + a piano bed
that ducks under the voice.

Usage:
  python mix_audio.py <voice.mp3> <events.json> <out.mp3> [--music <file>] [--no-music] [--no-sfx] [--music-db -22]

events.json comes from `render.mjs plan` (events: [{t, sound, what}], duration). Sounds: assets/sfx/*.wav, original
sounds synthesised by scripts/make_sfx.py (no third-party rights). Music: assets/music/piano-bed.mp3, synthesised by
scripts/make_music.py: 17 to 23 dB under the voice, sidechain-ducked by the narration, 2.5 s fade in, 3.5 s fade out.

Density: any two sounds at least 0.22 s apart, the same sound at least 0.35 s apart (transitions, ting and success are
exempt); ui and pop rotate through their variants so they never sound repetitive. Peaks around -19 to -23 dBFS under
the voice. Output is loudness-normalised to -18 LUFS (the final mux normalises to -16).
Writes <out>.sfx.json listing which sound plays when.
"""
import argparse
import json
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
ASSETS = Path(__file__).resolve().parent.parent / "assets"
SR = 44100
# name -> (file, gain dB, max seconds)
SFX = {
    "ui1": ("ui1.wav", -21, 0.5), "ui2": ("ui2.wav", -21, 0.5), "ui3": ("ui3.wav", -21, 0.5),
    "pop1": ("pop1.wav", -22, 0.3), "pop2": ("pop2.wav", -22, 0.3), "click": ("click.wav", -21, 0.2),
    "swoosh": ("swoosh.wav", -22, 0.6), "circle": ("circle.wav", -21, 0.7), "underline": ("underline.wav", -22, 0.4),
    "whoosh": ("whoosh.wav", -22, 1.0), "transition": ("transition.wav", -19, 1.4), "typing": ("typing.wav", -23, 1.4),
    "ting": ("ting.wav", -20, 1.6), "success": ("success.wav", -20, 1.9),
}
VARIANTS = {"ui": ["ui1", "ui2", "ui3"], "pop": ["pop1", "pop2"]}
NEVER_THINNED = ("transition", "ting", "success")


def load_sfx(name):
    f, gain, longest = SFX[name]
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(ASSETS / "sfx" / f), "-t", str(longest), "-ac", "2", "-ar", str(SR),
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    x = np.frombuffer(raw, dtype="<f4").reshape(-1, 2).copy()
    k = int(0.008 * SR)   # 8 ms fades against clicks
    if len(x) > 2 * k:
        x[:k] *= np.linspace(0, 1, k)[:, None]
        x[-k:] *= np.linspace(1, 0, k)[:, None]
    return x * 10 ** (gain / 20)


def thin(events):
    events = sorted(events, key=lambda e: e["t"])
    out, last_any, last_of = [], -9, {}
    for e in events:
        s = e["sound"]
        if s not in NEVER_THINNED and (e["t"] - last_any < 0.22 or e["t"] - last_of.get(s, -9) < 0.35):
            continue
        out.append(e); last_any = e["t"]; last_of[s] = e["t"]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("voice"); ap.add_argument("events"); ap.add_argument("out")
    ap.add_argument("--music", default=str(ASSETS / "music" / "piano-bed.mp3"))
    ap.add_argument("--no-music", action="store_true")
    ap.add_argument("--no-sfx", action="store_true")
    ap.add_argument("--music-db", type=float, default=-22)
    a = ap.parse_args()
    plan = json.loads(Path(a.events).read_text(encoding="utf-8"))
    dur = float(plan["duration"])
    n = int((dur + 0.5) * SR)
    track = np.zeros((n, 2), dtype=np.float32)
    kept = [] if a.no_sfx else thin(plan.get("events", []))
    cache, turn, log = {}, {}, []
    for e in kept:
        s = e["sound"]
        if s in VARIANTS:
            turn[s] = turn.get(s, -1) + 1
            s = VARIANTS[s][turn[s] % len(VARIANTS[s])]
        if s not in SFX:
            print("unknown sound, skipped:", s); continue
        if s not in cache:
            cache[s] = load_sfx(s)
        x = cache[s]
        i0 = max(0, int(e["t"] * SR)); i1 = min(n, i0 + len(x))
        if i0 < n:
            track[i0:i1] += x[: i1 - i0]
        log.append({"t": round(e["t"], 2), "sound": s, "what": e.get("what", "")})
    out = Path(a.out)
    tmp = out.with_suffix(".sfx.tmp.wav")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes((np.clip(track, -1, 1) * 32767).astype("<i2").tobytes())
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", a.voice, "-i", str(tmp)]
    if a.no_music or not Path(a.music).is_file():
        if not a.no_music:
            print("music not found:", a.music, "- mixing without music")
        fc = (f"[0:a]aformat=sample_rates={SR}:channel_layouts=stereo,apad=whole_dur={dur + 0.5}[v];"
              f"[1:a]aformat=sample_rates={SR}:channel_layouts=stereo[f];"
              "[v][f]amix=inputs=2:normalize=0:duration=first[m];[m]loudnorm=I=-18:TP=-2:LRA=9[o]")
    else:
        cmd += ["-stream_loop", "-1", "-i", a.music]
        fc = (f"[0:a]aformat=sample_rates={SR}:channel_layouts=stereo,apad=whole_dur={dur + 0.5},asplit=2[v][vs];"
              f"[1:a]aformat=sample_rates={SR}:channel_layouts=stereo[f];"
              f"[2:a]aformat=sample_rates={SR}:channel_layouts=stereo,atrim=0:{dur + 0.5},volume={a.music_db}dB,"
              f"afade=t=in:st=0:d=2.5,afade=t=out:st={max(0, dur - 3):.2f}:d=3.5[mu];"
              "[mu][vs]sidechaincompress=threshold=0.03:ratio=4:attack=40:release=700:makeup=1[md];"
              "[v][f][md]amix=inputs=3:normalize=0:duration=first[m];[m]loudnorm=I=-18:TP=-2:LRA=9[o]")
    cmd += ["-filter_complex", fc, "-map", "[o]", "-t", f"{dur + 0.5:.3f}", "-ar", str(SR), "-b:a", "192k", str(out)]
    subprocess.run(cmd, check=True)
    tmp.unlink()
    Path(str(out) + ".sfx.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{out.name}: {len(log)} sound effects ({len(plan.get('events', [])) - len(kept)} thinned out), music "
          f"{'off' if a.no_music else Path(a.music).name + f' ({a.music_db} dB)'}, {dur:.1f} s")


if __name__ == "__main__":
    main()
