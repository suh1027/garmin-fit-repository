"""Offline tests with a fake garminconnect module; no account, network or tokens."""
from __future__ import annotations
import importlib.util
from io import BytesIO
from pathlib import Path
import sys
import tempfile
import types
import unittest
from zipfile import ZipFile

sys.modules.setdefault('garminconnect', types.SimpleNamespace(Garmin=object))
SRC = Path(__file__).resolve().parents[1] / 'scripts'


def load(name):
    spec = importlib.util.spec_from_file_location(name, SRC / (name + '.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


h = load('sync_health')
w = load('sync_wellness_raw')


class TestExtension(unittest.TestCase):
    def test_raw_json_saved_only_when_changed(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'wellness' / '2026' / '10' / '19' / 'hrv.json'
            self.assertTrue(h.write_if_changed(p, {'hrv': 60, 'date': '2026-10-19'}))
            self.assertFalse(h.write_if_changed(p, {'date': '2026-10-19', 'hrv': 60}))
            self.assertTrue(h.write_if_changed(p, {'hrv': 61}))

    def test_empty_response_not_written(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'sleep.json'
            self.assertFalse(h.write_if_changed(p, None))
            self.assertFalse(h.write_if_changed(p, {}))
            self.assertFalse(p.exists())

    def test_body_battery_date_range_api(self):
        class Fake:
            def get_body_battery(self, start, end):
                return [start, end]
        self.assertEqual(h.fetch(Fake(), 'get_body_battery', '2026-10-19'), ['2026-10-19'] * 2)

    def test_zip_fit_presence(self):
        bio = BytesIO()
        with ZipFile(bio, 'w') as z:
            z.writestr('20261019_WELLNESS.fit', b'fake fit for archive validation test')
        self.assertEqual(len(w.validate_zip(bio.getvalue())), 1)
        with self.assertRaises(ValueError):
            w.validate_zip(b'not a zip')

    def test_archive_idempotent(self):
        bio = BytesIO()
        with ZipFile(bio, 'w') as z:
            z.writestr('123_WELLNESS.fit', b'FIT TEST')
        with tempfile.TemporaryDirectory() as d:
            prior = w.ROOT
            try:
                w.ROOT = Path(d)
                from datetime import date
                day = date(2026, 10, 19)
                self.assertTrue(w.archive(day, bio.getvalue()))
                self.assertFalse(w.archive(day, bio.getvalue()))
                self.assertTrue((Path(d) / 'wellness_raw/2026/10/19/wellness_original.zip').exists())
            finally:
                w.ROOT = prior


if __name__ == '__main__':
    unittest.main()
