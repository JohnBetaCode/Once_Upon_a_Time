#!/usr/bin/env bash
# Start Once Upon a Time with Docker Compose.
#
#   ./launch.sh              start the app, plus the local GPU image server when this machine can run it
#   ./launch.sh cloud        start the app only (images from Gemini)
#   ./launch.sh gpu          start the app and the local GPU image server (explains why when it cannot)
#   ./launch.sh status       containers, health, local GPU server state and URLs
#   ./launch.sh stop         stop everything (projects, settings and downloaded weights are kept)
#   ./launch.sh logs [app|gpu]
#
# Needs Docker with the Compose plugin. Research uses Gemini on Vertex AI, authenticated with
# `gcloud auth application-default login`. The local GPU server needs an NVIDIA GPU with at
# least 24 GB of VRAM (32 GB recommended), the NVIDIA Container Toolkit, about 40 GB of RAM and
# about 45 GB of free disk for the weights (LOCAL_IMAGE_MODELS_DIR picks where). See docs/setup.md.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

APP_URL="http://localhost:8501"
GPU_URL="http://127.0.0.1:8600"
MIN_VRAM_GB=24
MIN_RAM_GB=40
MIN_DISK_GB=45
WEIGHTS_VOLUME="local-image-models"  # shared Docker volume, see docker-compose.yml
export UID GID="${GID:-$(id -g)}"  # docker-compose.yml runs the app as you, so projects/ stays yours

if [ -t 1 ]; then B=$'\e[1m'; G=$'\e[32m'; Y=$'\e[33m'; R=$'\e[31m'; N=$'\e[0m'; else B=""; G=""; Y=""; R=""; N=""; fi
ok()   { echo "${G}✓${N} $*"; }
warn() { echo "${Y}!${N} $*"; }
fail() { echo "${R}✗${N} $*" >&2; exit 1; }

need_docker() {
  command -v docker >/dev/null || fail "Docker is not installed: https://docs.docker.com/get-docker/"
  docker compose version >/dev/null 2>&1 || fail "The Docker Compose plugin is missing: https://docs.docker.com/compose/install/"
  docker info >/dev/null 2>&1 || fail "Cannot talk to the Docker daemon (is it running, and is your user in the docker group?)"
}

check_credentials() {
  local adc="${CLOUDSDK_CONFIG:-$HOME/.config/gcloud}/application_default_credentials.json"
  if [ -s "$adc" ]; then
    ok "Google credentials found (research runs on Gemini)"
  else
    warn "No Google credentials yet. Research needs them: gcloud auth application-default login"
  fi
}

# Prints why the local GPU server cannot run here; prints nothing when it can.
gpu_reason() {
  command -v nvidia-smi >/dev/null || { echo "no NVIDIA driver found (nvidia-smi is missing)"; return; }
  local mib
  mib=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | sort -n | tail -1 | tr -d ' ')
  [ -n "$mib" ] || { echo "nvidia-smi does not report a GPU"; return; }
  if [ $((mib / 1024)) -lt "$MIN_VRAM_GB" ]; then
    echo "the GPU has $((mib / 1024)) GB of VRAM and the model needs at least $MIN_VRAM_GB GB"; return
  fi
  if ! docker info 2>/dev/null | grep -qiE 'nvidia'; then
    echo "Docker cannot use the GPU: install the NVIDIA Container Toolkit and restart Docker"; return
  fi
}

models_dir() {  # LOCAL_IMAGE_MODELS_DIR from the environment, else config/.env; empty: Docker's own storage
  local dir="${LOCAL_IMAGE_MODELS_DIR:-$(sed -n 's/^LOCAL_IMAGE_MODELS_DIR=//p' config/.env 2>/dev/null | tail -1)}"
  dir="${dir%\"}"; dir="${dir#\"}"
  [ -n "$dir" ] && echo "${dir/#\~/$HOME}"
  return 0
}

weights_location() {  # where the shared volume keeps the weights
  local device
  docker volume inspect "$WEIGHTS_VOLUME" >/dev/null 2>&1 || { echo "not created yet"; return; }
  device=$(docker volume inspect -f '{{index .Options "device"}}' "$WEIGHTS_VOLUME" 2>/dev/null)
  echo "${device:-$(docker volume inspect -f '{{.Mountpoint}}' "$WEIGHTS_VOLUME") (Docker volume $WEIGHTS_VOLUME)}"
}

# One volume, shared by every project that runs the GPU server, so each model downloads once.
# The first project that creates it decides where it lives (LOCAL_IMAGE_MODELS_DIR).
ensure_weights_volume() {
  local dir current
  dir=$(models_dir)
  if docker volume inspect "$WEIGHTS_VOLUME" >/dev/null 2>&1; then
    current=$(docker volume inspect -f '{{index .Options "device"}}' "$WEIGHTS_VOLUME" 2>/dev/null)
    if [ -n "$dir" ] && [ "$current" != "$dir" ]; then
      warn "LOCAL_IMAGE_MODELS_DIR is $dir, but the shared volume already keeps the weights in $(weights_location). To move them, see \"Where the models live\" in docs/setup.md."
    fi
    return 0
  fi
  if [ -n "$dir" ]; then
    mkdir -p "$dir" || fail "Cannot create LOCAL_IMAGE_MODELS_DIR=$dir"
    docker volume create --driver local --opt type=none --opt o=bind --opt device="$dir" "$WEIGHTS_VOLUME" >/dev/null
    ok "Model weights will be kept in $dir"
  else
    docker volume create "$WEIGHTS_VOLUME" >/dev/null
  fi
}

