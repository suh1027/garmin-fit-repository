#!/usr/bin/env bash
# Preserve the existing collector runtime environment for historical collection.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
if [[ -f "$REPO/.collector.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$REPO/.collector.env"
  set +a
fi
export GIT_SSH_COMMAND="${GIT_SSH_COMMAND:-ssh -i /home/garmin/.ssh/garmin_archive_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes}"
exec "$REPO/.venv/bin/python" "$REPO/scripts/run_backfill.py" "$@"
