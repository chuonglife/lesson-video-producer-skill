#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Synthesise the PIANO BED (background music) in code: original, so there are no third-party rights.

Usage:  python make_music.py <out.wav> [--seconds 240] [--bpm 66] [--seed 1]
        then, to keep the repository small: ffmpeg -i out.wav -b:a 192k assets/music/piano-bed.mp3

How it stays natural:
  - The instrument: slightly inharmonic partials like a real string, two detuned strings for warmth, a short hammer
    thump, long low notes and quick high ones.
  - The playing: left hand root and fifth, right hand gentle arpeggios, a sparse pentatonic melody from the second section.
  - The human touch: timing off by a few tens of milliseconds, varying velocity, the odd skipped note, a slight slowdown
    at the end of each phrase.
  - Harmony: Cmaj7, Am7, Fmaj7, G6, soft and unresolved; no sustained organ pads (they sound like church music under a
    voice). A different --seed gives each course its own bed.
"""
import argparse
import wave

import numpy as np

SR=44100
def note_hz(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)

def reverb(x, seconds=2.6, sr=SR, wet=0.28, seed=7):
    rng = np.random.default_rng(seed)
    n = int(seconds * sr)
    ir = rng.standard_normal(n) * np.exp(-np.arange(n) / sr * 2.6)
    ir[: int(0.02 * sr)] *= np.linspace(0, 1, int(0.02 * sr))
    # darken the reverb tail with a rough moving-average low-pass
    k = 24
    ir = np.convolve(ir, np.ones(k) / k, mode="same")
    N = 1 << int(np.ceil(np.log2(len(x) + len(ir))))
    y = np.fft.irfft(np.fft.rfft(x, N) * np.fft.rfft(ir, N), N)[: len(x)]
    y *= np.max(np.abs(x)) / (np.max(np.abs(y)) + 1e-9)
    return (1 - wet) * x + wet * y

def piano(m, vel, dur, rng):
    """One piano note (MIDI m, velocity 0..1, dur seconds)."""
    f0 = note_hz(m)
    n = int(dur * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)
    B = 0.00035 * (1 + (m - 40) / 40)
    ham = 6 + int(vel * 6)
    for k in range(1, ham + 1):
        fk = k * f0 * np.sqrt(1 + B * k * k)
        if fk > 9000:
            break
        a = (1.0 / k ** 1.15) * (vel ** (0.5 + 0.12 * k))
        dec = (0.55 + (m - 36) * 0.045) * (1 + 0.55 * (k - 1))
        for det, w in ((0.0, 1.0), (rng.uniform(0.4, 1.2), 0.8)):
            out += w * a * np.sin(2 * np.pi * (fk + det * k * 0.15) * t + rng.uniform(0, 6.28)) * np.exp(-t * dec)
    # hammer: a short, dark thump
    h = int(0.012 * SR)
    ns = rng.standard_normal(h) * np.linspace(1, 0, h) ** 2
    ns = np.convolve(ns, np.ones(14) / 14, mode="same")
    out[:h] += ns * 0.35 * vel
    att = min(int(0.004 * SR), n)
    out[:att] *= np.linspace(0, 1, att)
    rel = min(int(0.25 * SR), n)
    out[-rel:] *= np.linspace(1, 0, rel)
    return out / 6.0

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", help="output .wav")
    ap.add_argument("--seconds", type=float, default=240)
    ap.add_argument("--bpm", type=float, default=66)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    rng = np.random.default_rng(a.seed)
    beat = 60.0 / a.bpm
    n = int((a.seconds + 6) * SR)
    mix = np.zeros(n)

    def place(m, t, vel, dur):
        s = int(max(0, t) * SR)
        x = piano(m, vel, dur, rng)
        e = min(n, s + len(x))
        if s < n:
            mix[s:e] += x[: e - s]

    # chords: (bass note, [right-hand notes low -> high])
    CH = [(36, [55, 59, 64, 67, 71]),   # Cmaj7
          (33, [57, 60, 64, 67, 72]),   # Am7
          (29, [57, 60, 65, 69, 72]),   # Fmaj7
          (31, [55, 59, 62, 64, 69])]   # G6
    penta = [72, 74, 76, 79, 81, 84]    # C D E G A C

    t = 1.0
    bar = 0
    mel = 3
    while t < a.seconds + 2:
        b, rh = CH[bar % 4]
        section = bar // 4  # section 0, 1, 2... to vary the pattern
        slow = 1.0 + (0.06 if bar % 4 == 3 else 0.0)  # a slight ritardando at the end of each phrase
        bl = 4 * beat * slow
        # left hand
        place(b, t + rng.normal(0, 0.012), rng.uniform(0.34, 0.44), 4.5)
        place(b + 7, t + 2 * beat * slow + rng.normal(0, 0.012), rng.uniform(0.22, 0.32), 3.2)
        # right hand: eight-note arpeggio, a few notes skipped
        pattern = [0, 2, 3, 2, 1, 2, 3, 4] if section % 2 == 0 else [0, 1, 2, 3, 2, 1, 2, 4]
        for q, ix in enumerate(pattern):
            if rng.random() < 0.12 and q not in (0,):
                continue
            tq = t + q * (beat / 2) * slow + rng.normal(0, 0.014)
            vel = (0.26 if q % 2 == 0 else 0.20) + rng.uniform(-0.04, 0.05)
            place(rh[ix], tq, max(0.1, vel), 2.6)
        # a sparse melody from the second section on
        if section >= 1 and rng.random() < 0.8:
            for off in sorted(rng.choice([0, 1, 1.5, 2, 3, 3.5], size=rng.integers(1, 3), replace=False)):
                mel = int(np.clip(mel + rng.integers(-2, 3), 0, len(penta) - 1))
                place(penta[mel], t + off * beat * slow + rng.normal(0, 0.02), rng.uniform(0.34, 0.5), 3.4)
        t += bl
        bar += 1

    mix = reverb(mix, seconds=2.8, wet=0.32)
    # remove low rumble, soften peaks
    mix = mix - np.convolve(mix, np.ones(1200) / 1200, mode="same") * 0.7
    mix = np.tanh(mix / (np.max(np.abs(mix)) * 0.55)) * 0.8
    # normalise to about -17 dB RMS
    rms = np.sqrt(np.mean(mix ** 2))
    mix *= 10 ** (-17 / 20) / rms
    mix = np.tanh(mix * 1.1) / 1.1
    mix = mix[: int(a.seconds * SR)]
    f = int(3.0 * SR)
    mix[:f] *= np.linspace(0, 1, f)
    mix[-f:] *= np.linspace(1, 0, f)
    R = np.roll(mix, int(0.011 * SR))
    st = np.stack([mix, R], axis=1)
    pcm = (np.clip(st, -1, 1) * 32767).astype("<i2")
    with wave.open(a.out, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
    print(f"wrote {a.out}: {a.seconds:.0f} s, piano, {a.bpm} bpm, seed {a.seed}")


if __name__ == "__main__":
    main()
