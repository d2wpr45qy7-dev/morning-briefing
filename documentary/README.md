# Documentary pipeline (The Reconquista, The Crusades)

Archival documentary films built entirely from public-domain and openly licensed sources, narrated by an
open-source voice, with an original synthesized score. This folder holds everything needed to rebuild them in
a fresh container; media, models and virtual environments are not committed and are regenerated.

## Look and voice (approved by the user from the pilot)

- Calm third-person documentary narration. No Matt Walsh-style rhetoric or delivery.
- Voice: Chatterbox TTS conditioned on `voice/ref_bm_george.wav`, a synthetic Kokoro voice (`tools/make_ref.py`,
  voice `bm_george`, speed 0.88). Exaggeration 0.35 (0.5 for quoted documents), cfg 0.3. No real person's voice.
- Pictures: Library of Congress photochroms and stereographs, Cleveland Museum of Art CC0 objects, 19th-century
  book engravings and W. W. Collins watercolours (Project Gutenberg / Internet Archive), real CC BY-SA footage,
  animated Natural Earth maps, and printed primary sources shown on screen with the quoted lines highlighted
  from the scans' own word positions while the English translation appears word by word.
- Finish: depth-parallax camera moves, crossfades, warm grade, vignette, grain; lower thirds identify every image.
- Wikimedia Commons is not used: it refuses file downloads from these containers under its robot policy.

## Rebuild from scratch

```bash
cd documentary
python3 -m venv venv && venv/bin/pip install torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cpu
venv/bin/pip install chatterbox-tts && venv/bin/pip install "numpy<2" opencv-python-headless==4.10.0.84 pillow scipy soundfile faster-whisper
python3 -m venv venv_kokoro && venv_kokoro/bin/pip install kokoro-onnx==0.6.1 soundfile && venv_kokoro/bin/pip uninstall -y phonemizer && venv_kokoro/bin/pip install phonemizer-fork
mkdir -p /home/runner/work/espeakng-loader/espeakng-loader/espeak-ng/_dynamic/share
ln -sfn $PWD/venv_kokoro/lib/python3.11/site-packages/espeakng_loader/espeak-ng-data /home/runner/work/espeakng-loader/espeakng-loader/espeak-ng/_dynamic/share/espeak-ng-data
mkdir -p models && curl -L -o models/kokoro-v1.0.onnx https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx \
  && curl -L -o models/voices-v1.0.bin https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin

venv_kokoro/bin/python tools/make_ref.py bm_george                     # reference voice
venv/bin/python tools/fetch.py assets_reconquista.json                 # all pictures, footage, documents, map data
setsid nohup venv/bin/python tools/narrate.py reconquista_doc_script.md narration_reconquista voice/ref_bm_george.wav > narrate_reconquista.log 2>&1 &
venv/bin/python tools/transcribe.py narration_reconquista              # word timings; flags garbled paragraphs
venv/bin/python tools/reconquista_edl.py --audio-only                  # timeline, narration track, music cues
venv/bin/python tools/music.py "$(jq .total out/reconquista/cues.json)" <(jq .cues out/reconquista/cues.json) out/reconquista/score.wav
venv/bin/python tools/reconquista_edl.py                               # renders out/reconquista/video.mp4
venv/bin/python tools/mix.py out/reconquista/video.mp4 out/reconquista/narration.wav out/reconquista/score.wav \
  out/reconquista/timeline.json out/reconquista/reconquista.mp4 out/reconquista/reconquista.srt
```

After a container reset, run `git lfs pull && tools/persist.sh --restore` before narrating, so the voiced paragraphs
already saved are reused instead of re-voiced.

## Where everything is kept

Everything lives on GitHub, in `d2wpr45qy7-dev/morning-briefing`, branch `documentary`. Code, scripts and asset lists
are ordinary git files. The narration takes and the finished films (`media/films/`: mp4, srt, credits) are stored
with Git LFS under `media/`. `tools/persist.sh --loop 1800` copies new media there and pushes every half hour while
work runs. To put a copy on a local drive: `git clone -b documentary https://github.com/d2wpr45qy7-dev/morning-briefing`
into a folder on the drive (Git LFS installed), or download a single film from the GitHub web page.

Narration and rendering take hours on 4 CPU cores; run them detached (`setsid nohup`) because the tool runner
stops background jobs after two hours. Narration is cached per paragraph by text, so script edits only re-voice
what changed. Never use `pkill -f` with a pattern that also appears in your own command line.

## Files

- `reconquista_doc_script.md`: narration script; `## ` headings start chapters; paragraphs starting with `"` are
  quoted documents.
- `assets_reconquista.json`: every source with kind, id, local file and credit; `tools/fetch.py` downloads them.
- `tools/reconquista_edl.py`: the edit; every cut is anchored to a narration word with `at(paragraph, word)`.
- `tools/render.py`, `tools/maps.py`, `tools/music.py`, `tools/mix.py`: renderer, maps, score, mix and subtitles.
- `tools/ia_find.py`: finds a phrase in an Internet Archive scan and returns its page and word boxes.

## Facts still to verify before publishing

Cidi Yahya al-Nayyar's conversion and the Granada Venegas title; the Nasrid princes' baptismal names; Muley
al-Shaykh's 1593 baptism at the Escorial; Alonso del Castillo and Miguel de Luna's roles; Dadson's Villarrubia
findings; Talavera's converso descent and his 1505-07 Inquisition case; Teresa's grandfather; the 1264 mudéjar
expulsions; Almanzor sparing the apostle's tomb; the purity-statute details (Silíceo 1547, Jesuits 1593, Olivares);
the share of al-Andalus Muslim by about 1000; the 1605 plot. The quoted 754, 1492 and 1609 texts are transcribed
from the scans shown on screen and translated by Claude.
