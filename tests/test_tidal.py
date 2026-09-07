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

import json
import tempfile
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient
from app import main


class TidalPersistenceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name)
        for target, value in [('CONFIG_DIR', self.path), ('tidal_session', None), ('tidal_login', None)]:
            p = patch.object(main, target, value); p.start(); self.addCleanup(p.stop)
        for name in ['tidal_pending_session', 'tidal_login_details']:
            p = patch.object(main, name, None, create=True); p.start(); self.addCleanup(p.stop)
        self.client = TestClient(main.app)
        self.session = Mock(token_type='Bearer', access_token='new-access', refresh_token='refresh',
                            expiry_time=datetime(2027, 1, 1), is_pkce=False)
        self.session.check_login.return_value = True
        self.session.load_oauth_session.return_value = True

    def seed(self):
        main.save_tidal_session(self.session)

    def test_session_file_is_private(self):
        self.seed()
        self.assertEqual(0o600, (self.path/'tidal-session.json').stat().st_mode & 0o777)

    def test_restored_refreshed_credentials_are_persisted_for_next_restart(self):
        self.seed()
        self.session.access_token = 'refreshed-access'
        with patch('app.main.tidalapi.Session', return_value=self.session):
            main.load_tidal_session()
        self.assertEqual('refreshed-access', json.loads((self.path/'tidal-session.json').read_text())['access_token'])

    def test_connect_reuses_valid_saved_session_without_new_device_authorization(self):
        self.seed()
        with patch('app.main.tidalapi.Session', return_value=self.session):
            response=self.client.post('/api/tidal/login')
        self.assertEqual(200,response.status_code)
        self.assertTrue(response.json()['complete'])
        self.session.login_oauth.assert_not_called()

    def test_finish_keeps_pending_session_separate_from_playlist_reads(self):
        pending=Mock(token_type='Bearer',access_token='pending-access',refresh_token='pending-refresh',expiry_time=None,is_pkce=False)
        main.tidal_session=self.session
        main.tidal_pending_session=pending
        main.tidal_login=Future();main.tidal_login.set_result(True)
        response=self.client.post('/api/tidal/login/complete')
        self.assertEqual({'complete':True},response.json())
        self.assertEqual('pending-access',json.loads((self.path/'tidal-session.json').read_text())['access_token'])
        self.assertIsNone(main.tidal_login)

    def test_logout_forgets_saved_and_pending_credentials_and_is_repeatable(self):
        self.seed();main.tidal_session=self.session
        main.tidal_pending_session=self.session;main.tidal_login=Future()
        for _ in range(2):
            response=self.client.post('/api/tidal/logout')
            self.assertEqual(200,response.status_code)
        self.assertFalse((self.path/'tidal-session.json').exists())
        self.assertIsNone(main.tidal_session);self.assertIsNone(main.tidal_login)
        self.assertIsNone(main.tidal_pending_session)
        self.assertFalse(self.client.get('/api/status').json()['tidal_session'])

    def test_failed_authorization_does_not_report_complete_or_overwrite_saved_login(self):
        self.seed();main.tidal_session=self.session
        main.tidal_pending_session=Mock();main.tidal_login=Future()
        main.tidal_login.set_exception(RuntimeError('secret-provider-details'))
        response=self.client.post('/api/tidal/login/complete')
        self.assertEqual(502,response.status_code)
        self.assertNotIn('secret-provider-details',response.text)
        self.assertEqual('new-access',json.loads((self.path/'tidal-session.json').read_text())['access_token'])

    def test_pending_login_is_reused_and_never_claims_completion_early(self):
        future=Future()
        self.session.login_oauth.return_value=(Mock(verification_uri_complete='link.tidal.com/TEST'),future)
        with patch('app.main.tidalapi.Session',return_value=self.session):
            first=self.client.post('/api/tidal/login').json()
            second=self.client.post('/api/tidal/login').json()
        self.assertEqual(first,second)
        self.session.login_oauth.assert_called_once()
        self.assertEqual({'complete':False},self.client.post('/api/tidal/login/complete').json())
        self.assertFalse((self.path/'tidal-session.json').exists())

    def test_playlist_request_cannot_restore_credentials_after_logout(self):
        self.seed();main.tidal_session=self.session
        self.client.post('/api/tidal/logout')
        main.persist_active_tidal_session(self.session)
        self.assertFalse((self.path/'tidal-session.json').exists())

    def test_refreshed_live_session_is_saved(self):
        self.seed();main.tidal_session=self.session
        self.session.access_token='rotated-live-token'
        main.load_tidal_session()
        self.assertEqual('rotated-live-token',json.loads((self.path/'tidal-session.json').read_text())['access_token'])

    def test_revoked_credentials_prompt_reconnect_without_provider_details(self):
        self.seed()
        self.session.load_oauth_session.side_effect=main.tidalapi.exceptions.AuthenticationError('secret-provider-details')
        with patch('app.main.tidalapi.Session',return_value=self.session):
            response=self.client.get('/api/tidal/playlists')
        self.assertEqual(401,response.status_code)
        self.assertIn('Connect TIDAL',response.json()['detail'])
        self.assertNotIn('secret-provider-details',response.text)

    def test_unsuccessful_completed_future_does_not_save_or_report_success(self):
        main.tidal_pending_session=self.session;main.tidal_login=Future()
        main.tidal_login.set_result(False)
        response=self.client.post('/api/tidal/login/complete')
        self.assertEqual(502,response.status_code)
        self.assertFalse((self.path/'tidal-session.json').exists())
