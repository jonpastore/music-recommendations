"""Spotify's official Web API, including the 2026 playlist items endpoint."""
import time
from pathlib import Path
from threading import RLock
from urllib.parse import urlencode, urlsplit

import requests

from app.providers import ProviderError, collection, load_json, playlist_id, require, save_json, track

API = "https://api.spotify.com/v1/"
TOKEN_URL = "https://accounts.spotify.com/api/token"
TOKEN_LOCK = RLock()
SCOPES = "playlist-read-private playlist-read-collaborative"


class Spotify:
    def __init__(self, config: dict, directory: Path):
        self.config = config
        self.token_path = directory / "spotify-session.json"

    def authorization_url(self, state: str) -> str:
        require(self.config, "SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET", "SPOTIFY_REDIRECT_URI")
        uri = self.config["SPOTIFY_REDIRECT_URI"]
        parsed = urlsplit(uri)
        if not (parsed.scheme == "https" and parsed.hostname) and not (
            parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "::1"}
        ):
            raise ProviderError("SPOTIFY_REDIRECT_URI must use HTTPS or an HTTP loopback IP (127.0.0.1).")
        return "https://accounts.spotify.com/authorize?" + urlencode({
            "client_id": self.config["SPOTIFY_CLIENT_ID"], "response_type": "code",
            "redirect_uri": uri, "scope": SCOPES, "state": state,
        })

    def _token_request(self, data: dict, previous: dict | None = None) -> dict:
        require(self.config, "SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET")
        response = requests.post(TOKEN_URL, data=data, auth=(
            self.config["SPOTIFY_CLIENT_ID"], self.config["SPOTIFY_CLIENT_SECRET"]), timeout=30)
        if response.status_code != 200:
            raise ProviderError("Spotify sign-in expired or was rejected. Check the client credentials and reconnect.", 401)
        token = response.json()
        if not token.get("access_token"):
            raise ProviderError("Spotify did not return an access token.", 502)
        token = {**(previous or {}), **token, "expires_at": time.time() + token.get("expires_in", 3600)}
        save_json(self.token_path, token)
        return token

    def complete_login(self, code: str) -> None:
        require(self.config, "SPOTIFY_REDIRECT_URI")
        with TOKEN_LOCK:
            self._token_request({"grant_type": "authorization_code", "code": code,
                                 "redirect_uri": self.config["SPOTIFY_REDIRECT_URI"]})

    def access_token(self, force: bool = False) -> str:
        require(self.config, "SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET")
        with TOKEN_LOCK:
            token = load_json(self.token_path)
            if not force and token.get("access_token") and token.get("expires_at", 0) > time.time() + 60:
                return token["access_token"]
            refresh = token.get("refresh_token") or self.config.get("SPOTIFY_REFRESH_TOKEN")
            if not refresh:
                raise ProviderError("Connect Spotify first, or configure SPOTIFY_REFRESH_TOKEN.")
            return self._token_request({"grant_type": "refresh_token", "refresh_token": refresh},
                                       {**token, "refresh_token": refresh})["access_token"]

    def _get(self, url: str, params=None) -> dict:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != "api.spotify.com" or not parsed.path.startswith("/v1/"):
            raise ProviderError("Spotify returned an invalid pagination link.", 502)
        for attempt in range(2):
            response = requests.get(url, params=params, headers={
                "Authorization": "Bearer " + self.access_token(force=bool(attempt))}, timeout=30,
                allow_redirects=False)
            if response.status_code != 401:
                break
        if response.status_code == 403:
            raise ProviderError("Spotify denied access. Playlist contents require a playlist you own or collaborate on; also check app access and scopes.", 403)
        if response.status_code == 429:
            raise ProviderError("Spotify rate limit reached. Wait before loading again.", 429)
        if response.status_code != 200:
            raise ProviderError("Spotify could not load this playlist. Reconnect and check its availability.", 502)
        return response.json()

    def _pages(self, url: str):
        seen = set()
        params = {"limit": 50}
        while url:
            if url in seen:
                raise ProviderError("Spotify returned repeated pagination data.", 502)
            seen.add(url)
            page = self._get(url, params)
            yield from page.get("items", [])
            url, params = page.get("next"), None

    def playlists(self) -> list[dict]:
        return [{"id": item["id"], "name": item.get("name", "Untitled playlist")}
                for item in self._pages(API + "me/playlists") if item and item.get("id")]

    def playlist(self, identifier: str) -> dict:
        identifier = playlist_id(identifier)
        data = self._get(API + "playlists/" + identifier)
        tracks, skipped = [], 0
        for wrapper in self._pages(API + "playlists/" + identifier + "/items"):
            item = (wrapper.get("item", wrapper.get("track")) if wrapper else None)
            artists = ", ".join(a["name"] for a in (item or {}).get("artists", []) if a.get("name"))
            if not item or item.get("type") != "track" or not item.get("name") or not artists or item.get("is_playable") is False:
                skipped += 1
                continue
            tracks.append(track(item["name"], artists, (item.get("album") or {}).get("name"), item.get("duration_ms")))
        return collection("spotify", identifier, data.get("name", "Spotify playlist"),
                          "https://open.spotify.com/playlist/" + identifier, tracks, skipped)
