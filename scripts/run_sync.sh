#!/usr/bin/env bash
# Extension of existing sync workflow. Preserve original activity collector.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec 9>"${REPO}/.collector.lock"
flock -n 9 || { echo 'Another Garmin sync is still running' >&2; exit 1; }
cd "$REPO"

# Non-secret local config, untracked by Git.
if [[ -f "${REPO}/.collector.env" ]]; then
  # This file is a trusted, owner-controlled shell config (chmod 600).
  # shellcheck disable=SC1091
  source "${REPO}/.collector.env"
fi

export GIT_SSH_COMMAND="${GIT_SSH_COMMAND:-ssh -i /home/garmin/.ssh/garmin_archive_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes}"
ENABLE_HEALTH_JSON="${ENABLE_HEALTH_JSON:-1}"
ENABLE_WELLNESS_RAW="${ENABLE_WELLNESS_RAW:-0}"
HEALTH_DAYS="${HEALTH_DAYS:-7}"
WELLNESS_DAYS="${WELLNESS_DAYS:-2}"

# Single writer policy; never force-push.
git pull --ff-only origin main
result=0
run_collector() {
  local label="$1"; shift
  echo "[COLLECT] ${label}"
  if "$@"; then
    echo "[OK] ${label}"
  else
    local rc=$?
    echo "[WARN] ${label} failed (exit=${rc}); continuing with remaining collectors and Git push" >&2
    result=1
  fi
}

run_collector FIT "${REPO}/.venv/bin/python" "${REPO}/scripts/sync_fit.py" "$@"
if [[ "$ENABLE_HEALTH_JSON" == "1" ]]; then
  run_collector HEALTH "${REPO}/.venv/bin/python" "${REPO}/scripts/sync_health.py" --days "$HEALTH_DAYS"
fi
if [[ "$ENABLE_WELLNESS_RAW" == "1" ]]; then
  # Activate only after one day's ZIP has been inspected/verified.
  run_collector WELLNESS_ZIP "${REPO}/.venv/bin/python" "${REPO}/scripts/sync_wellness_raw.py" --mode api --days "$WELLNESS_DAYS"
fi

# Stage only intended data paths (plus prior locally pending commits).
paths=()
for path in activities wellness performance wellness_raw; do
  [[ -d "${REPO}/${path}" ]] && paths+=("$path")
done
if (( ${#paths[@]} )); then
  git add -A -- "${paths[@]}"
fi
if ! git diff --cached --quiet; then
  git commit -m "archive: Garmin activity and wellness sync $(date +%Y-%m-%d)"
fi
git push origin main
exit "$result"
