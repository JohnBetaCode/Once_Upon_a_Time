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
#   app.sh local     - run without Docker using the current Python environment
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$ROOT"
URL="http://localhost:8501"

compose() { docker compose "$@"; }

health() {
  local code
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$URL/_stcore/health" || true)
  if [ "$code" = "200" ]; then echo "HTTP health: OK ($URL)"; else echo "HTTP health: not responding (code: ${code:-none})"; fi
}

case "${1:-status}" in
  status)
    compose ps 2>/dev/null || true
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
    compose down
    ;;
  logs)
    compose logs --tail "${2:-100}" -f app
    ;;
  local)
    python -c "import streamlit" 2>/dev/null || { echo "streamlit is not installed: pip install -r requirements.txt"; exit 1; }
    exec streamlit run app/main.py --server.port=8501
    ;;
  *)
    sed -n '2,12p' "$0"
    exit 1
    ;;
esac
