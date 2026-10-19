#!/usr/bin/env python3
"""Incrementally archive Garmin Connect original FIT files (or original ZIPs)."""
import argparse
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, BadZipFile
import logging
import os
import re
import sys
import time
from zoneinfo import ZoneInfo

from garminconnect import Garmin

REPO = Path(__file__).resolve().parents[1]
LOGGER = logging.getLogger('garmin_fit_sync')
ID_RE = re.compile(r'^\d+$')
MAX_UNCOMPRESSED_FIT = 100 * 1024 * 1024


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--days', type=int, default=30, help='Rolling lookback in days (default: 30).')
    parser.add_argument('--since', type=date.fromisoformat, help='Historical backfill from YYYY-MM-DD.')
    parser.add_argument('--until', type=date.fromisoformat, help='Last date, YYYY-MM-DD (default: today in Asia/Seoul).')
    parser.add_argument('--format', choices=('fit', 'zip'), default='fit', help='Archive FIT or unmodified Garmin original ZIP.')
    parser.add_argument('--max-downloads', type=int, default=0, help='Limit for initial test, 0 means unlimited.')
    parser.add_argument('--pause', type=float, default=3.0, help='Seconds to wait after each download.')
    return parser.parse_args()


def monthly_chunks(first, last):
    """Limit query windows to 30 days; avoids a single giant history query."""
    cur = first
    while cur <= last:
        end = min(cur + timedelta(days=29), last)
        yield cur, end
        cur = end + timedelta(days=1)


def fit_valid(data):
    if len(data) < 14:
        return False
    header_size = data[0]
    if header_size not in (12, 14) or data[8:12] != b'.FIT':
        return False
    data_size = int.from_bytes(data[4:8], 'little')
    return header_size + data_size <= len(data)


def original_to_fit(zip_data):
    try:
        with ZipFile(BytesIO(zip_data)) as archive:
            candidates = [x for x in archive.infolist() if not x.is_dir() and x.filename.lower().endswith('.fit')]
            if len(candidates) != 1:
                raise ValueError(f'Expected one FIT member in Garmin original ZIP, found {len(candidates)}')
            member = candidates[0]
            if member.file_size > MAX_UNCOMPRESSED_FIT:
                raise ValueError(f'FIT member exceeds {MAX_UNCOMPRESSED_FIT} bytes')
            payload = archive.read(member)
    except BadZipFile as exc:
        raise ValueError('Garmin returned invalid original ZIP') from exc
    if not fit_valid(payload):
        raise ValueError('FIT header/payload validation failed')
    return payload


