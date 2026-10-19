#!/usr/bin/env bash
# Prevent overlapping collectors; preserve collected data when a push fails.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec 9>"${REPO}/.collector.lock"
flock -n 9 || { echo 'Another Garmin sync is still running' >&2; exit 1; }
cd "$REPO"
# Use this repository's dedicated SSH deploy key, independent of ssh-agent.
# Host key must already be verified in /home/garmin/.ssh/known_hosts.
export GIT_SSH_COMMAND="${GIT_SSH_COMMAND:-ssh -i /home/garmin/.ssh/garmin_archive_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes}"
# This pipeline assumes only this machine writes to the archive branch.
git pull --ff-only origin main
set +e
"${REPO}/.venv/bin/python" "${REPO}/scripts/sync_fit.py" "$@"
collector_rc=$?
set -e
git add -A -- activities
if ! git diff --cached --quiet; then
  git commit -m "archive: Garmin FIT sync $(date +%Y-%m-%d)"
fi
# Push also retries any previously committed but unpushed FIT files.
git push origin main
exit "$collector_rc"
