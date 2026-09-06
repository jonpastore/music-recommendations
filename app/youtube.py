"""YouTube Music playlist access through the documented ytmusicapi client."""
from pathlib import Path

import requests

from ytmusicapi import OAuthCredentials, YTMusic

from app.providers import ProviderError, collection, playlist_id, require, track


class TimeoutSession(requests.Session):
    def request(self, method, url, **kwargs):
        kwargs.setdefault("timeout", 30)
        return super().request(method, url, **kwargs)


class YouTubeMusic:
    def __init__(self, config: dict, directory: Path):
        self.config = config
        self.token_path = directory / "youtube-music-session.json"

    def credentials(self) -> OAuthCredentials:
        require(self.config, "YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET")
        return OAuthCredentials(self.config["YOUTUBE_CLIENT_ID"], self.config["YOUTUBE_CLIENT_SECRET"], session=TimeoutSession())

    def client(self, authenticated: bool = False) -> YTMusic:
        browser_file = self.config.get("YOUTUBE_MUSIC_AUTH_FILE")
        if browser_file:
            if not Path(browser_file).is_file():
                raise ProviderError("YOUTUBE_MUSIC_AUTH_FILE does not exist inside the container.")
            return YTMusic(browser_file, requests_session=TimeoutSession())
        if self.token_path.exists():
            return YTMusic(str(self.token_path), oauth_credentials=self.credentials(), requests_session=TimeoutSession())
        if authenticated:
            raise ProviderError("Connect YouTube Music first, or configure YOUTUBE_MUSIC_AUTH_FILE.")
        return YTMusic(requests_session=TimeoutSession())

    def playlists(self) -> list[dict]:
        items = self.client(authenticated=True).get_library_playlists(limit=None)
        return [{"id": item["playlistId"], "name": item.get("title", "Untitled playlist")}
                for item in items if item.get("playlistId")]

    def playlist(self, identifier: str) -> dict:
        identifier = playlist_id(identifier)
        data = self.client().get_playlist(identifier, limit=None)
        tracks, skipped = [], 0
        for item in data.get("tracks", []):
            artists = ", ".join(a["name"] for a in item.get("artists", []) if a.get("name"))
            if item.get("isAvailable") is False or not item.get("title") or not artists:
                skipped += 1
                continue
            seconds = item.get("duration_seconds")
            tracks.append(track(item["title"], artists, (item.get("album") or {}).get("name"),
                                int(seconds * 1000) if seconds is not None else None))
        return collection("youtube_music", identifier, data.get("title", "YouTube Music playlist"),
                          "https://music.youtube.com/playlist?list=" + identifier, tracks, skipped)
