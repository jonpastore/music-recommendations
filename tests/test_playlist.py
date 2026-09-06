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

    def test_formats_a_compact_artist_and_album_discord_message(self):
        tracks = self.tracks + [Track(title="Lover", artist="Taylor Swift", album="Lover"), Track(title="Single", artist="Mitski")]
        message = discord_playlist_message("Road Trip", "https://listen.tidal.com/playlist/example", tracks)

        self.assertIn("**Road Trip**", message)
        self.assertIn("\n!requestlist Taylor Swift — Lover\n", message)
        self.assertIn("\n!requestlist Vampire Weekend — Vampire Weekend\n", message)
        self.assertTrue(message.endswith("\n!requestlist Mitski — Discography"))
        self.assertNotIn("Paper Rings", message)
        self.assertEqual(1, message.count("Taylor Swift — Lover"))
        self.assertIn("Open in TIDAL", message)


    def test_splits_long_playlists_into_discord_safe_messages(self):
        from app.playlist import discord_playlist_messages

        tracks = [Track(title=f"Song {i}: " + "x" * 50, artist="An artist with a long name") for i in range(100)]
        messages = discord_playlist_messages("Long playlist", "https://listen.tidal.com/playlist/example", tracks)

        self.assertTrue(all(len(message) <= 2000 for message in messages))
        self.assertEqual(1, len(messages))
        self.assertIn("An artist with a long name — Discography", "\n".join(messages))

    def test_supports_discography_album_and_full_track_post_formats(self):
        from app.playlist import discord_playlist_messages
        tracks = [Track("One", "Artist", "Album"), Track("Two", "Artist", "Album")]
        self.assertIn("\n!requestlist Artist — Discography", discord_playlist_messages("P", "https://x", tracks, "discography")[0])
        self.assertIn("\n!requestlist Artist — Album", discord_playlist_messages("P", "https://x", tracks, "album")[0])
        self.assertIn("\n!requestlist Artist — One", discord_playlist_messages("P", "https://x", tracks, "tracks")[0])
        self.assertIn("\n!requestlist Artist — Two", discord_playlist_messages("P", "https://x", tracks, "tracks")[0])

    def test_preserves_source_attribution_for_each_provider(self):
        from app.playlist import discord_playlist_messages
        for source, label, domain in [('spotify', 'Spotify', 'spotify.com'),
                                      ('youtube_music', 'YouTube Music', 'music.youtube.com'),
                                      ('pandora', 'Pandora', 'pandora.com')]:
            with self.subTest(source=source):
                message = discord_playlist_messages('Mix', 'https://' + domain, self.tracks, source=source)[0]
                self.assertIn('Open in ' + label, message)
                self.assertNotIn('Open in TIDAL', message)
                payload = as_listenbrainz_payload(self.tracks, 1700000000, source=source)
                self.assertEqual(domain, payload['payload'][0]['track_metadata']['additional_info']['music_service'])
