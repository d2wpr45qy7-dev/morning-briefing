#!/usr/bin/env bash
# Score, render, mix and save one film after its narration is transcribed.  usage: tools/finish.sh reconquista|crusades
set -eu
cd "$(dirname "$0")/.."
F=$1; O=out/$F
venv/bin/python tools/${F}_edl.py --audio-only
venv/bin/python -c "import json; c = json.load(open('$O/cues.json')); json.dump(c['cues'], open('$O/cues_only.json', 'w')); print(c['total'])" > $O/total.txt
venv/bin/python tools/music.py "$(cat $O/total.txt)" $O/cues_only.json $O/score.wav
echo "score done $(date -u +%H:%M)"
venv/bin/python tools/${F}_edl.py
echo "video done $(date -u +%H:%M)"
venv/bin/python tools/mix.py $O/video.mp4 $O/narration.wav $O/score.wav $O/timeline.json $O/$F.mp4 $O/$F.srt
venv/bin/python -c "
import json, sys; sys.path.insert(0, 'tools')
from fetch import credits_md
from credits_roll import used_assets
used = used_assets('tools/${F}_edl.py')
entries = [e for e in json.load(open('assets_$F.json')) if e['file'] in used]
credits_md(entries, '$O/credits.md', 'The ${F^}')"
echo "FILM DONE $(date -u +%H:%M)"
tools/persist.sh
