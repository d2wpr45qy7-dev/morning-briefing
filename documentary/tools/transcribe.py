"""Transcribe narration with Whisper and attach per-word timings aligned to the script text.

usage: transcribe.py NARRATION_DIR
Adds 'heard', 'words' ([script_word, start, end]) and 'dur' to each manifest entry; prints any paragraph
where Whisper heard noticeably different words, so dropped or garbled narration can be caught.
"""
import json, os, sys
import soundfile as sf
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from textnorm import align_words, norm
from difflib import SequenceMatcher

d = sys.argv[1]
man = json.load(open(os.path.join(d, "manifest.json")))
from faster_whisper import WhisperModel
m = WhisperModel("small.en", device="cpu", compute_type="int8")
total = 0.0
for p in man:
    if p.get("heard_for") != p["wav"]:
        segs, _ = m.transcribe(p["wav"], word_timestamps=True)
        p["heard"] = [dict(w=w.word.strip(), s=w.start, e=w.end) for s in segs for w in s.words]
        p["heard_for"] = p["wav"]
    words = p["text"].replace('"', "").split()
    p["words"] = [[w, s, e] for w, (s, e) in zip(words, align_words(words, p["heard"]))]
    p["dur"] = sf.info(p["wav"]).duration
    total += p["dur"]
    ratio = SequenceMatcher(None, [norm(w) for w in words], [norm(h["w"]) for h in p["heard"]], autojunk=False).ratio()
    flag = "  <-- CHECK" if ratio < 0.9 else ""
    print(f"n{p['n']:02d} {p['dur']:5.1f}s match {ratio:.2f}{flag}")
    if flag:
        print("    heard:", " ".join(h["w"] for h in p["heard"]))
json.dump(man, open(os.path.join(d, "manifest.json"), "w"), indent=1)
print(f"total {total / 60:.1f} min")
