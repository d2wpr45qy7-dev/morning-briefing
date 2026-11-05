#!/usr/bin/env bash
# Save the expensive generated media to GitHub (Git LFS, under media/) so a container reset loses nothing.
# Narration takes hours to voice and the films hours to render; everything else is rebuilt by the pipeline.
#
# usage: tools/persist.sh            copy, commit and push once
#        tools/persist.sh --loop N   repeat every N seconds (run detached with setsid nohup)
#        tools/persist.sh --restore  copy saved narration back into place after a reset
set -u
cd "$(dirname "$0")/.."

restore() {
  for d in media/narration_*; do
    [ -d "$d" ] || continue
    mkdir -p "$(basename "$d")" && cp -n "$d"/* "$(basename "$d")/"
  done
}

sync_once() {
  for d in narration_*; do
    [ -d "$d" ] || continue
    mkdir -p "media/$d"
    cp -u "$d"/p_*.wav "media/$d/" 2>/dev/null
    [ -f "$d/manifest.json" ] && cp -u "$d/manifest.json" "media/$d/"
  done
  for film in reconquista crusades; do
    # the delivery encode (tools/deliver.sh), never the multi-gigabyte render master: LFS caps files at 2 GB
    f="out/$film/${film}_1080p.mp4"
    [ -f "$f" ] && mkdir -p "media/films" && cp -u "$f" "media/films/$film.mp4"
    f="out/$film/$film.srt"
    [ -f "$f" ] && mkdir -p "media/films" && cp -u "$f" "media/films/"
    [ -f "out/$film/credits.md" ] && cp -u "out/$film/credits.md" "media/films/${film}_credits.md"
  done
  git add media
  if ! git diff --cached --quiet -- media; then
    git commit -q -m "Save generated media ($(date -u +%H:%M) UTC)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018fci5MVXnMyjdEescoPnnH" -- media \
      && for i in 1 2 3 4; do git push -q -u origin "$(git branch --show-current)" && break; sleep $((2 ** i)); done
  fi
}

case "${1:-}" in
  --restore) restore ;;
  --loop) while true; do sync_once; sleep "${2:-1800}"; done ;;
  *) sync_once ;;
esac
