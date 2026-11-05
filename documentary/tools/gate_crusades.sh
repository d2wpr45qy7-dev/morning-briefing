#!/usr/bin/env bash
# Narration done -> transcribe -> render, unless a paragraph matches its script below 0.80 (garbled voicing).
cd "$(dirname "$0")/.."
until grep -q "ALL DONE" narrate_crusades2.log; do sleep 30; done
venv/bin/python tools/transcribe.py narration_crusades > transcribe_crusades.log 2>&1
tools/persist.sh
if grep -E "match 0\.[0-7][0-9]" transcribe_crusades.log; then echo "GATE: garbled paragraph, render held"; exit 1; fi
exec tools/finish.sh crusades
