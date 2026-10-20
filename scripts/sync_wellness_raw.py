#!/usr/bin/env python3
"""Archive daily Garmin Wellness ZIP contents as separate, verified FIT files.

Garmin returns a ZIP archive for each requested day. This collector DOES NOT
store the ZIP in the Git working tree; each FIT becomes a separate file under
wellness_raw/YYYY/MM/DD/<original_name>.fit.

Both API download and import of an existing ZIP are supported. --probe only
checks the ZIP and never writes files.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from io import BytesIO
import logging
import os
from pathlib import Path, PurePosixPath
import re
import sys
import time
from zipfile import ZipFile, BadZipFile
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
LOG = logging.getLogger("garmin_wellness_fit")
KST = ZoneInfo("Asia/Seoul")
MAX_ZIP_BYTES = 150 * 1024 * 1024
MAX_FIT_BYTES = 100 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED = 500 * 1024 * 1024
MAX_ENTRIES = 2000
FIT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,200}\.fit$", re.IGNORECASE)


def arguments():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=("api", "import"), required=True)
    p.add_argument("--date", type=date.fromisoformat, help="Archive date YYYY-MM-DD")
    p.add_argument("--days", type=int, default=3, help="Previous completed calendar days in API mode")
    p.add_argument("--import-file", type=Path, help="Previously downloaded Garmin Wellness ZIP")
    p.add_argument("--pause", type=float, default=3.0, help="Delay between API days")
    p.add_argument("--probe", action="store_true", help="Inspect ZIP without saving")
    return p.parse_args()


def fit_valid(payload: bytes) -> bool:
    """FIT header/length sanity check; not a full FIT CRC/developer-field parser."""
    if len(payload) < 14:
        return False
    header_size = payload[0]
    if header_size not in (12, 14) or payload[8:12] != b".FIT":
        return False
    data_size = int.from_bytes(payload[4:8], "little")
    return header_size + data_size + 2 <= len(payload)


def safe_fit_filename(archive_name: str) -> str:
    """Flatten safe nested ZIP names; reject traversal or dangerous names."""
    if not archive_name or "\\" in archive_name or archive_name.startswith("/"):
        raise ValueError("Unsafe ZIP member path")
    parts = PurePosixPath(archive_name).parts
    if any(part in ("", ".", "..") or ":" in part for part in parts):
        raise ValueError("Unsafe ZIP member path")
    filename = parts[-1]
    if not FIT_NAME.fullmatch(filename):
        raise ValueError("Unsupported FIT filename")
    return filename


def extract_fit_members(raw: bytes) -> dict[str, bytes]:
    """Fully validate, bound memory, and return unique FIT filenames + bytes."""
    if not (0 < len(raw) <= MAX_ZIP_BYTES):
        raise ValueError("Unexpected Garmin Wellness ZIP size")
    try:
        with ZipFile(BytesIO(raw)) as archive:
            infos = [info for info in archive.infolist() if not info.is_dir()]
            if not infos or len(infos) > MAX_ENTRIES:
                raise ValueError("Unexpected member count")
            if sum(info.file_size for info in infos) > MAX_TOTAL_UNCOMPRESSED:
                raise ValueError("ZIP uncompressed size exceeds limit")
            bad = archive.testzip()
            if bad is not None:
                raise ValueError("Wellness ZIP CRC validation failed")
            members: dict[str, bytes] = {}
            for info in infos:
                if not info.filename.lower().endswith(".fit"):
                    continue
                name = safe_fit_filename(info.filename)
                if name in members:
                    raise ValueError(f"Duplicate FIT filename: {name}")
                if not (0 < info.file_size <= MAX_FIT_BYTES):
                    raise ValueError(f"FIT member size out of range: {name}")
                payload = archive.read(info)
                if not fit_valid(payload):
                    raise ValueError(f"Invalid FIT header or size: {name}")
                members[name] = payload
    except BadZipFile as exc:
        raise ValueError("Garmin Wellness response is not a valid ZIP") from exc
    if not members:
        raise ValueError("Wellness ZIP contains no FIT members")
    return members


def validate_zip(raw: bytes) -> list[str]:
    """Compatibility with earlier --probe test call: returns FIT filenames."""
    return list(extract_fit_members(raw))


def save_if_changed(target: Path, payload: bytes) -> bool:
    if target.exists() and target.is_file() and target.read_bytes() == payload:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        with temp.open("xb") as output:
            os.chmod(temp, 0o600)
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)
    return True


def archive(day: date, raw: bytes) -> tuple[int, int]:
    """Extract archive to per-day .fit files. Never writes wellness_original.zip."""
    members = extract_fit_members(raw)
    directory = ROOT / "wellness_raw" / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}"
    saved = 0
    for filename, payload in members.items():
        target = directory / filename
        if save_if_changed(target, payload):
            saved += 1
            LOG.info("SAVED %s (%d bytes)", target.relative_to(ROOT), len(payload))
    LOG.info("FIT date=%s total=%d saved_or_updated=%d unchanged=%d", day,
             len(members), saved, len(members) - saved)
    return saved, len(members)


def main() -> int:
    opts = arguments()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not 1 <= opts.days <= 30 or not 0 <= opts.pause <= 60:
        raise SystemExit("--days must be 1..30 and --pause 0..60")
    if opts.mode == "import":
        if not opts.date or not opts.import_file:
            raise SystemExit("--mode import requires --date and --import-file")
        raw = opts.import_file.read_bytes()
        if opts.probe:
            LOG.info("PROBE date=%s fit_count=%d files=%s", opts.date,
                     len(validate_zip(raw)), validate_zip(raw))
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
    days = [opts.date] if opts.date else [today - timedelta(days=i)
                                             for i in range(0, opts.days + 1)]
    errors = 0
    for day in days:
        try:
            raw = client.download(f"/download-service/files/wellness/{day.isoformat()}")
            if not isinstance(raw, (bytes, bytearray)):
                raise TypeError("Wellness download returned non-binary content")
            if opts.probe:
                names = validate_zip(bytes(raw))
                LOG.info("PROBE date=%s fit_count=%d files=%s", day, len(names), names)
            else:
                archive(day, bytes(raw))
        except Exception as exc:
            # GARMIN_SYNC_PENDING_V2
            err_text = str(exc).lower()
            err_name = type(exc).__name__.lower()
            if day == today and (
                'notfound' in err_name
                or 'not found' in err_text
                or '404' in err_text
            ):
                LOG.info(
                    'PENDING date=%s: Wellness ZIP not available yet',
                    day
                )
                continue
            LOG.error("FAILED date=%s type=%s message=%s", day,
                      type(exc).__name__, str(exc)[:180])
            errors += 1
            if any(token in type(exc).__name__.lower() for token in
                   ("authentication", "toomanyrequests", "connection")):
                break
        if opts.pause:
            time.sleep(opts.pause)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
