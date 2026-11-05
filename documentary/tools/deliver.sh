#!/usr/bin/env bash
# Delivery copy of a finished film: two-pass 1080p H.264 sized to stay under Git LFS's 2 GB file limit, then saved.
# usage: tools/deliver.sh reconquista|crusades   (needs out/FILM/FILM.mp4 from tools/finish.sh)
set -eu
cd "$(dirname "$0")/.."
F=$1; O=out/$F; IN=$O/$F.mp4
DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$IN")
VB=$(python3 -c "print(int(min(8000, 1.7e9 * 8 / $DUR / 1000 - 200)))")  # kbit/s of video: at most 1.7 GB in all
ffmpeg -v error -y -i "$IN" -c:v libx264 -preset medium -tune film -b:v ${VB}k -pass 1 -passlogfile $O/x264 -an -f null /dev/null
ffmpeg -v error -y -i "$IN" -c:v libx264 -preset medium -tune film -b:v ${VB}k -maxrate $((VB * 2))k -bufsize $((VB * 4))k \
  -pass 2 -passlogfile $O/x264 -c:a copy -movflags +faststart "$O/${F}_1080p.mp4"
rm -f $O/x264*
echo "DELIVERED $F $(du -h "$O/${F}_1080p.mp4" | cut -f1) $(date -u +%H:%M)"
tools/persist.sh
