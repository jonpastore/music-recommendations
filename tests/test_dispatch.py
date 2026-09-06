import unittest
from unittest.mock import Mock, patch

import requests
from fastapi import HTTPException

from app.main import DispatchRequest, dispatch, recommendations


class DiscordDispatchTests(unittest.TestCase):
    def setUp(self):
        self.request = DispatchRequest(
            confirmed_listens=True, listened_at=1700000000, playlist_name="Playlist", playlist_url="https://example.com/playlist",
            tracks=[{"title": "Song", "artist": "Artist", "album": "Album"}],
        )
        config = patch("app.main.settings", return_value={
            "DISCORD_WEBHOOK_URL": "https://example.com/webhook",
            "LISTENBRAINZ_USERNAME": "listener", "LISTENBRAINZ_TOKEN": "test-token",
        })
        config.start()
        self.addCleanup(config.stop)

    @patch("app.main.requests.post")
    def test_auto_follows_all_playlist_chunks(self, post):
        self.request.discord_format = "tracks"
        self.request.tracks *= 100
        for index, track in enumerate(self.request.tracks):
            self.request.tracks[index] = {**track.model_dump(), "title": f"Song {index}"}
        result = dispatch(self.request)
        messages = [call.kwargs["json"]["content"] for call in post.call_args_list]
        self.assertGreater(len(messages), 2)
        self.assertEqual("!auto on", messages[-1])
        self.assertEqual(1, messages.count("!auto on"))
        self.assertTrue(all(len(message) <= 2000 for message in messages))
        self.assertEqual(100, "\n".join(messages).count("!requestlist "))
        self.assertEqual(len(messages), result["discord_messages"])

    @patch("app.main.requests.post")
    def test_failed_playlist_post_does_not_enable_auto(self, post):
        post.return_value.raise_for_status.side_effect = requests.HTTPError("failed")
        with self.assertRaises(HTTPException):
            dispatch(self.request)
        self.assertEqual(1, post.call_count)

    @patch("app.main.requests.get")
    @patch("app.main.requests.post")
    def test_recommendations_end_with_separate_auto_message(self, post, get):
        get.return_value.json.return_value = {"playlists": [{"title": "Weekly picks"}]}
        recommendations(self.request)
        messages = [call.kwargs["json"]["content"] for call in post.call_args_list[1:]]
        self.assertEqual(2, len(messages))
        self.assertIn("!requestlist Weekly picks", messages[0].splitlines())
        self.assertEqual("!auto on", messages[1])

    @patch("app.main.requests.get")
    @patch("app.main.requests.post")
    def test_no_recommendations_does_not_enable_auto(self, post, get):
        get.return_value.json.return_value = {"playlists": []}
        result = recommendations(self.request)
        self.assertFalse(result["posted"])
        self.assertEqual(1, post.call_count)  # Only the ListenBrainz submission.

    @patch("app.main.requests.post")
    def test_failed_auto_post_is_reported(self, post):
        failed = Mock()
        failed.raise_for_status.side_effect = requests.HTTPError("auto failed")
        post.side_effect = [Mock(), failed]
        with self.assertRaises(HTTPException):
            dispatch(self.request)

    @patch("app.main.requests.get")
    @patch("app.main.requests.post")
    def test_pandora_recommendations_do_not_resubmit_existing_listens(self, post, get):
        self.request.source = "pandora"
        self.request.confirmed_listens = False
        get.return_value.json.return_value = {"playlists": [{"playlist": {"title": "Picks"}}]}
        result = recommendations(self.request)
        self.assertEqual(0, result["listenbrainz_submitted"])
        self.assertEqual(2, post.call_count)
        self.assertIn("!requestlist Picks", post.call_args_list[0].kwargs['json']['content'])

    @patch("app.main.requests.post")
    def test_partial_discord_failure_reports_confirmed_count_without_retry(self, post):
        from fastapi import HTTPException
        post.side_effect = [Mock(), requests.Timeout('lost response')]
        with self.assertRaises(HTTPException) as error:
            dispatch(self.request)
        self.assertIn('1 confirmed Discord messages', error.exception.detail)
        self.assertIn('Check Discord', error.exception.detail)
        self.assertEqual(2, post.call_count)

    @patch("app.main.requests.post")
    def test_later_listenbrainz_batch_failure_reports_confirmed_listens(self, post):
        from fastapi import HTTPException
        self.request.tracks *= 101
        post.side_effect = [Mock(), requests.Timeout('lost response')]
        with self.assertRaises(HTTPException) as error:
            recommendations(self.request)
        self.assertIn('100 confirmed listens', error.exception.detail)
        self.assertIn('may also have been accepted', error.exception.detail)
        self.assertEqual(2, post.call_count)
