"""Offline tests using a fake Garmin API. Run: python3.12 -m unittest discover -s tests -v"""
import importlib.util
import io
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile
import types

# The tests don't require Garmin login or even the external dependency to be installed.
sys.modules.setdefault('garminconnect', types.SimpleNamespace(Garmin=object))
module_file = Path(__file__).resolve().parents[1] / 'scripts' / 'sync_fit.py'
spec = importlib.util.spec_from_file_location('collector_under_test', module_file)
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


def fit_bytes():
    # 14-byte FIT header + 4-byte content + 2-byte CRC; collector validates layout, not CRC.
    return bytes([14, 0x10]) + (0).to_bytes(2, 'little') + (4).to_bytes(4, 'little') + b'.FIT' + b'\x00\x00' + b'data' + b'\x00\x00'


def zipped_fit():
    buffer = io.BytesIO()
    with ZipFile(buffer, 'w') as z:
        z.writestr('device/ACTIVITY.fit', fit_bytes())
    return buffer.getvalue()


class FakeGarmin:
    class ActivityDownloadFormat:
        ORIGINAL = 1
    downloads = []
    def login(self, token_dir):
        pass
    def get_activities_by_date(self, first, last):
        return [
            {'activityId': 111111, 'startTimeLocal': '2026-10-19 06:20:11'},
            {'activityId': 222222, 'startTimeLocal': '2026-10-19 19:10:00'},
            {'activityId': 333333, 'startTimeGMT': '2026-10-19 15:20:00'},
        ]
    def download_activity(self, activity_id, dl_fmt):
        self.downloads.append(activity_id)
        return zipped_fit()


class CollectorTests(unittest.TestCase):
    def test_archive_dates(self):
        self.assertEqual('2026-10-19', str(collector.archive_date({'startTimeLocal':'2026-10-19 06:20:00'})))
        # UTC 15:20 = Korea 00:20 next day
        self.assertEqual('2026-10-20', str(collector.archive_date({'startTimeGMT':'2026-10-19 15:20:00'})))
        with self.assertRaises(ValueError):
            collector.archive_date({})

    def test_fit_payload_zip(self):
        self.assertEqual(fit_bytes(), collector.original_to_fit(zipped_fit()))
        self.assertTrue(collector.fit_valid(fit_bytes()))
        self.assertFalse(collector.fit_valid(b'invalid data'))

    def test_same_day_and_legacy_migrate_without_redownload(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / 'repo'
            repo.mkdir()
            tok = Path(temp) / 'tokens'
            tok.mkdir()
            (tok / 'garmin_tokens.json').write_text('fake')
            legacy = repo / 'activities/2026/10/111111.fit'
            legacy.parent.mkdir(parents=True)
            legacy.write_bytes(fit_bytes())
            FakeGarmin.downloads = []
            args = ['sync_fit.py', '--since', '2026-10-19', '--until', '2026-10-20', '--pause', '0']
            with patch.object(collector, 'REPO', repo), patch.object(collector, 'Garmin', FakeGarmin), \
                 patch.dict(os.environ, {'GARMIN_TOKEN_DIR': str(tok)}), patch.object(sys, 'argv', args):
                self.assertEqual(0, collector.main())
                self.assertFalse(legacy.exists())
                self.assertTrue((repo / 'activities/2026/10/19/111111.fit').exists())
                self.assertTrue((repo / 'activities/2026/10/19/222222.fit').exists())
                self.assertTrue((repo / 'activities/2026/10/20/333333.fit').exists())
                self.assertEqual([222222, 333333], FakeGarmin.downloads)
                # Idempotent: no more downloads on repeat.
                self.assertEqual(0, collector.main())
                self.assertEqual([222222, 333333], FakeGarmin.downloads)


if __name__ == '__main__':
    unittest.main()
