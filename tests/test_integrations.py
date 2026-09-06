import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.main import app


class IntegrationRoutesTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        for target, value in [("app.main.CONFIG_DIR", self.directory), ("app.main.settings", {})]:
            mock = patch(target, return_value=value) if target.endswith('settings') else patch(target, value)
            mock.start()
            self.addCleanup(mock.stop)
        self.client = TestClient(app)

    def test_provider_status_contains_configuration_flags_without_credentials(self):
        data = self.client.get('/api/status').json()
        self.assertIn('spotify', data['sources'])
        self.assertIn('youtube_music', data['sources'])
        self.assertIn('pandora', data['sources'])
        self.assertFalse(data['sources']['spotify']['connected'])

    def test_missing_provider_credentials_are_readable_errors(self):
        for path, message in [('/api/spotify/playlists', 'SPOTIFY_CLIENT_ID'),
                              ('/api/youtube_music/playlists', 'Connect YouTube Music'),
                              ('/api/pandora/history', 'LISTENBRAINZ_USERNAME')]:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(400, response.status_code)
                self.assertIn(message, response.json()['detail'])

    @patch('app.spotify.Spotify.complete_login')
    def test_spotify_rejects_callback_without_browser_state(self, complete):
        response = self.client.get('/api/spotify/callback?state=forged&code=secret')
        self.assertEqual(400, response.status_code)
        complete.assert_not_called()

    @patch('app.spotify.Spotify.complete_login')
    @patch('app.main.settings')
    def test_spotify_browser_bound_callback_is_single_use(self, settings, complete):
        settings.return_value = {'SPOTIFY_CLIENT_ID': 'id', 'SPOTIFY_CLIENT_SECRET': 'secret',
                                 'SPOTIFY_REDIRECT_URI': 'http://127.0.0.1:8090/api/spotify/callback'}
        from urllib.parse import urlsplit, parse_qs
        start = self.client.post('/api/spotify/login')
        self.assertEqual(200, start.status_code)
        state = parse_qs(urlsplit(start.json()['authorization_url']).query)['state'][0]
        foreign = TestClient(app)
        self.assertEqual(400, foreign.get('/api/spotify/callback', params={'state': state, 'code': 'code'}).status_code)
        response = self.client.get('/api/spotify/callback', params={'state': state, 'code': 'code'})
        self.assertEqual(200, response.status_code)
        complete.assert_called_once_with('code')
        self.assertEqual(400, self.client.get('/api/spotify/callback', params={'state': state, 'code': 'code'}).status_code)

    @patch('app.youtube.YouTubeMusic.credentials')
    def test_youtube_pending_then_success_persists_private_token(self, credentials):
        credentials.return_value.get_code.return_value = {'device_code': 'private-device', 'user_code': 'ABCD',
                                                          'verification_url': 'https://google.com/device', 'expires_in': 600, 'interval': 5}
        start = self.client.post('/api/youtube_music/login')
        self.assertEqual(200, start.status_code)
        self.assertNotIn('private-device', start.text)
        credentials.return_value.token_from_code.return_value = {'error': 'authorization_pending'}
        self.assertFalse(self.client.post('/api/youtube_music/login/complete').json()['complete'])
        from app.integrations import youtube_pending
        for pending in youtube_pending.values():
            pending['next_poll'] = 0
        credentials.return_value.token_from_code.return_value = {'access_token': 'access', 'refresh_token': 'refresh',
                                                               'expires_in': 3600, 'token_type': 'Bearer', 'scope': 'youtube'}
        self.assertTrue(self.client.post('/api/youtube_music/login/complete').json()['complete'])
        self.assertEqual(0o600, (self.directory / 'youtube-music-session.json').stat().st_mode & 0o777)

    @patch('app.main.requests.post')
    def test_playlist_listens_require_confirmation_and_time(self, post):
        data = {'playlist_name': 'Mix', 'playlist_url': 'https://open.spotify.com/playlist/abc', 'source': 'spotify',
                'tracks': [{'title': 'Song', 'artist': 'Artist'}]}
        response = self.client.post('/api/recommendations', json=data)
        self.assertEqual(400, response.status_code)
        self.assertIn('confirm', response.json()['detail'].lower())
        post.assert_not_called()

    @patch('app.main.settings')
    def test_secure_oauth_cookie_can_be_forced_behind_https_proxy(self, settings):
        settings.return_value = {'SPOTIFY_CLIENT_ID': 'id', 'SPOTIFY_CLIENT_SECRET': 'secret',
                                 'SPOTIFY_REDIRECT_URI': 'https://bridge.example/api/spotify/callback',
                                 'OAUTH_COOKIE_SECURE': 'true'}
        response = self.client.post('/api/spotify/login')
        self.assertIn('Secure', response.headers['set-cookie'])
