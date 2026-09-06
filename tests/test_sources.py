import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.spotify import Spotify
from app.youtube import YouTubeMusic
from app.pandora import Pandora
from app.providers import ProviderError


def response(data, status=200):
    return Mock(status_code=status, json=Mock(return_value=data), headers={})


class SpotifyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        self.client = Spotify({"SPOTIFY_CLIENT_ID": "client", "SPOTIFY_CLIENT_SECRET": "secret",
                               "SPOTIFY_REFRESH_TOKEN": "refresh"}, self.directory)

    @patch("app.spotify.requests.post")
    @patch("app.spotify.requests.get")
    def test_playlist_pages_use_current_items_endpoint_and_skip_unavailable_tracks(self, get, post):
        post.return_value = response({"access_token": "access", "expires_in": 3600, "refresh_token": "rotated"})
        get.side_effect = [response({"name": "Mix"}), response({"items": [
            {"item": {"type": "track", "name": "One", "artists": [{"name": "Artist"}], "album": {"name": "Album"}, "duration_ms": 2000}},
            {"item": None}, {"item": {"type": "episode", "name": "Podcast"}},
        ], "next": "https://api.spotify.com/v1/playlists/abc/items?offset=3"}), response({"items": [
            {"track": {"type": "track", "name": "Two", "artists": [{"name": "Other"}]}}
        ], "next": None})]
        result = self.client.playlist("abc")
        self.assertEqual(["One", "Two"], [t["title"] for t in result["tracks"]])
        self.assertEqual("spotify", result["source"])
        self.assertEqual("https://open.spotify.com/playlist/abc", result["url"])
        self.assertEqual(2, result["skipped"])
        self.assertEqual("https://api.spotify.com/v1/playlists/abc/items", get.call_args_list[1].args[0])
        token_path = self.directory / "spotify-session.json"
        self.assertEqual("rotated", json.loads(token_path.read_text())["refresh_token"])
        self.assertEqual(0o600, token_path.stat().st_mode & 0o777)

    @patch("app.spotify.requests.post")
    @patch("app.spotify.requests.get")
    def test_refuses_off_origin_pagination_without_sending_token(self, get, post):
        post.return_value = response({"access_token": "access", "expires_in": 3600})
        get.return_value = response({"items": [], "next": "https://evil.example/steal"})
        with self.assertRaises(ProviderError):
            self.client.playlists()
        self.assertEqual(1, get.call_count)

    @patch("app.spotify.requests.post")
    @patch("app.spotify.requests.get")
    def test_forbidden_explains_playlist_ownership(self, get, post):
        post.return_value = response({"access_token": "access", "expires_in": 3600})
        get.return_value = response({}, 403)
        with self.assertRaisesRegex(ProviderError, "own|collaborat"):
            self.client.playlist("abc")

    def test_missing_credentials_are_actionable(self):
        with self.assertRaisesRegex(ProviderError, "SPOTIFY_CLIENT_ID"):
            Spotify({}, self.directory).playlists()


class YouTubeTests(unittest.TestCase):
    @patch("app.youtube.YTMusic")
    def test_full_playlist_normalization_and_missing_metadata(self, factory):
        factory.return_value.get_playlist.return_value = {"title": "Mix", "tracks": [
            {"title": "One", "artists": [{"name": "Artist"}], "album": {"name": "Album"}, "duration_seconds": 30},
            {"title": "Removed", "isAvailable": False},
            {"title": "Two", "artists": [{"name": "Other"}]},
        ]}
        result = YouTubeMusic({}, Path('/nonexistent')).playlist("PL123")
        factory.return_value.get_playlist.assert_called_once_with("PL123", limit=None)
        self.assertEqual(2, len(result["tracks"]))
        self.assertEqual(30000, result["tracks"][0]["duration_ms"])
        self.assertIsNone(result["tracks"][1]["album"])
        self.assertEqual(1, result["skipped"])
        self.assertEqual("youtube_music", result["source"])

    def test_library_requires_sign_in(self):
        with self.assertRaisesRegex(ProviderError, "Connect YouTube Music"):
            YouTubeMusic({}, Path('/nonexistent')).playlists()


class PandoraTests(unittest.TestCase):
    @patch("app.pandora.requests.get")
    def test_only_real_pandora_listens_are_imported_with_original_timestamps(self, get):
        def listen(ts, service):
            return {"listened_at": ts, "track_metadata": {"track_name": "Song", "artist_name": "Artist",
                    "additional_info": {"music_service": service}}}
        get.side_effect = [response({"payload": {"listens": [listen(300, "spotify.com"), listen(200, "https://www.pandora.com/")]}}),
                           response({"payload": {"listens": [listen(100, "pandora.com"), listen(50, "notpandora.com")]}}),
                           response({"payload": {"listens": []}})]
        result = Pandora({"LISTENBRAINZ_USERNAME": "listener"}).history()
        self.assertEqual([200, 100], [t["listened_at"] for t in result["tracks"]])
        self.assertEqual("pandora", result["source"])
        self.assertTrue(result["already_submitted"])
        self.assertEqual(200, get.call_args_list[1].kwargs["params"]["max_ts"])

    def test_history_requires_listenbrainz_username(self):
        with self.assertRaisesRegex(ProviderError, "LISTENBRAINZ_USERNAME"):
            Pandora({}).history()
