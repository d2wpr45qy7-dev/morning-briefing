"""Make the synthetic reference voice Chatterbox is conditioned on (a Kokoro voice, not a real person)."""
import os, sys
import soundfile as sf
from kokoro_onnx import Kokoro

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF_TEXT = ("The river runs slowly here, past the old walls and the orchards. For a thousand years, travelers have stopped at this "
            "crossing to rest. Some came as pilgrims. Others came as soldiers. Very few of them left any record of what they saw.")

if __name__ == "__main__":
    voice = sys.argv[1] if len(sys.argv) > 1 else "bm_george"
    k = Kokoro(os.path.join(HERE, "models/kokoro-v1.0.onnx"), os.path.join(HERE, "models/voices-v1.0.bin"))
    a, sr = k.create(REF_TEXT, voice=voice, speed=0.88, lang="en-us" if voice.startswith("a") else "en-gb")
    out = os.path.join(HERE, "voice", f"ref_{voice}.wav")
    sf.write(out, a, sr)
    print(out, round(len(a) / sr, 1), "s")