gpu_warnings() {
  local ram_gb free_gb root
  ram_gb=$(awk '/MemTotal/ {printf "%d", $2 / 1048576}' /proc/meminfo 2>/dev/null || echo 0)
  if [ "${ram_gb:-0}" -gt 0 ] && [ "$ram_gb" -lt "$MIN_RAM_GB" ]; then
    warn "This machine has ${ram_gb} GB of RAM; the model holds about 25 GB while loaded (${MIN_RAM_GB} GB recommended)"
  fi
  if ! docker volume inspect "$WEIGHTS_VOLUME" >/dev/null 2>&1; then
    root=$(models_dir); [ -n "$root" ] && mkdir -p "$root" 2>/dev/null
    [ -d "$root" ] || root=$(docker info --format '{{.DockerRootDir}}' 2>/dev/null || echo /var/lib/docker)
    free_gb=$(df -BG --output=avail "$root" 2>/dev/null | tail -1 | tr -dc '0-9')
    if [ -n "$free_gb" ] && [ "$free_gb" -lt "$MIN_DISK_GB" ]; then
      warn "Only ${free_gb} GB free under $root; the first start downloads about 33 GB of weights plus a ~10 GB image"
    fi
  fi
}

json_field() {  # json_field <json> <key>: crude extractor for flat string/number fields
  sed -n "s/.*\"$2\":\"\{0,1\}\([^,\"}]*\)\"\{0,1\}[,}].*/\1/p" <<<"$1" | head -1
}

app_health() {
  curl -s -o /dev/null --max-time 3 -w '%{http_code}' "$APP_URL/_stcore/health" 2>/dev/null || true
}

gpu_status_line() {
  local body status
  body=$(curl -s --max-time 3 "$GPU_URL/health" 2>/dev/null || true)
  if [ -z "$body" ]; then echo "not running"; return; fi
  status=$(json_field "$body" status)
  case "$status" in
    downloading) echo "downloading the model weights: $(json_field "$body" downloaded_gb) of $(json_field "$body" total_gb) GB ($(json_field "$body" percent)%)";;
    ready|idle)  echo "ready ($(json_field "$body" model) on $(json_field "$body" gpu))";;
    unsupported|error) echo "$status: $(json_field "$body" error)";;
    *) echo "$status";;
  esac
}

print_urls() {
  echo
  echo "${B}Open the app:${N} $APP_URL"
  local ips
  if command -v ip >/dev/null; then
    ips=$(ip -4 -o addr show scope global 2>/dev/null | awk '$2 !~ /^(docker|br-|veth|virbr)/ {split($4, a, "/"); print a[1]}')
  else
    ips=$(hostname -I 2>/dev/null || true)
  fi
  for ip in $ips; do echo "  from other devices: http://$ip:8501"; done
}

backend_setting() {
  local value
  value=$(sed -n 's/^IMAGE_BACKEND=//p' config/.env 2>/dev/null | tail -1)
  echo "${value:-gemini (default)}"
}

wait_for_app() {
  for _ in $(seq 1 60); do
    [ "$(app_health)" = "200" ] && return 0
    sleep 1
  done
  return 1
}

start() {
  local mode="$1" reason=""
  need_docker
  check_credentials
  if [ "$mode" = "auto" ] || [ "$mode" = "gpu" ]; then
    reason=$(gpu_reason)
    if [ -z "$reason" ]; then
      ok "NVIDIA GPU can run the local image model"
      gpu_warnings
      mode="gpu"
    elif [ "$mode" = "gpu" ]; then
      fail "The local GPU image server cannot run here: $reason"
    else
      echo "  Local GPU image server skipped: $reason. Images will come from Gemini."
      mode="cloud"
    fi
  fi

  if [ "$mode" = "gpu" ]; then
    echo "Starting the app and the local GPU image server (the first build takes a few minutes)..."
    ensure_weights_volume
    docker compose --profile gpu up -d --build
  else
    echo "Starting the app..."
    docker compose up -d --build app
  fi

  if wait_for_app; then ok "App is up"; else warn "The app did not answer yet; check ./launch.sh logs app"; fi
  print_urls

  if [ "$mode" = "gpu" ]; then
    for _ in $(seq 1 60); do  # wait until the server is past its start-up checks
      case "$(gpu_status_line)" in "not running"|checking*) sleep 1 ;; *) break ;; esac
    done
    echo
    echo "${B}Local GPU server:${N} $(gpu_status_line)"
    if ! docker volume inspect "$WEIGHTS_VOLUME" >/dev/null 2>&1 || [[ "$(gpu_status_line)" == downloading* ]]; then
      echo "  The first start downloads ~33 GB once; follow it with ./launch.sh status"
    fi
    if [ "$(backend_setting)" != "local" ]; then
      echo "  To use it: Settings → Image backend → Local GPU → Save (the app keeps using Gemini until then)."
    fi
  fi
}

case "${1:-auto}" in
  auto|"") start auto ;;
  cloud)   start cloud ;;
  gpu)     start gpu ;;
  status)
    need_docker
    docker compose --profile gpu ps
    echo
    if [ "$(app_health)" = "200" ]; then ok "App: $APP_URL"; else warn "App: not responding at $APP_URL"; fi
    echo "Local GPU server: $(gpu_status_line)"
    echo "Model weights: $(weights_location)"
    echo "Image backend setting: $(backend_setting)"
    ;;
  stop)
    need_docker
    docker compose --profile gpu down
    ok "Stopped. Projects, settings and downloaded weights are kept."
    ;;
  logs)
    need_docker
    case "${2:-app}" in
      gpu|local-image) docker compose --profile gpu logs --tail 100 -f local-image ;;
      *) docker compose logs --tail 100 -f app ;;
    esac
    ;;
  -h|--help|help) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//' ;;
  *) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
