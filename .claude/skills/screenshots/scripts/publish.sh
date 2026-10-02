#!/usr/bin/env bash
# Resize/compress raw captures into docs/images/ with the file names the README expects.
#   publish.sh <raw-shots-dir> [docs/images]
set -euo pipefail
SRC="${1:?raw shots dir}"; DST="${2:-docs/images}"
mkdir -p "$DST"
for f in "$SRC"/*.png; do
  n=$(basename "$f" .png)
  convert "$f" -resize 1280x -colors 255 "$DST/ui-$n.png"
  echo "wrote $DST/ui-$n.png"
done
