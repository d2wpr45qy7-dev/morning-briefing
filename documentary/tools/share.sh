#!/usr/bin/env bash
# 720p copy under the Claude app's 500 MiB transfer limit.  usage: tools/share.sh reconquista|crusades
set -eu
cd "$(dirname "$0")/.."
F=$1; O=out/$F; IN=$O/$F.mp4
DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$IN")
VB=$(python3 -c "print(int(min(3500, 470 * 1048576 * 8 / $DUR / 1000 - 128)))")
ffmpeg -v error -y -i "$IN" -vf scale=1280:720 -c:v libx264 -preset medium -tune film -b:v ${VB}k -pass 1 -passlogfile $O/share -an -f null /dev/null
ffmpeg -v error -y -i "$IN" -vf scale=1280:720 -c:v libx264 -preset medium -tune film -b:v ${VB}k -maxrate $((VB * 2))k -bufsize $((VB * 4))k \
  -pass 2 -passlogfile $O/share -c:a aac -b:a 128k -movflags +faststart "$O/${F}_720p.part.mp4"
mv "$O/${F}_720p.part.mp4" "$O/${F}_720p.mp4"; rm -f $O/share*
echo "SHARE READY $F $(du -m "$O/${F}_720p.mp4" | cut -f1) MB"
