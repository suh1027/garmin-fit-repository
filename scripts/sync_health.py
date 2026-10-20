#!/usr/bin/env python3
"""Download Garmin daily wellness and performance API responses as raw JSON.

Keeps existing Activity FIT collection independent. No credentials are logged.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
import logging
import os
from pathlib import Path
import sys
import time
from zoneinfo import ZoneInfo

from garminconnect import Garmin

ROOT = Path(__file__).resolve().parents[1]
KST = ZoneInfo("Asia/Seoul")
LOG = logging.getLogger("garmin_health")

# API methods are intentionally read-only. 'current' metrics are recorded by
# collection date and not falsely represented as historical daily measurements.
DAILY = {
    "wellness": {
        "sleep": "get_sleep_data",
        "hrv": "get_hrv_data",
        "heart_rate": "get_heart_rates",
        "stress": "get_all_day_stress",
        "body_battery": "get_body_battery",
        "daily_stats": "get_stats",
    },
    "performance": {
        "training_readiness": "get_training_readiness",
    },
}
SNAPSHOTS = {
    "vo2max": "get_max_metrics",
    "training_status": "get_training_status",
    "load_focus": "get_training_four_week_load_balance",
}


def arguments():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--days", type=int, default=7, help="Previous N days plus current day (default: 7)")
    p.add_argument("--pause", type=float, default=1.0, help="Pause seconds between API calls")
    p.add_argument("--no-snapshots", action="store_true", help="Do not collect current performance snapshots")
    return p.parse_args()


def stable_json(data):
    # Garmin API may use dates/decimals. Retain raw JSON structure, no volatile fetch timestamp.
    return (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n").encode("utf-8")


def write_if_changed(path: Path, data) -> bool:
    if data is None or data == {} or data == []:
        return False
    payload = stable_json(data)
    if path.exists() and path.read_bytes() == payload:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temp.open("xb") as stream:
            os.chmod(temp, 0o600)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)
    return True


def fetch(client, method: str, day: str):
    fn = getattr(client, method)
    if method == "get_body_battery":
        return fn(day, day)
    return fn(day)


def main():
    opts = arguments()
    if not 1 <= opts.days <= 365 or not 0 <= opts.pause <= 60:
        raise SystemExit("--days must be 1..365 and --pause must be 0..60")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    today = datetime.now(KST).date()
    tokenstore = Path(os.getenv("GARMIN_TOKEN_DIR", "~/.garminconnect")).expanduser()
    if not (tokenstore / "garmin_tokens.json").is_file():
        raise SystemExit(f"Missing Garmin token store: {tokenstore} (run scripts/auth.py first)")
    client = Garmin()
    client.login(str(tokenstore))

    # GARMIN_SYNC_SNAPSHOT_HISTORY_V2
    snapshot_run_id = datetime.now(KST).strftime('%H%M%S%f')
    changes = errors = unavailable = 0
    blocked = False

    def process(kind: str, metric: str, method: str, day_str: str, base: Path):
        nonlocal changes, errors, unavailable, blocked
        if not hasattr(client, method):
            LOG.warning("UNSUPPORTED method=%s metric=%s (check installed garminconnect version)", method, metric)
            unavailable += 1
            return
        try:
            response = fetch(client, method, day_str)
            path = base / f"{metric}.json"
            if kind == "snapshot" and response not in (None, {}, []):
                write_if_changed(
                    base / "history" / snapshot_run_id / f"{metric}.json",
                    response
                )
            if write_if_changed(path, response):
                changes += 1
                LOG.info("SAVED %s", path.relative_to(ROOT))
            else:
                LOG.info("UNCHANGED_OR_EMPTY %s %s", day_str, metric)
        except Exception as exc:
            n = type(exc).__name__.lower()
            if "notfound" in n:
                unavailable += 1
                LOG.info("NOT_AVAILABLE date=%s metric=%s", day_str, metric)
            else:
                errors += 1
                LOG.error("FAILED date=%s metric=%s error_type=%s", day_str, metric, type(exc).__name__)
                if any(x in n for x in ("authentication", "toomanyrequests", "connection")):
                    blocked = True
        if opts.pause:
            time.sleep(opts.pause)

    # 00:00 KST run: yesterday through N completed days, avoid assigning incomplete
    # today values to a complete daily record. Rescan days for late sync updates.
    for offset in range(0, opts.days + 1):
        date = today - timedelta(days=offset)
        d = date.isoformat()
        for category, metrics in DAILY.items():
            for name, method in metrics.items():
                base = ROOT / category / f"{date:%Y}" / f"{date:%m}" / f"{date:%d}"
                process(category, name, method, d, base)
                if blocked:
                    break
            if blocked:
                break
        if blocked:
            break

    # Performance metrics may be returned as latest aggregate even with a date
    # parameter, so store them by *snapshot capture date*, not falsely backfilled.
    if not opts.no_snapshots and not blocked:
        base = ROOT / "performance" / "snapshots" / f"{today:%Y}" / f"{today:%m}" / f"{today:%d}"
        for name, method in SNAPSHOTS.items():
            process("snapshot", name, method, today.isoformat(), base)
            if blocked:
                break

    LOG.info("Summary changed=%s errors=%s unsupported=%s", changes, errors, unavailable)
    # Unsupported optional fields are not fatal. Real API errors produce nonzero result.
    return 1 if errors or blocked else 0


if __name__ == "__main__":
    sys.exit(main())
