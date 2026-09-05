import unittest

from app.playlist import Track, as_listenbrainz_payload, discord_playlist_message


class PlaylistFormattingTests(unittest.TestCase):
    def setUp(self):
        self.tracks = [
            Track(title="Paper Rings", artist="Taylor Swift", album="Lover", duration_ms=222400),
            Track(title="A-Punk", artist="Vampire Weekend", album="Vampire Weekend", duration_ms=137000),
        ]

    def test_creates_listenbrainz_import_payload_from_selected_tracks(self):
        payload = as_listenbrainz_payload(self.tracks, listened_at=1_700_000_000)

        self.assertEqual("import", payload["listen_type"])
        self.assertEqual(2, len(payload["payload"]))
        self.assertEqual("Taylor Swift", payload["payload"][0]["track_metadata"]["artist_name"])
        self.assertEqual("tidal.com", payload["payload"][0]["track_metadata"]["additional_info"]["music_service"])

    def test_formats_a_readable_discord_playlist_message(self):
        message = discord_playlist_message("Road Trip", "https://listen.tidal.com/playlist/example", self.tracks)

        self.assertIn("**Road Trip**", message)
        self.assertIn("Taylor Swift — Paper Rings", message)
        self.assertIn("Vampire Weekend — A-Punk", message)
        self.assertIn("Open in TIDAL", message)


    def test_splits_long_playlists_into_discord_safe_messages(self):
        from app.playlist import discord_playlist_messages

        tracks = [Track(title=f"Song {i}: " + "x" * 50, artist="An artist with a long name") for i in range(100)]
        messages = discord_playlist_messages("Long playlist", "https://listen.tidal.com/playlist/example", tracks)

        self.assertGreater(len(messages), 1)
        self.assertTrue(all(len(message) <= 2000 for message in messages))
        self.assertIn("Song 99", "\n".join(messages))
