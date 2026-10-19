#!/usr/bin/env python3
"""Download daily Garmin Wellness ZIP but archive its individual FIT members.

The ZIP is an in-memory transport only for new downloads; previously archived
ZIPs can be converted with --mode import. This program does not write new ZIPs.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from io import BytesIO
import logging
import os
from pathlib import Path
import re
import sys
import time
from zipfile import BadZipFile, ZipFile
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
LOG = logging.getLogger("garmin_wellness_raw")
KST = ZoneInfo("Asia/Seoul")
MAX_ARCHIVE = 150 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED = 500 * 1024 * 1024
MAX_MEMBER = 100 * 1024 * 1024
MAX_MEMBERS = 2000
FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.fit$", re.IGNORECASE)


def arguments():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=("api", "import"), required=True)
    p.add_argument("--date", type=date.fromisoformat, help="Wellness day YYYY-MM-DD")
    p.add_argument("--days", type=int, default=3, help="Previously completed days in API mode")
    p.add_argument("--import-file", type=Path, help="Existing Garmin Wellness ZIP")
    p.add_argument("--pause", type=float, default=3.0)
    p.add_argument("--probe", action="store_true", help="Verify ZIP only, without saving")
    return p.parse_args()


def fit_valid(data: bytes) -> bool:
    if len(data) < 14 or data[0] not in (12, 14) or data[8:12] != b".FIT":
        return False
    data_size = int.from_bytes(data[4:8], "little")
    return data[0] + data_size + 2 <= len(data)


def inspect_zip(raw: bytes):
    if not 0 < len(raw) <= MAX_ARCHIVE:
        raise ValueError("Invalid Wellness ZIP size")
    try:
        with ZipFile(BytesIO(raw)) as archive:
            entries = [x for x in archive.infolist() if not x.is_dir()]
            if len(entries) > MAX_MEMBERS:
                raise ValueError("Too many ZIP entries")
            if sum(x.file_size for x in entries) > MAX_TOTAL_UNCOMPRESSED:
                raise ValueError("Wellness ZIP uncompressed size too large")
            fit_entries = [x for x in entries if x.filename.lower().endswith(".fit")]
            if not fit_entries:
                raise ValueError("No FIT files in Wellness ZIP")
            basenames = set()
            for info in fit_entries:
                # Deny paths, traversal and duplicate names before writing.
                name = info.filename
                if ("/" in name or "\\" in name or not FILENAME.fullmatch(name)):
                    raise ValueError("Unsafe FIT filename in ZIP")
                if name.lower() in basenames:
                    raise ValueError("Duplicate FIT filename in ZIP")
                basenames.add(name.lower())
                if info.file_size > MAX_MEMBER:
                    raise ValueError("Oversized FIT file in ZIP")
            if archive.testzip() is not None:
                raise ValueError("ZIP CRC validation failed")
            return [x.filename for x in fit_entries]
    except BadZipFile as exc:
        raise ValueError("Invalid ZIP response") from exc


def atomic_write(target: Path, payload: bytes) -> bool:
    if target.is_file() and target.read_bytes() == payload:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        with temp.open("xb") as stream:
            os.chmod(temp, 0o600)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)
    return True


def archive(day: date, raw: bytes) -> int:
    names = inspect_zip(raw)
    directory = ROOT / "wellness_raw" / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}"
    changed = 0
    with ZipFile(BytesIO(raw)) as bundle:
        for name in names:
            payload = bundle.read(name)
            if not fit_valid(payload):
                raise ValueError(f"Malformed FIT file: {name}")
            if atomic_write(directory / name, payload):
                changed += 1
                LOG.info("SAVED %s", (directory / name).relative_to(ROOT))
    LOG.info("COMPLETE date=%s FITs=%d changed=%d", day, len(names), changed)
    return changed


def main():
    opts = arguments()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not 1 <= opts.days <= 30 or not 0 <= opts.pause <= 60:
        raise SystemExit("--days must be 1..30 and --pause 0..60")
    if opts.mode == "import":
        if not opts.date or not opts.import_file:
            raise SystemExit("--mode import requires --date and --import-file")
        raw = opts.import_file.read_bytes()
        if opts.probe:
            LOG.info("PROBE date=%s files=%s", opts.date, inspect_zip(raw))
        else:
            archive(opts.date, raw)
        return 0

    from garminconnect import Garmin

    tokenstore = Path(os.getenv("GARMIN_TOKEN_DIR", "~/.garminconnect")).expanduser()
    if not (tokenstore / "garmin_tokens.json").is_file():
        raise SystemExit(f"Missing Garmin token store: {tokenstore}")
    client = Garmin()
    client.login(str(tokenstore))
    today = datetime.now(KST).date()
    days = [opts.date] if opts.date else [today - timedelta(days=i) for i in range(1, opts.days + 1)]
    errors = 0
    for day in days:
        try:
            endpoint = f"/download-service/files/wellness/{day.isoformat()}"
            raw = client.download(endpoint)
            if not isinstance(raw, (bytes, bytearray)):
                raise TypeError("Wellness endpoint returned non-binary response")
            if opts.probe:
                fit_names = inspect_zip(bytes(raw))
                LOG.info("PROBE date=%s fit_count=%d files=%s", day, len(fit_names), fit_names[:15])
            else:
                archive(day, bytes(raw))
        except Exception as exc:
            LOG.error("FAILED date=%s type=%s detail=%s", day, type(exc).__name__, str(exc)[:250])
            errors += 1
            lower = type(exc).__name__.lower()
            if any(s in lower for s in ("authentication", "toomanyrequests", "connection")):
                break
        if opts.pause:
            time.sleep(opts.pause)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
