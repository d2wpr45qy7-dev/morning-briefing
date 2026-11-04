"""Mix narration over the score with ducking, normalize to -16 LUFS, mux with video; write SRT subtitles.

usage: mix.py VIDEO NARRATION.wav SCORE.wav TIMELINE.json OUT.mp4 OUT.srt
"""
import json, os, re, subprocess, sys
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

SR = 48000


def duck_curve(voice, sr, attack=0.08, release=0.7):
    win = int(0.02 * sr)
    rms = np.sqrt(np.convolve(voice ** 2, np.ones(win) / win, mode="same"))
    active = (rms > 10 ** (-38 / 20)).astype(np.float32)
    out = np.zeros_like(active)
    a, r = 1 - np.exp(-1 / (attack * sr)), 1 - np.exp(-1 / (release * sr))
    v = 0.0
    for i, x in enumerate(active):
        v += (a if x > v else r) * (x - v)
        out[i] = v
    return out


def mix(video, narration, score, out_path, workdir):
    voice, vsr = sf.read(narration, dtype="float32")
    if vsr != SR:
        voice = resample_poly(voice, SR // 1000, vsr // 1000).astype(np.float32)
    music, _ = sf.read(score, dtype="float32")
    n = max(len(voice), len(music))
    voice = np.pad(voice, (0, n - len(voice))); music = np.pad(music, ((0, n - len(music)), (0, 0)))
    dec = 16
    env = np.repeat(duck_curve(voice[::dec], SR // dec), dec)[:n]
    gain = 0.85 - 0.65 * env  # music forward in the pauses, about 14 dB under the voice
    raw = os.path.join(workdir, "mix_raw.wav")
    sf.write(raw, music * gain[:, None] + voice[:, None], SR)
    p = subprocess.run(["ffmpeg", "-hide_banner", "-i", raw, "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = json.loads(p.stderr[p.stderr.rindex("{"):p.stderr.rindex("}") + 1])
    af = (f"loudnorm=I=-16:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
          f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", video, "-i", raw, "-af", af, "-map", "0:v", "-map", "1:a",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest", "-movflags", "+faststart",
                    out_path], check=True)


def srt(timeline, out_path):
    cues = []
    for p in timeline:
        cur = []
        for w, s0, e0 in p["words"]:
            cur.append((w, p["start"] + s0, p["start"] + e0))
            text = " ".join(x[0] for x in cur)
            if (len(text) > 38 and re.search(r"[.,;:?!]$", w)) or len(text) > 52:
                cues.append(cur); cur = []
        if cur:
            cues.append(cur)
    fmt = lambda t: f"{int(t // 3600):02d}:{int(t % 3600 // 60):02d}:{int(t % 60):02d},{int(round(t * 1000)) % 1000:03d}"
    with open(out_path, "w") as f:
        for i, c in enumerate(cues):
            end = c[-1][2] + 0.25
            if i + 1 < len(cues):
                end = min(end, cues[i + 1][0][1] - 0.04)
            f.write(f"{i + 1}\n{fmt(c[0][1])} --> {fmt(end)}\n{' '.join(x[0] for x in c)}\n\n")


if __name__ == "__main__":
    video, narration, score, timeline, out_mp4, out_srt = sys.argv[1:7]
    mix(video, narration, score, out_mp4, os.path.dirname(os.path.abspath(out_mp4)))
    srt(json.load(open(timeline)), out_srt)
    print("mixed", out_mp4)
