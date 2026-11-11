#!/usr/bin/env python3
"""Read-only historical Garmin collector. Stage first; publishing requires explicit opt-in."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
import fcntl
import hashlib
import inspect
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

from garminconnect import Garmin
import sync_fit as activity
import sync_health as health
import sync_wellness_raw as raw

ROOT = Path(__file__).resolve().parents[1]
KST = ZoneInfo("Asia/Seoul")
REPO = "suh1027/garmin-fit-repository"
# Read-only allowlist. Existing 7 daily metrics retain their exact archive paths.
CORE = health.DAILY
DAILY = {
    "wellness": {
        "steps": "get_steps_data", "floors": "get_floors",
        "respiration": "get_respiration_data", "spo2": "get_spo2_data",
        "spo2_acclimation": "get_spo2_acclimation_data",
        "intensity_minutes": "get_intensity_minutes_data",
        "hydration": "get_hydration_data", "hydration_all": "get_hydration_all_data",
        "body_battery_events": "get_body_battery_events",
        "all_day_events": "get_all_day_events", "resting_heart_rate": "get_rhr_day",
        "daily_movement": "get_daily_movement", "steps_goal": "get_steps_goal",
        "weigh_ins": "get_daily_weigh_ins", "body_composition_daily": "get_stats_and_body",
        "blood_pressure_daily": "get_blood_pressure_day", "health_snapshots": "get_health_snapshots",
        "lifestyle": "get_lifestyle_logging_data", "jetlag_status": "get_jetlag_status",
    },
    "performance": {
        "daily_training_status": "get_daily_training_status",
        "morning_training_readiness": "get_morning_training_readiness",
        "fitness_age": "get_fitness_age_details", "running_economy": "get_running_economy",
        "heat_altitude_acclimation": "get_heat_altitude_acclimation",
        "cycling_ability": "get_cycling_ability", "critical_swim_speed": "get_critical_swim_speed",
        "stamina_curve": "get_stamina_curve",
    },
}
# Query historical range endpoints separately; never assign current aggregates to old dates.
RANGES = {
    "wellness": {
        "daily_steps": "get_daily_steps", "daily_summaries": "get_daily_summaries",
        "daily_stress": "get_daily_stress_stats", "hrv": "get_hrv_data_range",
        "body_composition": "get_body_composition", "weigh_ins": "get_weigh_ins",
        "weight": "get_daily_last_weight", "weight_snapshot": "get_weight_snapshot",
        "blood_pressure": "get_blood_pressure", "daily_blood_pressure": "get_daily_last_blood_pressure",
        "health_snapshots": "get_health_snapshots_range", "ecg_daily": "get_ecg_daily",
        "calorie_summary": "get_calorie_summary",
    },
    "performance": {
        "max_metrics": "get_max_metrics_range", "endurance_score": "get_endurance_score",
        "hill_score": "get_hill_score", "race_predictions": "get_race_predictions",
        "running_tolerance": "get_running_tolerance", "running_economy": "get_running_economy_range",
        "cycling_ability": "get_cycling_ability_range", "critical_swim_speed": "get_critical_swim_speed_range",
        "heat_altitude_acclimation": "get_heat_altitude_acclimation_range",
        "fitness_age": "get_fitness_age_daily", "training_load_activities": "get_training_load_activities",
        "weekly_activity_stats": "get_weekly_activity_stats", "fastest_splits": "get_fastest_splits",
        "biometric_stats": "get_biometric_stats", "power_to_weight": "get_power_to_weight_range",
        "power_curve": "get_power_curve", "available_metrics": "get_available_metrics",
    },
}
ACTIVITY = {
    "summary": "get_activity", "details": "get_activity_details", "laps": "get_activity_laps",
    "splits": "get_activity_splits", "split_summaries": "get_activity_split_summaries",
    "typed_splits": "get_activity_typed_splits", "heart_rate_zones": "get_activity_hr_in_timezones",
    "power_zones": "get_activity_power_in_timezones", "weather": "get_activity_weather",
    "map": "get_activity_map_details", "polyline": "get_activity_polyline",
    "segments": "get_activity_segments", "exercise_sets": "get_activity_exercise_sets",
    "rounds": "get_activity_rounds", "step_details": "get_activity_step_details",
    "swim_details": "get_activity_swim_details", "jump_details": "get_activity_jump_details",
    "subsecond_details": "get_activity_subsecond_details",
}
CURRENT = {
    "vo2max": ("get_max_metrics", True), "training_status": ("get_training_status", True),
    "load_focus": ("get_training_four_week_load_balance", True),
    "biometrics": ("get_current_biometrics", False), "lactate_threshold": ("get_lactate_threshold", False),
    "cycling_ftp": ("get_cycling_ftp", False), "heart_rate_zones": ("get_heart_rate_zones", False),
    "power_zones": ("get_power_zones", False), "personal_records": ("get_personal_record", False),
    "race_predictions": ("get_race_predictions", False),
}

def days_between(first, last):
    return [first + timedelta(days=i) for i in range((last-first).days+1)]

def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str)+"\n").encode()

def save(path, payload):
    return raw.save_if_changed(path, payload)

def verify_fit(payload):
    # Full record traversal + CRC, not just .FIT magic/header.
    import fitdecode
    if not raw.fit_valid(payload):
        raise ValueError("invalid FIT header/length")
    count = 0
    with fitdecode.FitReader(BytesIO(payload), check_crc=fitdecode.CrcCheck.RAISE,
                            error_handling=fitdecode.ErrorHandling.RAISE) as reader:
        for frame in reader:
            if isinstance(frame, fitdecode.FitDataMessage):
                count += 1
    if not count:
        raise ValueError("no FIT data messages")
    return count

def git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True,
                          stdout=subprocess.PIPE, text=True).stdout.strip()

def private_origin(allow_public=False):
    # Exact origin is always enforced. Public exposure requires explicit opt-in.
    url = git("remote", "get-url", "origin")
    allowed = {f"https://github.com/{REPO}", f"https://github.com/{REPO}.git",
               f"git@github.com:{REPO}.git", f"ssh://git@github.com/{REPO}.git"}
    if url not in allowed:
        raise RuntimeError("origin is not the expected GitHub repository")
    if allow_public:
        print("WARNING: You explicitly requested PUBLIC publication of raw GPS and health data.",
              file=sys.stderr, flush=True)
        return
    try:
        result = subprocess.run(["gh", "api", f"repos/{REPO}", "--jq", ".visibility"],
                                capture_output=True, text=True, check=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError("Cannot verify private origin. Install/authenticate gh or set GH_TOKEN locally.") from None
    if result.stdout.strip() != "private":
        raise RuntimeError("Origin is not PRIVATE; publication blocked.")

def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--since", required=True, type=date.fromisoformat)
    p.add_argument("--until", required=True, type=date.fromisoformat)
    p.add_argument("--pause", type=float, default=2)
    p.add_argument("--retries", type=int, default=3)
    p.add_argument("--push", action="store_true", help="Publish data to GitHub")
    p.add_argument("--allow-public", action="store_true", help="Explicit opt-in to PUBLIC GPS/health data publication")
    p.add_argument("--publish-only", action="store_true", help="Push completed staging without Garmin API requests")
    p.add_argument("--allow-partial", action="store_true", help="Permit publication with recorded required gaps")
    p.add_argument("--refresh", action="store_true", help="Refetch successful API results instead of resuming")
    p.add_argument("--no-current", action="store_true")
    return p.parse_args()

class StopCollection(Exception):
    pass

class Collector:
    def __init__(self, opts, stage, client, existing_only=False):
        self.opts, self.stage, self.client = opts, stage, client
        self.manifest_path = stage / "manifest.json"
        if existing_only and not self.manifest_path.is_file():
            raise RuntimeError("Completed staged manifest not found.")
        self.manifest = json.loads(self.manifest_path.read_text()) if self.manifest_path.exists() else {}
        self.records = self.manifest.setdefault("records", {})
        if existing_only:
            if self.manifest.get("state") not in ("complete_core", "partial"):
                raise RuntimeError("Manifest is not a completed collection.")
            if (self.manifest.get("since"), self.manifest.get("until")) != (str(opts.since), str(opts.until)):
                raise RuntimeError("Staged manifest dates do not match the requested dates.")
            keys = self.manifest.get("active_records")
            if not isinstance(keys, list) or not keys:
                raise RuntimeError("Missing active_records in completed manifest.")
            self.active = set(keys)
            return
        self.active = set()
        self.manifest.update(since=str(opts.since), until=str(opts.until),
                             schema=1, timezone="Asia/Seoul", state="running")
        self.flush()

    def flush(self):
        save(self.manifest_path, json_bytes(self.manifest))

    def record(self, key, status, required, **extra):
        self.active.add(key)
        self.records[key] = dict(status=status, required=required, **extra)
        self.flush()

    def request(self, call):
        for attempt in range(self.opts.retries+1):
            try:
                result = call()
                time.sleep(self.opts.pause)
                return result
            except Exception as exc:
                name = type(exc).__name__.lower()
                response = getattr(exc, "response", None)
                status = getattr(response, "status_code", None)
                if "authentication" in name or status in (401, 403):
                    raise StopCollection("authentication/permission failure") from None
                if "notfound" in name or status == 404:
                    raise LookupError("not available") from None
                if "toomanyrequests" in name or status == 429:
                    if attempt >= self.opts.retries:
                        raise StopCollection("rate limit; resume later") from None
                elif isinstance(exc, (ValueError, TypeError, AttributeError)):
                    raise
                elif attempt >= self.opts.retries:
                    raise
                time.sleep(max(self.opts.pause, min(120, 10 * (2 ** attempt))))

    def cached(self, key, target):
        r = self.records.get(key, {})
        if self.opts.refresh or r.get("status") != "ok" or not target.is_file():
            return False
        return hashlib.sha256(target.read_bytes()).hexdigest() == r.get("sha256")

    def output(self, key, rel, payload, required):
        target = self.stage / rel
        save(target, payload)
        self.record(key, "ok", required, path=str(rel),
                    sha256=hashlib.sha256(payload).hexdigest())

    def api(self, rel, method, args=(), required=False, kwargs=None, accept_empty=False):
        key = str(rel)
        target = self.stage / rel
        self.active.add(key)
        if self.cached(key, target):
            return json.loads(target.read_text())
        fn = getattr(self.client, method, None)
        if not callable(fn):
            self.record(key, "unsupported", required, method=method)
            return None
        kwargs = kwargs or {}
        try:
            inspect.signature(fn).bind(*args, **kwargs)
        except (TypeError, ValueError):
            self.record(key, "unsupported_signature", required, method=method)
            return None
        try:
            value = self.request(lambda: fn(*args, **kwargs))
            if not accept_empty and value in (None, {}, []):
                self.record(key, "empty", required, method=method)
                return None
            if value is None:
                self.record(key, "empty", required, method=method)
                return None
            self.output(key, rel, json_bytes(value), required)
            return value
        except StopCollection:
            self.record(key, "blocked", required, method=method)
            raise
        except LookupError:
            self.record(key, "unavailable", required, method=method)
        except Exception as exc:
            self.record(key, "error", required, method=method, error=type(exc).__name__)
        return None

    def fit(self, row, day):
        aid = str(row["activityId"])
        rel = Path("activities") / day.strftime("%Y/%m/%d") / (aid+".fit")
        key = str(rel)
        self.active.add(key)
        if self.cached(key, self.stage/rel):
            return
        try:
            # Reuse verified archive, otherwise re-download.
            for candidate in (self.stage/rel, ROOT/rel, ROOT/rel.parent.parent/rel.name):
                if candidate.is_file():
                    try:
                        payload = candidate.read_bytes()
                        verify_fit(payload)
                        self.output(key, rel, payload, True)
                        return
                    except Exception:
                        pass
            z = self.request(lambda: self.client.download_activity(
                int(aid), dl_fmt=self.client.ActivityDownloadFormat.ORIGINAL))
            payload = activity.original_to_fit(z)
            verify_fit(payload)
            self.output(key, rel, payload, True)
        except StopCollection:
            self.record(key, "blocked", True)
            raise
        except Exception as exc:
            self.record(key, "unavailable" if isinstance(exc, LookupError) else "error",
                        True, error=type(exc).__name__)

    def wellness_fit(self, day):
        rel = Path("wellness_raw") / day.strftime("%Y/%m/%d")
        key = str(rel)+"/_archive"
        self.active.add(key)
        prior = self.records.get(key, {})
        files = prior.get("files", {})
        if not self.opts.refresh and prior.get("status") == "ok" and files and all(
            (self.stage/p).is_file() and hashlib.sha256((self.stage/p).read_bytes()).hexdigest()==h
            for p,h in files.items()):
            return
        try:
            z = self.request(lambda: self.client.download("/download-service/files/wellness/"+str(day)))
            members = raw.extract_fit_members(bytes(z))
            for data in members.values():
                verify_fit(data)
            hashes = {}
            for name, data in members.items():
                path = rel/name
                save(self.stage/path, data)
                hashes[str(path)] = hashlib.sha256(data).hexdigest()
            self.record(key, "ok", True, files=hashes)
        except StopCollection:
            self.record(key, "blocked", True)
            raise
        except Exception as exc:
            self.record(key, "unavailable" if isinstance(exc, LookupError) else "error",
                        True, error=type(exc).__name__)

    def collect(self):
        o = self.opts
        interval = str(o.since)+"_"+str(o.until)
        inventory = {}
        # One query per date: explicit distinction between confirmed zero and failed listing.
        for day in days_between(o.since, o.until):
            d = str(day)
            path = day.strftime("%Y/%m/%d")
            print("Collect", d, flush=True)
            listing = self.api(Path("activity_inventory")/path/"activities.json",
                               "get_activities_by_date", (d,d), True, accept_empty=True)
            if not isinstance(listing, list):
                self.record("inventory/"+d, "error", True, reason="missing or non-list activity response")
            else:
                inventory[d] = len(listing)
                self.record("inventory/"+d, "ok", True, activity_count=len(listing))
                seen = set()
                for row in listing:
                    try:
                        aid = str(row["activityId"])
                        if not activity.ID_RE.fullmatch(aid):
                            raise ValueError("invalid ID")
                        actual = activity.archive_date(row)
                        if actual != day:
                            raise ValueError("activity date mismatch")
                        if aid in seen:
                            continue
                        seen.add(aid)
                    except (ValueError, KeyError, TypeError):
                        self.record("inventory/"+d, "error", True, reason="invalid activity ID/date")
                        continue
                    self.fit(row, day)
                    for metric, method in ACTIVITY.items():
                        self.api(Path("activity_details")/path/aid/(metric+".json"), method, (aid,))
            for category, metrics in CORE.items():
                for metric, method in metrics.items():
                    args = (d,d) if method == "get_body_battery" else (d,)
                    self.api(Path(category)/path/(metric+".json"), method, args, True)
            for category, metrics in DAILY.items():
                for metric, method in metrics.items():
                    self.api(Path(category)/path/(metric+".json"), method, (d,))
            self.wellness_fit(day)
        for category, metrics in RANGES.items():
            # Small windows respect endpoint-specific maximum date ranges.
            for start,end in activity.monthly_chunks(o.since,o.until):
                label = str(start)+"_"+str(end)
                for metric, method in metrics.items():
                    self.api(Path(category)/"ranges"/label/(metric+".json"),
                             method, (str(start),str(end)))
                self.api(Path("performance")/"ranges"/label/"lactate_threshold.json",
                         "get_lactate_threshold", kwargs={"latest":False,"start_date":str(start),"end_date":str(end)})
        if not o.no_current:
            now = datetime.now(KST)
            path = Path("performance")/"snapshots"/now.strftime("%Y/%m/%d")/"history"/now.strftime("%H%M%S%f")
            for metric,(method,dated) in CURRENT.items():
                self.api(path/(metric+".json"), method, (str(now.date()),) if dated else ())
        self.manifest["activity_counts"] = inventory
        self.manifest["interval"] = interval

    def finish(self, interrupted=False):
        current = {k:self.records[k] for k in self.active}
        missing = [k for k,v in current.items() if v["required"] and v["status"]!="ok"]
        optional = [k for k,v in current.items() if not v["required"] and v["status"]!="ok"]
        self.manifest.update(state="interrupted" if interrupted else ("partial" if missing else "complete_core"),
                             required_gaps=sorted(missing), optional_gaps=sorted(optional),
                             active_records=sorted(current))
        self.flush()
        print("Manifest:", self.manifest_path, "| required gaps:", len(missing),
              "| optional gaps:", len(optional), flush=True)
        return missing

    def publish(self):
        # Only current successful results; stale/failed files remain in staging.
        private_origin(self.opts.allow_public)
        if git("status", "--porcelain"):
            raise RuntimeError("Repository working tree is not clean; resolve changes before publishing.")
        if git("branch", "--show-current") != "main":
            raise RuntimeError("Repository must be on main.")
        git("pull", "--ff-only", "origin", "main")
        expected_hashes = {}
        for key in self.active:
            item = self.records.get(key)
            if not isinstance(item, dict):
                raise RuntimeError("Active manifest record missing: " + str(key))
            if item.get("status") != "ok":
                continue
            entries = dict(item.get("files", {}))
            if "path" in item:
                entries[item["path"]] = item.get("sha256")
            for p, digest in entries.items():
                if p in expected_hashes and expected_hashes[p] != digest:
                    raise RuntimeError("Conflicting staged hashes for " + p)
                expected_hashes[p] = digest
        if not expected_hashes:
            raise RuntimeError("No completed files available for publication.")
        allowed_roots = {"activities", "activity_inventory", "activity_details",
                         "wellness", "wellness_raw", "performance"}
        verified_paths = []
        for p, digest in sorted(expected_hashes.items()):
            relative = Path(p)
            if relative.is_absolute() or ".." in relative.parts or not relative.parts or relative.parts[0] not in allowed_roots:
                raise RuntimeError("Unsafe manifest path: " + p)
            source = (self.stage / relative).resolve()
            if not source.is_relative_to(self.stage.resolve()) or not source.is_file():
                raise RuntimeError("Staged file unavailable: " + p)
            payload = source.read_bytes()
            if not isinstance(digest, str) or hashlib.sha256(payload).hexdigest() != digest:
                raise RuntimeError("Staged hash mismatch: " + p)
            verified_paths.append(p)
        # Validate ALL staged hashes before copying; copy one file at a time to limit RAM.
        for p in verified_paths:
            save(ROOT/p, (self.stage/p).read_bytes())
        manifest_rel = Path("backfill_manifests")/(self.manifest["interval"]+".json")
        save(ROOT/manifest_rel, json_bytes(self.manifest))
        git("add", "--", "activities", "activity_inventory", "wellness", "wellness_raw",
            "performance", "backfill_manifests", *(
                ["activity_details"] if (ROOT/"activity_details").exists() else []))
        if subprocess.run(["git","-C",str(ROOT),"diff","--cached","--quiet"]).returncode == 1:
            git("commit", "-m", "archive: Garmin historical backfill "+self.manifest["interval"])
        private_origin(self.opts.allow_public)
        git("push", "origin", "main")
        print("Published:", git("rev-parse","HEAD"), flush=True)

def main():
    o = parse_args()
    today = datetime.now(KST).date()
    if not (o.since <= o.until < today) or (o.until-o.since).days >= 365:
        raise SystemExit("Specify 1..365 completed KST dates; today is excluded.")
    if not 0 <= o.pause <= 60 or not 0 <= o.retries <= 5:
        raise SystemExit("Invalid pause/retries.")
    if o.allow_partial and not o.push:
        raise SystemExit("--allow-partial requires --push")
    if o.allow_public and not o.push:
        raise SystemExit("--allow-public requires --push")
    if o.publish_only and not o.push:
        raise SystemExit("--publish-only requires --push")
    if o.publish_only and o.refresh:
        raise SystemExit("--publish-only cannot be combined with --refresh")
    os.umask(0o077)
    state = Path(os.environ.get("GARMIN_BACKFILL_STATE", "~/.local/state/garmin-backfill")).expanduser().resolve()
    if state == ROOT or ROOT in state.parents:
        raise SystemExit("Staging must be outside repository.")
    stage = state/(str(o.since)+"_"+str(o.until))
    stage.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = (ROOT/".collector.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("Another Garmin collector is running.")
    # Hold the same lock as run_sync.sh until exit. Do not alter systemd.
    if o.push:
        private_origin(o.allow_public)
    if o.publish_only:
        c = Collector(o, stage, None, existing_only=True)
        missing = [k for k in c.active
                   if c.records[k].get("required") and c.records[k].get("status") != "ok"]
        if missing and not o.allow_partial:
            raise RuntimeError("Staged manifest has required gaps: " + str(len(missing)))
        print("Publish-only: reusing completed staging without Garmin API calls.", flush=True)
        c.publish()
        return 2 if missing else 0
    try:
        import fitdecode
    except ImportError:
        raise SystemExit("Install fitdecode in existing venv: .venv/bin/pip install fitdecode")
    tokenstore = Path(os.getenv("GARMIN_TOKEN_DIR","~/.garminconnect")).expanduser()
    if not (tokenstore/"garmin_tokens.json").is_file():
        raise SystemExit("Missing existing Garmin token store.")
    client = Garmin()
    client.login(str(tokenstore))
    c = Collector(o,stage,client)
    try:
        c.collect()
    except (StopCollection, KeyboardInterrupt) as exc:
        c.finish(interrupted=True)
        print("Collection interrupted; rerun same command to resume.", file=sys.stderr)
        return 1
    missing = c.finish()
    if o.push:
        if missing and not o.allow_partial:
            print("Required data gaps; publication blocked. Inspect manifest and retry.", file=sys.stderr)
            return 2
        c.publish()
    else:
        print("Local staging only; no Git changes or push.", flush=True)
    return 2 if missing else 0

if __name__ == "__main__":
    sys.exit(main())
