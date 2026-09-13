#!/usr/bin/env sh
# Safe Docker update path for Odysseus-Lab on Linux and macOS.

set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

for command in git docker python3; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "error: required command not found: $command" >&2
        exit 1
    fi
done
docker compose version >/dev/null

branch=$(git branch --show-current)
if [ "$branch" != "main" ]; then
    echo "error: updates must run from main (current branch: ${branch:-detached})" >&2
    exit 1
fi

previous_sha=$(git rev-parse HEAD)
app_port=${APP_PORT:-}
compose_files=${COMPOSE_FILE:-}
if [ -f .env ]; then
    if [ -z "$app_port" ]; then
        app_port=$(awk -F= '$1 == "APP_PORT" {sub(/^[^=]*=/, ""); print; exit}' .env)
    fi
    if [ -z "$compose_files" ]; then
        compose_files=$(awk -F= '$1 == "COMPOSE_FILE" {sub(/^[^=]*=/, ""); print; exit}' .env)
    fi
fi
app_port=${app_port:-7000}
compose_files=${compose_files:-docker-compose.yml}

failed() {
    code=$?
    trap - EXIT HUP INT TERM
    if [ "$code" -ne 0 ]; then
        cat >&2 <<EOF
Update failed.
Previous commit: $previous_sha
Review changes: git diff $previous_sha..HEAD
Restore the pre-update bundle with:
  python3 scripts/odysseus-compose-backup restore backups/BUNDLE.tar.gz --yes
EOF
    fi
    exit "$code"
}
trap failed EXIT HUP INT TERM

echo "Compose files: $compose_files"
echo "Creating a full pre-update backup..."
python3 scripts/odysseus-compose-backup snapshot

echo "Pulling origin/main with fast-forward only..."
git pull --ff-only origin main

echo "Rebuilding and starting the stack..."
docker compose up -d --build

echo "Waiting for Odysseus-Lab readiness on port $app_port..."
python3 - "$app_port" <<'PY'
import sys
import time
import urllib.request

url = f"http://127.0.0.1:{sys.argv[1]}/api/ready"
deadline = time.monotonic() + 300
while time.monotonic() < deadline:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            if response.status == 200:
                raise SystemExit(0)
    except Exception:
        time.sleep(5)
raise SystemExit(f"readiness timeout: {url}")
PY

docker image prune -f
trap - EXIT HUP INT TERM
echo "Odysseus-Lab update completed successfully."
