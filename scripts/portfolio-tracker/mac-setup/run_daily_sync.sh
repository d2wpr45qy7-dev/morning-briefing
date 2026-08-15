#!/bin/bash
# Wrapper invoked by launchd. Activates the venv, loads Schwab creds, runs the sync.
set -e
BASE="$HOME/Claude/schwab-portfolio-sync"
source "$BASE/venv/bin/activate"
cd "$BASE/morning-briefing"
python3 scripts/portfolio-tracker/daily_sync.py --repo "$BASE/morning-briefing"
