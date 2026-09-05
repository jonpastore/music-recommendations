import unittest

from app.tidal import verification_url


class TidalLoginTests(unittest.TestCase):
    def test_adds_https_to_a_scheme_less_device_link(self):
        self.assertEqual("https://link.tidal.com/POUY", verification_url("link.tidal.com/POUY"))

from datetime import datetime, timezone
from app.tidal import session_data_for_storage, expiry_time_from_storage


class TidalSessionStorageTests(unittest.TestCase):
    def test_round_trips_an_oauth_expiry_datetime_as_json_safe_iso_text(self):
        expiry = datetime(2026, 9, 5, 19, 0, tzinfo=timezone.utc)
        payload = session_data_for_storage("Bearer", "access", "refresh", expiry)

        self.assertEqual("2026-09-05T19:00:00+00:00", payload["expiry_time"])
        self.assertEqual(expiry, expiry_time_from_storage(payload["expiry_time"]))
