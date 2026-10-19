#!/usr/bin/env python3
"""Archive daily Garmin Wellness ZIP bundles.

Read-only automatic API mode is experimental and disabled in the scheduled
wrapper by default. Offline --import-file is the reliable manual fallback.
"""
from __future__ import annotations
import argparse
from datetime import date, datetime, timedelta
from io import BytesIO
import logging
import os
from pathlib import Path
import sys
import time
from zipfile import ZipFile, BadZipFile
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
LOG = logging.getLogger("garmin_wellness_raw")
MAX_ARCHIVE = 150 * 1024 * 1024
KST = ZoneInfo("Asia/Seoul")


def arguments():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=("api", "import"), required=True)
    p.add_argument("--date", type=date.fromisoformat, help="Wellness bundle date YYYY-MM-DD")
    p.add_argument("--days", type=int, default=2, help="Previous completed days for API mode")
    p.add_argument("--import-file", type=Path, help="ZIP exported manually from Garmin Connect")
    p.add_argument("--pause", type=float, default=3.0)
    p.add_argument("--probe", action="store_true", help="Download and inspect ZIP without saving (API mode)")
    return p.parse_args()


def validate_zip(raw: bytes):
    if not 0 < len(raw) <= MAX_ARCHIVE:
        raise ValueError("Invalid Wellness ZIP size")
    try:
        with ZipFile(BytesIO(raw)) as archive:
            if archive.testzip() is not None:
                raise ValueError("Wellness ZIP failed CRC validation")
            members = [e.filename for e in archive.infolist() if not e.is_dir()]
            fit_names = [n for n in members if n.lower().endswith(".fit")]
            if not fit_names:
                raise ValueError("ZIP has no FIT files; endpoint may be unsupported or changed")
            if len(members) > 2000 or sum(i.file_size for i in archive.infolist()) > 500 * 1024 * 1024:
                raise ValueError("Unexpected ZIP decompressed size / member count")
            return fit_names
    except BadZipFile as exc:
        raise ValueError("Response is not ZIP") from exc


def archive(day: date, raw: bytes):
    fits = validate_zip(raw)
    path = ROOT / "wellness_raw" / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}" / "wellness_original.zip"
    if path.exists() and path.read_bytes() == raw:
        LOG.info("UNCHANGED %s FITs=%d", path.relative_to(ROOT), len(fits))
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temp.open("xb") as output:
            os.chmod(temp, 0o600)
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)
    LOG.info("SAVED %s FITs=%d bytes=%d", path.relative_to(ROOT), len(fits), len(raw))
    return True


def main():
    opts = arguments()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not 1 <= opts.days <= 30 or not 0 <= opts.pause <= 60:
        raise SystemExit("--days must be 1..30 and --pause 0..60")
    if opts.mode == "import":
        if not opts.date or not opts.import_file:
            raise SystemExit("--mode import requires --date and --import-file")
        archive(opts.date, opts.import_file.read_bytes())
        return 0

    # Unofficial endpoint seen in open-source download implementations. It may
    # stop working without notice; never treat Health Snapshot as proof that the
    # full daily Wellness export is correct. Inspect the ZIP member names.
    from garminconnect import Garmin
    tokenstore = Path(os.getenv("GARMIN_TOKEN_DIR", "~/.garminconnect")).expanduser()
    if not (tokenstore / "garmin_tokens.json").is_file():
        raise SystemExit(f"Missing token store: {tokenstore}")
    client = Garmin()
    client.login(str(tokenstore))
    today = datetime.now(KST).date()
    days = [opts.date] if opts.date else [today - timedelta(days=i) for i in range(1, opts.days + 1)]
    errors = 0
    for day in days:
        try:
            # Experiment: /download-service/files/wellness/YYYY-MM-DD
            endpoint = f"/download-service/files/wellness/{day.isoformat()}"
            raw = client.download(endpoint)
            if not isinstance(raw, (bytes, bytearray)):
                raise TypeError("Wellness endpoint did not return binary content")
            if opts.probe:
                fit_names = validate_zip(bytes(raw))
                LOG.info("PROBE date=%s fit_count=%d files=%s", day, len(fit_names), fit_names[:15])
                LOG.info("Compare the FIT file types with Garmin's manual Export Wellness Data ZIP before enabling scheduled import.")
            else:
                archive(day, bytes(raw))
        except Exception as exc:
            LOG.error("FAILED date=%s reason=%s", day, type(exc).__name__)
            errors += 1
            n = type(exc).__name__.lower()
            if any(x in n for x in ("authentication", "toomanyrequests", "connection")):
                break
        if opts.pause:
            time.sleep(opts.pause)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
