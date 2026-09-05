import unittest

from app.tidal import verification_url


class TidalLoginTests(unittest.TestCase):
    def test_adds_https_to_a_scheme_less_device_link(self):
        self.assertEqual("https://link.tidal.com/POUY", verification_url("link.tidal.com/POUY"))
