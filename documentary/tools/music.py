"""Original score, synthesized: Andalusian-cadence string pad, drone, plucked motif, frame drum, convolution reverb.

usage: music.py TOTAL_SECONDS CUES_JSON OUT.wav
cues: {name: [t0, t1]} with names intro, title, conquest, lament, closing (any may repeat with a suffix, e.g. conquest2).
"""
import json, sys
import numpy as np
from scipy.signal import butter, sosfilt, fftconvolve, lfilter
import soundfile as sf

SR = 48000
NOTE = {n: i for i, n in enumerate(["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"])}


def hz(name):
    return 440.0 * 2 ** ((NOTE[name[:-1]] - 9) / 12 + (int(name[-1]) - 4))


def env(n, a, r):
    e = np.ones(n, np.float32)
    ai, ri = int(a * SR), int(r * SR)
    if ai: e[:ai] = np.linspace(0, 1, ai) ** 2
    if ri: e[-ri:] *= np.linspace(1, 0, ri) ** 1.5
    return e


def lowpass(x, fc, order=2):
    return sosfilt(butter(order, fc, fs=SR, output="sos"), x)


def saw_pad(freq, dur, rng, detune=0.006, voices=5, bright=1400):
    n = int(dur * SR); t = np.arange(n) / SR
    out = np.zeros(n, np.float32)
    for v in range(voices):
        f = freq * (1 + detune * (v - voices // 2) / (voices // 2 or 1))
        out += (2 * ((t * f + rng.random()) % 1.0) - 1).astype(np.float32)
    lfo = 1 + 0.15 * np.sin(2 * np.pi * 0.11 * t + rng.random() * 6)
    return lowpass(out / voices * lfo, bright).astype(np.float32)


def pluck(freq, dur, rng, damp=0.996):
    """Karplus-Strong string, vectorized as a feedback comb with a two-tap averaging loop filter."""
    n = int(dur * SR); p = int(SR / freq)
    x = np.zeros(n, np.float32); x[:p] = rng.uniform(-1, 1, p)
    a = np.zeros(p + 2); a[0] = 1; a[p] = -damp * 0.5; a[p + 1] = -damp * 0.5
    out = lfilter([1.0], a, x).astype(np.float32)
    return lowpass(out, 3500) * env(n, 0.002, 0.3)


def drum(dur, rng, f0=70):
    n = int(dur * SR); t = np.arange(n) / SR
    body = np.sin(2 * np.pi * (f0 * t + 25 * (1 - np.exp(-t * 18)) / 18)) * np.exp(-t * 7)
    skin = lowpass(rng.normal(0, 1, n), 900) * np.exp(-t * 30) * 0.4
    return (body + skin).astype(np.float32)


def reverb(x, seconds=3.2, mix=0.32, seed=1):
    rng = np.random.default_rng(seed)
    n = int(seconds * SR); t = np.arange(n) / SR
    out = []
    for ch in range(2):
        ir = lowpass(rng.normal(0, 1, n) * np.exp(-t * 6.5 / seconds), 5000); ir[:int(0.02 * SR)] = 0
        ir /= np.sqrt((ir ** 2).sum())
        out.append((1 - mix) * x + mix * fftconvolve(x, ir)[:len(x)] * 1.4)
    return np.stack(out, 1).astype(np.float32)


PROG = [["A2", "E3", "A3", "C4"], ["G2", "D3", "G3", "B3"], ["F2", "C3", "F3", "A3"], ["E2", "B2", "E3", "G#3"]]
MOTIF = ["E4", "F4", "G#4", "A4", "G#4", "F4", "E4", "D4", "E4"]


def score(total, cues, seed=7):
    rng = np.random.default_rng(seed)
    n = int(total * SR) + SR
    pad = np.zeros(n, np.float32); pl = np.zeros(n, np.float32); dr = np.zeros(n, np.float32)
    chord_len, t, k = 4.0, 0.0, 0
    while t < total:
        seg = sum(saw_pad(hz(nm), chord_len + 2.5, rng) * 0.22 for nm in PROG[k % 4])
        seg = seg * env(len(seg), 1.6, 2.4)
        i0 = int(t * SR); pad[i0:i0 + len(seg)] += seg[:max(0, n - i0)]
        t += chord_len; k += 1
    tt = np.arange(n) / SR
    drone = (np.sin(2 * np.pi * hz("A1") * tt) * 0.5 + np.sin(2 * np.pi * hz("E2") * tt) * 0.25 +
             lowpass(saw_pad(hz("A1"), total + 1, rng, voices=3, bright=300)[:n], 300) * 0.4).astype(np.float32)

    def window(prefix, fade=2.5):
        w = np.zeros(n, np.float32)
        for name, (a, b) in cues.items():
            if name.startswith(prefix):
                w[int(a * SR):int(b * SR)] = 1
        k = int(fade * SR)
        return np.convolve(w, np.ones(k) / k, mode="same").astype(np.float32)

    for prefix, every in (("intro", 8.0), ("lament", 6.0), ("closing", 8.0)):
        for name, (a, b) in cues.items():
            if not name.startswith(prefix):
                continue
            t = a + 1.0
            while t < b - 2:
                for j, nm in enumerate(MOTIF[: rng.integers(4, len(MOTIF) + 1)]):
                    s = pluck(hz(nm), 2.5, rng) * (0.35 if j else 0.45)
                    i0 = int((t + j * 0.42 + rng.uniform(-0.02, 0.02)) * SR)
                    pl[i0:i0 + len(s)] += s[:max(0, n - i0)]
                t += every
    beat = 60 / 72
    for name, (a, b) in cues.items():
        if not name.startswith("conquest"):
            continue
        t = a
        while t < b:
            for off, amp in ((0, 0.9), (beat * 1.5, 0.45), (beat * 2, 0.7)):
                s = drum(1.2, rng) * amp
                i0 = int((t + off) * SR); dr[i0:i0 + len(s)] += s[:max(0, n - i0)]
            t += beat * 4
    padw = 0.55 + 0.45 * window("title") - 0.35 * window("lament")
    mix = pad * padw + drone * (0.18 + 0.25 * window("conquest") + 0.15 * window("lament")) + pl * 0.8 + dr * 0.55 * window("conquest", 1.0)
    mix *= 1 + 0.6 * window("title", 3.0)
    fade = np.ones(n, np.float32)
    fi, fo, end = int(2.0 * SR), int(5.0 * SR), int(total * SR)
    fade[:fi] = np.linspace(0, 1, fi); fade[end - fo:end] = np.linspace(1, 0, fo); fade[end:] = 0
    st = reverb(mix * fade)
    st /= np.abs(st).max() + 1e-9
    return st[:end] * 0.8


if __name__ == "__main__":
    total = float(sys.argv[1]); cues = json.loads(open(sys.argv[2]).read()); out = sys.argv[3]
    sf.write(out, score(total, cues), SR)
    print("wrote", out)
