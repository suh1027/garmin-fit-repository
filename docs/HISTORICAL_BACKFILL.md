# Historical Garmin backfill

Use the existing Rocky Linux collector account and virtual environment. The shell launcher loads .collector.env and the existing archive SSH identity. This is an independent read-only collection job; daily systemd timer and existing scripts are unchanged.

## Security prerequisite
The origin must be PRIVATE before publishing health/GPS records. The script checks the exact origin URL and verifies GitHub visibility using authenticated `gh api` twice. No credentials are requested in chat. Local staging is outside the repository and is not pushed by the normal timer. The existing daily job is not modified by this feature; protect the repository before running it.

## Run
```bash
sudo -iu garmin
cd /garmin/garmin-fit-pipeline
git pull --ff-only origin main
.venv/bin/pip install fitdecode
bash scripts/run_backfill.sh --since 2026-08-19 --until 2026-11-10
```
Dates are inclusive and completed days in Asia/Seoul. To publish, authenticate the GitHub CLI on the server with access to this private repository, then rerun the same command with `--push`. Existing server Git SSH key must work for push. Do not use public repositories. The script resumes successful records from ~/.local/state/garmin-backfill/<since>_<until>/manifest.json; --refresh forces refetch. A run with required gaps returns 2, an interrupted run returns 1. Optional unsupported/empty/no-data endpoints are listed separately. --allow-partial --push explicitly publishes successful records with a gap manifest, never represents them as complete. Do not use this flag until gaps are reviewed.

## Coverage and layout
- Original activity FIT, source list per day (including explicitly confirmed zero activity days), activity detail JSON (summary, laps/splits, zones, charts, map, weather, workout and sport-specific details).
- Daily raw Wellness FIT, daily sleep/HRV/HR/stress/Body Battery/stats/training readiness, plus optional daily metrics (steps, floors, respiration, SpO2, hydration, intensity, weight, blood pressure, health snapshots, etc.).
- Historical range data for available VO2 max, endurance/hill, training load, race predictions, lactate threshold, running economy/tolerance, fitness age, weight/biometrics and other range methods. Current metrics are captured under today's snapshot history, not invented for old dates.
- Existing paths activities/, wellness/, wellness_raw/, performance/ retained. New activity_inventory/, activity_details/, category/ranges/, and backfill_manifests/ directories hold source evidence and richer raw JSON. No changes to STRIDELAB ingestion in this commit.
- The installed garminconnect version and device/account determine which methods and historical data are available. The allowlist is broad but not an exhaustive export of every Garmin account feature (e.g. configuration, writes, social, golf, photos, device settings, ECG waveforms, individual health snapshot sessions). Range queries are chunked; responses are raw, and historical coverage must be inspected rather than assumed. Missing old snapshot history cannot be recreated.
- FIT validates ZIP, header/length, full FIT record decoding and CRC via fitdecode. Activity original may be unavailable for manual/non-FIT records; required gap is retained. JSON endpoint availability is not equivalent to populated sensor measurements. Activity detail endpoints can downsample; original FIT remains canonical.
- A single collector lock prevents concurrent daily jobs. Schedule an off-peak run; if the timer fires while the lock is held, its invocation may fail and the next scheduled run resumes normally. Stage is local with restrictive permissions. On publish, existing paths are updated atomically, no deletes or force push. Review manifest and any publication error before running again. If Git push fails after commit, resolve/push the local commit manually; do not reset or force push.
