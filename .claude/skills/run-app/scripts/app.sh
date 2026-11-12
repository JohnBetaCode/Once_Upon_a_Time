#!/usr/bin/env bash
# Manage the Once Upon a Time Streamlit app (Docker Compose by default).
#
#   app.sh status    - container state + HTTP health of http://localhost:8501
#   app.sh up        - start (build if needed) in the background
#   app.sh rebuild   - rebuild the image (after requirements.txt / Dockerfile changes) and restart
#   app.sh restart   - restart the container (code under app/ is bind-mounted and hot-reloads;
#                      restart only when a module-level import or config/.env changed)
#   app.sh down      - stop and remove the container
#   app.sh logs [N]  - last N log lines (default 100), then follow
#   app.sh gpu       - start (build if needed) the local GPU image server (Compose profile "gpu")
#   app.sh gpu-logs [N] - follow the local GPU image server's logs
#   app.sh local     - run without Docker using the current Python environment
#
# For a full start with GPU detection, use ./launch.sh at the repo root.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$ROOT"
URL="http://localhost:8501"
GPU_URL="http://127.0.0.1:8600"

compose() { docker compose "$@"; }

health() {
  local code gpu
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$URL/_stcore/health" || true)
  if [ "$code" = "200" ]; then echo "HTTP health: OK ($URL)"; else echo "HTTP health: not responding (code: ${code:-none})"; fi
  gpu=$(curl -s --max-time 3 "$GPU_URL/health" || true)
  if [ -n "$gpu" ]; then echo "Local GPU server: $gpu"; else echo "Local GPU server: not running (optional; app.sh gpu)"; fi
}

case "${1:-status}" in
  status)
    compose --profile gpu ps 2>/dev/null || true
    health
    ;;
  up)
    compose up -d --build
    echo "Waiting for the app..."
    for _ in $(seq 1 30); do
      if curl -s -o /dev/null --max-time 2 "$URL/_stcore/health"; then break; fi
      sleep 1
    done
    health
    ;;
  rebuild)
    compose build --no-cache app
    compose up -d
    health
    ;;
  restart)
    compose restart app
    sleep 3
    health
    ;;
  down)
    compose --profile gpu down
    ;;
  gpu)
    compose --profile gpu up -d --build local-image
    health
    ;;
  gpu-logs)
    compose --profile gpu logs --tail "${2:-100}" -f local-image
    ;;
  logs)
    compose logs --tail "${2:-100}" -f app
    ;;
  local)
    python -c "import streamlit" 2>/dev/null || { echo "streamlit is not installed: pip install -r requirements.txt"; exit 1; }
    exec streamlit run app/main.py --server.port=8501
    ;;
  *)
    sed -n '2,16p' "$0"
    exit 1
    ;;
esac
