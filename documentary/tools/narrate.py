"""Narrate a documentary script with Chatterbox, one file per paragraph, cached by content.

usage: narrate.py SCRIPT.md OUTDIR REF.wav
"""
import hashlib, json, os, re, sys
import numpy as np, torch, torchaudio as ta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from textnorm import speakable, parse_script

torch.set_num_threads(4)
EXAG, CFG, GAP = 0.35, 0.3, 0.32


def chunks(p, limit=38):
    out, cur = [], ""
    for s in re.split(r"(?<=[.!?])\s+", p):
        if cur and len((cur + " " + s).split()) > limit:
            out.append(cur); cur = s
        else:
            cur = (cur + " " + s).strip()
    if cur:
        out.append(cur)
    return out


def main(script, outdir, ref):
    os.makedirs(outdir, exist_ok=True)
    paras = parse_script(script)
    model = None
    manifest = []
    for n, (section, p) in enumerate(paras, 1):
        quote = p.startswith('"')
        spoken = speakable(p)
        key = hashlib.md5(f"{spoken}|{os.path.basename(ref)}|{EXAG}|{CFG}|{quote}".encode()).hexdigest()[:8]
        path = os.path.abspath(os.path.join(outdir, f"n{n:02d}_{key}.wav"))
        if not os.path.exists(path):
            if model is None:
                from chatterbox.tts import ChatterboxTTS
                model = ChatterboxTTS.from_pretrained(device="cpu")
            pieces = []
            for i, c in enumerate(chunks(spoken)):
                torch.manual_seed(1000 * n + i)
                w = model.generate(c, audio_prompt_path=ref, exaggeration=0.5 if quote else EXAG, cfg_weight=CFG)
                pieces.append(w.squeeze(0).numpy())
                pieces.append(np.zeros(int(GAP * model.sr), dtype=np.float32))
            ta.save(path, torch.from_numpy(np.concatenate(pieces[:-1])).unsqueeze(0), model.sr)
            print("para", n, "done", flush=True)
        manifest.append(dict(n=n, section=section, text=p, wav=path, quote=quote))
        json.dump(manifest, open(os.path.join(outdir, "manifest.json"), "w"), indent=1)
    print("ALL DONE", flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:4])
