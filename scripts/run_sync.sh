#!/usr/bin/env bash
# Garmin activity FIT + health JSON + Wellness individual FIT archival.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
# GARMIN_SYNC_RUN_LOG_V2
echo "[SYNC] $(TZ=Asia/Seoul date '+%Y-%m-%d %H:%M:%S %Z')"
exec 9>"${REPO}/.collector.lock"
flock -n 9 || { echo "ERROR: Another Garmin collector is already running" >&2; exit 1; }
if [[ -f "${REPO}/.collector.env" ]]; then
  # shellcheck disable=SC1091
  source "${REPO}/.collector.env"
fi
ENABLE_HEALTH_JSON="${ENABLE_HEALTH_JSON:-1}"
HEALTH_DAYS="${HEALTH_DAYS:-7}"
ENABLE_WELLNESS_RAW="${ENABLE_WELLNESS_RAW:-1}"
WELLNESS_DAYS="${WELLNESS_DAYS:-7}"
export GIT_SSH_COMMAND="${GIT_SSH_COMMAND:-ssh -i /home/garmin/.ssh/garmin_archive_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes}"

# Fail safely if upstream history has changed; never force push or overwrite.
git pull --ff-only origin main
collector_failed=0
run() {
  local label="$1"; shift
  echo "[RUN] ${label} $(date -Is)"
  if "$@"; then
    echo "[OK] ${label}"
  else
    local rc=$?
    echo "[WARN] ${label} exit=${rc}; attempting other jobs and Push" >&2
    collector_failed=1
  fi
}

run ACTIVITY_FIT "${REPO}/.venv/bin/python" "${REPO}/scripts/sync_fit.py" "$@"
if [[ "$ENABLE_HEALTH_JSON" == "1" ]]; then
  run WELLNESS_JSON "${REPO}/.venv/bin/python" "${REPO}/scripts/sync_health.py" --days "$HEALTH_DAYS"
fi
if [[ "$ENABLE_WELLNESS_RAW" == "1" ]]; then
  run WELLNESS_INDIVIDUAL_FIT "${REPO}/.venv/bin/python" "${REPO}/scripts/sync_wellness_raw.py" --mode api --days "$WELLNESS_DAYS"
fi
paths=()
for p in activities wellness performance wellness_raw; do
  [[ -d "${REPO}/${p}" ]] && paths+=("$p")
done
if (( ${#paths[@]} > 0 )); then
  git add -A -- "${paths[@]}"
fi
if ! git diff --cached --quiet; then
  git commit -m "archive: Garmin sync $(TZ=Asia/Seoul date +%F)"
fi
git push origin main
exit "$collector_failed"
