#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Synthesise the SOUND EFFECTS used by the lesson videos, in code, so they are original and free of third-party rights.

Usage:  python make_sfx.py [out-folder=assets/sfx] [--audition audition.wav]

The set: marimba notes on a pentatonic scale that rotate so reveals never sound the same (ui1-3), bubble pops (pop1-2),
a short click, smooth air swooshes panned left to right (swoosh, whoosh, circle, underline), a transition swoosh with a
three-note sparkle, typing, a two-note ting and a four-note success chime.
Every file: WAV 44.1 kHz stereo, peak about -1 dBFS (mix_audio.py lowers them in the mix).
"""
import sys
import wave
from pathlib import Path

import numpy as np

SR = 44100
RNG = np.random.default_rng(2026)


def t_(d):
    return np.arange(int(d * SR)) / SR


def norm(x, peak=0.9):
    return x / (np.max(np.abs(x)) + 1e-9) * peak


def mono2st(x, pan=0.5):
    return np.stack([x * np.sqrt(1 - pan), x * np.sqrt(pan)], axis=1)


def fade(x, a=0.003, r=0.02):
    n = len(x)
    na, nr = int(a * SR), int(r * SR)
    x = x.copy()
    if na:
        x[:na] *= np.linspace(0, 1, na)
    if nr:
        x[-nr:] *= np.linspace(1, 0, nr)
    return x


def marimba(f, d=0.5):
    t = t_(d)
    s = np.sin(2 * np.pi * f * t) * np.exp(-t * 9)
    s += 0.45 * np.sin(2 * np.pi * f * 4.0 * t) * np.exp(-t * 28)       # the fourth partial dies fast: a wooden tone
    s += 0.12 * np.sin(2 * np.pi * f * 10.0 * t) * np.exp(-t * 60)
    tick = RNG.standard_normal(int(0.006 * SR)) * np.linspace(1, 0, int(0.006 * SR))
    s[:len(tick)] += tick * 0.25
    return fade(s, 0.001, 0.05)


def glass_bell(f, d=1.2):
    t = t_(d)
    idx = 2.2 * np.exp(-t * 5)
    s = np.sin(2 * np.pi * f * t + idx * np.sin(2 * np.pi * f * 3.5 * t)) * np.exp(-t * 3.6)
    s += 0.25 * np.sin(2 * np.pi * f * 2.0 * t) * np.exp(-t * 5)
    return fade(s, 0.001, 0.12)


def bubble_pop(f0=420, f1=1500, d=0.22):
    t = t_(d)
    sweep = f0 + (f1 - f0) * np.minimum(1, t / 0.07) ** 0.6
    ph = 2 * np.pi * np.cumsum(sweep) / SR
    s = np.sin(ph) * np.exp(-t * 22)
    s += 0.2 * np.sin(2 * ph) * np.exp(-t * 40)
    tick = RNG.standard_normal(int(0.004 * SR)) * np.linspace(1, 0, int(0.004 * SR))
    s[:len(tick)] += tick * 0.3
    return fade(s, 0.0008, 0.04)


def click(f=2400, d=0.09):
    t = t_(d)
    n = RNG.standard_normal(len(t)) * np.exp(-t * 180)
    n = n - np.convolve(n, np.ones(40) / 40, mode="same")                 # remove the rumble, keep a crisp attack
    s = n * 0.7 + np.sin(2 * np.pi * f * t) * np.exp(-t * 90) * 0.5 + np.sin(2 * np.pi * 190 * t) * np.exp(-t * 55) * 0.5
    return fade(s, 0.0005, 0.02)


def band_noise(d, fc_fn, bw_fn, amp_fn):
    """A swoosh: white noise through a band-pass whose centre frequency moves (STFT)."""
    n = int(d * SR)
    x = RNG.standard_normal(n + 4096)
    N, H = 2048, 512
    win = np.hanning(N)
    out = np.zeros(n + 4096)
    f = np.fft.rfftfreq(N, 1 / SR)
    for st in range(0, n, H):
        u = st / SR / d
        seg = x[st:st + N]
        if len(seg) < N:
            break
        X = np.fft.rfft(seg * win)
        fc, bw = fc_fn(u), bw_fn(u)
        mask = np.exp(-((np.log(f + 1) - np.log(fc)) / bw) ** 2)
        out[st:st + N] += np.fft.irfft(X * mask, N) * win * amp_fn(u)
    return out[:n]


def swoosh(d=0.5, f0=500, f1=5200, peak_at=0.45, bright=1.0):
    def fc(u):
        return f0 * (f1 / f0) ** (u ** 1.2)
    def amp(u):
        return np.sin(np.pi * min(1, u / peak_at / 2)) ** 1.5 if u < peak_at else np.cos(np.pi / 2 * (u - peak_at) / (1 - peak_at)) ** 2
    s = band_noise(d, fc, lambda u: 0.55 / bright, amp)
    s = norm(fade(s, 0.01, 0.06), 0.9)
    L = np.linspace(1.0, 0.45, len(s)); R = np.linspace(0.45, 1.0, len(s))    # pan from left to right
    return np.stack([s * L, s * R], axis=1)


def seq(parts, gaps):
    """Place mono/stereo parts at given times (seconds) in one stereo file."""
    end = max(int(g * SR) + len(p) for p, g in zip(parts, gaps))
    out = np.zeros((end, 2))
    for p, g in zip(parts, gaps):
        if p.ndim == 1:
            p = mono2st(p)
        s = int(g * SR)
        out[s:s + len(p)] += p
    return out


def save(path, x):
    x = norm(x, 0.89)
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = Path(args[0] if args else Path(__file__).resolve().parent.parent / "assets" / "sfx")
    out.mkdir(parents=True, exist_ok=True)
    nghe = None
    if "--audition" in sys.argv:
        nghe = sys.argv[sys.argv.index("--audition") + 1]
    E5, G5, A5, C6, D6 = 659.26, 783.99, 880.0, 1046.5, 1174.66

    lib = {}
    # reveals: three marimba notes that rotate (pentatonic), light and friendly
    lib["ui1"] = mono2st(marimba(G5, 0.45), 0.42)
    lib["ui2"] = mono2st(marimba(A5, 0.45), 0.5)
    lib["ui3"] = mono2st(marimba(C6, 0.45), 0.58)
    # pops: bubble pops at two pitches
    lib["pop1"] = mono2st(bubble_pop(420, 1500), 0.45)
    lib["pop2"] = mono2st(bubble_pop(520, 1900), 0.55)
    # a short click
    lib["click"] = mono2st(click(), 0.5)
    # smooth swoosh, longer whoosh, a circle with momentum, a quick underline
    lib["swoosh"] = swoosh(0.42, 700, 4200, 0.5)
    lib["circle"] = swoosh(0.6, 500, 6000, 0.55, 1.1)
    lib["underline"] = swoosh(0.28, 1500, 7000, 0.4, 1.2)
    lib["whoosh"] = swoosh(0.9, 300, 3200, 0.5, 0.8)
    # slide transition: a long swoosh with a rising three-note sparkle
    spark = [glass_bell(f, 0.8) * 0.5 for f in (C6 * 1.5, D6 * 1.5, G5 * 3)]
    lib["transition"] = seq([swoosh(0.75, 350, 4800, 0.5, 0.9)] + [mono2st(s, 0.5 + 0.1 * i) for i, s in enumerate(spark)], [0, 0.34, 0.41, 0.48])
    # typing: random key taps with a natural rhythm
    ticks, ts, tt = [], [], 0.0
    for i in range(13):
        ticks.append(mono2st(click(RNG.uniform(1700, 3200), 0.07) * RNG.uniform(0.55, 1.0), RNG.uniform(0.35, 0.65)))
        ts.append(tt)
        tt += RNG.uniform(0.05, 0.12) + (0.09 if i % 5 == 4 else 0)
    lib["typing"] = seq(ticks, ts)
    # a two-note ting and a four-note success chime
    lib["ting"] = seq([mono2st(glass_bell(E5 * 2, 1.4), 0.45), mono2st(glass_bell(E5 * 3, 1.6), 0.55)], [0, 0.11])
    lib["success"] = seq([mono2st(glass_bell(f, 1.5), 0.5) for f in (C6, E5 * 2, G5 * 2, C6 * 2)], [0, 0.1, 0.2, 0.3])
    for k, v in lib.items():
        save(out / f"{k}.wav", v)
        print(f"{k}.wav  {len(v) / SR:.2f}s")
    if nghe:
        order = ["ui1", "ui2", "ui3", "pop1", "pop2", "click", "swoosh", "circle", "underline", "whoosh", "transition", "typing", "ting", "success"]
        parts = [lib[k] for k in order]
        gaps, t = [], 0.0
        for p in parts:
            gaps.append(t)
            t += len(p) / SR + 0.55
        save(Path(nghe), seq(parts, gaps))
        print("wrote", nghe)


if __name__ == "__main__":
    main()
