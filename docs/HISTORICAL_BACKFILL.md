# Historical Garmin backfill

Use the existing Rocky Linux collector account and virtual environment. The shell launcher loads .collector.env and the existing archive SSH identity. This is an independent read-only collection job; daily systemd timer and existing scripts are unchanged.

## Public repository publishing and local staging
The default `--push` mode requires a verified PRIVATE GitHub origin through authenticated `gh api` (unchanged).
For the user's explicitly requested PUBLIC repository, `--allow-public` bypasses the `gh` visibility check while still strictly checking the exact expected GitHub origin URL. No GitHub CLI authentication is necessary; the existing SSH Git push identity must work. This is a high-risk option: raw FIT files can contain GPS routes and potentially home/work locations, and JSON can include personal health metrics. All pushed records are globally accessible and may remain in git history or third-party mirrors even if subsequently removed. Never commit tokens or credentials. Local staging stays outside the repository with restrictive permissions.

## Run
```bash
sudo -iu garmin
cd /garmin/garmin-fit-pipeline
git pull --ff-only origin main
.venv/bin/pip install fitdecode
bash scripts/run_backfill.sh --since 2026-08-19 --until 2026-11-10
```
Dates are inclusive and completed days in Asia/Seoul. The script resumes successful records from ~/.local/state/garmin-backfill/<since>_<until>/manifest.json; --refresh forces refetch.

### Publish pre-collected staging with NO Garmin API requests
```bash
sudo -iu garmin
cd /garmin/garmin-fit-pipeline
git pull --ff-only origin main
bash scripts/run_backfill.sh --since 2026-08-01 --until 2026-11-10 --publish-only --push --allow-public
```
The specific completed stage must exist with `state=complete_core` or `partial`. The script checks dates, all recorded successful file SHA-256 hashes, the active branch and exact origin before commit and push. Publication uses a disposable Git worktree at the current remote main commit, so local dirty/untracked collector files are never staged or overwritten. It never logs into Garmin in `--publish-only` mode. It does not need `gh` for explicit `--allow-public`; do not use that flag unless public disclosure is intended. For a private origin, omit `--allow-public` and use authenticated `gh`.

A run with required gaps returns 2; an interrupted collection returns 1. Optional unsupported/empty/no-data endpoints are listed separately. `--allow-partial --push` explicitly publishes successful records with a gap manifest, never represents them as complete. Avoid this flag until gaps are reviewed. Unsupported optional endpoints, empty responses and optional errors are distinct states.

## Coverage and layout
- Original activity FIT, source list per day (including explicitly confirmed zero activity days), activity detail JSON (summary, laps/splits, zones, charts, map, weather, workout and sport-specific details).
- Daily raw Wellness FIT, daily sleep/HRV/HR/stress/Body Battery/stats/training readiness, plus optional daily metrics (steps, floors, respiration, SpO2, hydration, intensity, weight, blood pressure, health snapshots, etc.).
- Historical range data for available VO2 max, endurance/hill, training load, race predictions, lactate threshold, running economy/tolerance, fitness age, weight/biometrics and other range methods. Current metrics are captured under today's snapshot history, not invented for old dates.
- Existing paths activities/, wellness/, wellness_raw/, performance/ retained. New activity_inventory/, activity_details/, category/ranges/, and backfill_manifests/ directories hold source evidence and richer raw JSON. No changes to STRIDELAB ingestion in this commit.
- The installed garminconnect version and device/account determine which methods and historical data are available. The allowlist is broad but not an exhaustive export of every Garmin account feature (e.g. configuration, writes, social, golf, photos, device settings, ECG waveforms, individual health snapshot sessions). Range queries are chunked; responses are raw, and historical coverage must be inspected rather than assumed. Missing old snapshot history cannot be recreated.
- FIT validates ZIP, header/length, full FIT record decoding and CRC via fitdecode. Activity original may be unavailable for manual/non-FIT records; required gap is retained. JSON endpoint availability is not equivalent to populated sensor measurements. Activity detail endpoints can downsample; original FIT remains canonical.
- A single collector lock prevents concurrent daily jobs. Schedule an off-peak run; if the timer fires while the lock is held, its invocation may fail and the next scheduled run resumes normally. Stage is local with restrictive permissions. On publish, existing paths are updated atomically, no deletes or force push. Review manifest and any publication error before running again. If Git push fails after commit, resolve/push the local commit manually; do not reset or force push.

## Dirty local worktree handling
The publisher does not reset, stash, clean, or modify the active pipeline checkout. It creates a temporary detached Git worktree and stages **only validated Backfill files** there. This works even when `git status --short` reports pre-existing collector changes. After publishing, the original local `main` may be behind `origin/main`. Reconcile the local collector's pending changes before its next scheduled `git pull --ff-only`; do not use `git reset --hard` or `git clean` to solve this. If a remote push is rejected due to a concurrent update, re-run the same publish-only command.