def atomic_save(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
    try:
        with tmp.open('xb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def existing_file_valid(path, file_format):
    if not path.is_file():
        return False
    if file_format == 'fit':
        return fit_valid(path.read_bytes())
    try:
        with ZipFile(path) as archive:
            return archive.testzip() is None
    except BadZipFile:
        return False


def archive_date(activity):
    """Prefer the activity's own local date, not VM time or query-window start.

    If Garmin omits startTimeLocal, convert startTimeGMT from UTC to Korea.
    Never guess a date when both timestamps are missing.
    """
    local = activity.get('startTimeLocal')
    if isinstance(local, str) and len(local) >= 10:
        try:
            return date.fromisoformat(local[:10])
        except ValueError:
            pass

    gmt = activity.get('startTimeGMT')
    if isinstance(gmt, str):
        try:
            timestamp = datetime.fromisoformat(gmt.replace('Z', '+00:00'))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            return timestamp.astimezone(ZoneInfo('Asia/Seoul')).date()
        except ValueError:
            pass

    raise ValueError('Missing or invalid startTimeLocal/startTimeGMT')


def main():
    opts = arguments()
    if opts.days < 1 or opts.pause < 0 or opts.max_downloads < 0:
        raise SystemExit('--days must be >=1; --pause and --max-downloads must be >=0')
    today = datetime.now(ZoneInfo('Asia/Seoul')).date()
    last = opts.until or today
    first = opts.since or (last - timedelta(days=opts.days))
    if first > last:
        raise SystemExit('--since must not be after --until')

    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    token_dir = Path(os.getenv('GARMIN_TOKEN_DIR', '~/.garminconnect')).expanduser()
    if not (token_dir / 'garmin_tokens.json').is_file():
        raise SystemExit(f'Garmin token not found in {token_dir}. Run scripts/auth.py interactively first.')

    client = Garmin()
    client.login(str(token_dir))
    downloads = 0
    seen = set()
    errors = 0
    LOGGER.info('Archive window=%s..%s format=%s layout=YYYY/MM/DD', first, last, opts.format)
    for start, end in monthly_chunks(first, last):
        activities = client.get_activities_by_date(start.isoformat(), end.isoformat())
        LOGGER.info('Activities queried %s..%s: %d', start, end, len(activities))
        for activity in activities:
            activity_id = str(activity.get('activityId', ''))
            if not ID_RE.fullmatch(activity_id):
                LOGGER.warning('Unexpected activity id (skipped)')
                errors += 1
                continue
            if activity_id in seen:
                continue
            seen.add(activity_id)
            try:
                d = archive_date(activity)
            except ValueError:
                LOGGER.error('Missing activity date for %s; skipping, not misfiling', activity_id)
                errors += 1
                continue
            month_dir = REPO / 'activities' / f'{d.year:04d}' / f'{d.month:02d}'
            target = month_dir / f'{d.day:02d}' / f'{activity_id}.{opts.format}'
            legacy = month_dir / f'{activity_id}.{opts.format}'

            if existing_file_valid(target, opts.format):
                # Clean up a redundant pre-v2 monthly file if it exists.
                if existing_file_valid(legacy, opts.format):
                    legacy.unlink()
                    LOGGER.info('Removed duplicate legacy file: %s', legacy.relative_to(REPO))
                continue
            if target.exists():
                LOGGER.warning('Invalid archive %s - replacing', target.relative_to(REPO))

            # Existing v1 archives can be relocated without contacting Garmin.
            if existing_file_valid(legacy, opts.format):
                target.parent.mkdir(parents=True, exist_ok=True)
                legacy.replace(target)
                LOGGER.info('Moved legacy monthly file: %s -> %s',
                            legacy.relative_to(REPO), target.relative_to(REPO))
                continue
            try:
                zip_data = client.download_activity(
                    int(activity_id), dl_fmt=client.ActivityDownloadFormat.ORIGINAL
                )
                if not isinstance(zip_data, (bytes, bytearray)):
                    raise TypeError('Garmin download did not return bytes')
                if opts.format == 'fit':
                    payload = original_to_fit(zip_data)
                else:
                    with ZipFile(BytesIO(zip_data)) as z:
                        if z.testzip() is not None:
                            raise ValueError('Original ZIP CRC failed')
                    payload = bytes(zip_data)
                atomic_save(target, payload)
                downloads += 1
                LOGGER.info('Saved: %s (%d bytes)', target.relative_to(REPO), len(payload))
                if opts.pause:
                    time.sleep(opts.pause)
            except Exception as exc:
                LOGGER.error('Download failed for activity %s: %s', activity_id, type(exc).__name__)
                LOGGER.debug('Download detail', exc_info=True)
                errors += 1
                # Avoid repeated requests when an account is blocked or rate limited.
                name = type(exc).__name__.lower()
                if any(x in name for x in ('authentication', 'toomanyrequests', 'connection')):
                    LOGGER.error('Authentication / rate-limit / connection error; ending collection')
                    LOGGER.info('Summary: downloaded=%d errors=%d', downloads, errors)
                    return 1
            if opts.max_downloads and downloads >= opts.max_downloads:
                LOGGER.info('Reached test limit --max-downloads=%d', opts.max_downloads)
                LOGGER.info('Summary: downloaded=%d errors=%d', downloads, errors)
                return 1 if errors else 0
    LOGGER.info('Summary: downloaded=%d errors=%d', downloads, errors)
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
