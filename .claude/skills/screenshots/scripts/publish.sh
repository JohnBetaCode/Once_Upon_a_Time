#!/usr/bin/env bash
# Resize/compress raw captures into docs/images/ with the file names the README expects.
#   publish.sh <raw-shots-dir> [docs/images]
# Uses ImageMagick when installed, otherwise Pillow (python3).
set -euo pipefail
SRC="${1:?raw shots dir}"; DST="${2:-docs/images}"
mkdir -p "$DST"
for f in "$SRC"/*.png; do
  n=$(basename "$f" .png)
  if command -v convert >/dev/null; then
    convert "$f" -resize 1280x -colors 255 "$DST/ui-$n.png"
  else
    python3 - "$f" "$DST/ui-$n.png" <<'EOF'
import sys
from PIL import Image
im = Image.open(sys.argv[1]).convert("RGB")
im = im.resize((1280, round(im.height * 1280 / im.width)), Image.LANCZOS)
im.quantize(colors=255, method=Image.Quantize.MEDIANCUT).save(sys.argv[2], optimize=True)
EOF
  fi
  echo "wrote $DST/ui-$n.png"
done
