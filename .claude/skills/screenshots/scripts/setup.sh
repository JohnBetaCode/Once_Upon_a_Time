#!/usr/bin/env bash
# Create (once) a throwaway virtualenv with Playwright. Uses the system Google Chrome,
# so no browser download is required. Prints the python interpreter path to use.
set -euo pipefail
VENV="${1:-/tmp/once-upon-a-time-playwright}"
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q playwright
fi
command -v google-chrome >/dev/null || { echo "google-chrome not found; install Chrome or run: $VENV/bin/playwright install chromium" >&2; exit 1; }
echo "$VENV/bin/python"
