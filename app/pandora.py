"""Actual Pandora listens previously recorded by a ListenBrainz scrobbler."""
from urllib.parse import quote, urlsplit

import requests

from app.providers import ProviderError, collection, track


def is_pandora(info: dict) -> bool:
    for key in ("music_service", "origin_url"):
        value = info.get(key, "")
        if not isinstance(value, str):
            continue
        host = urlsplit(value if "://" in value else "https://" + value).hostname or ""
        if host == "pandora.com" or host.endswith(".pandora.com"):
            return True
    return str(info.get("music_service_name", "")).casefold() == "pandora"


class Pandora:
    def __init__(self, config: dict):
        self.config = config

    def history(self) -> dict:
        user = self.config.get("PANDORA_LISTENBRAINZ_USERNAME") or self.config.get("LISTENBRAINZ_USERNAME")
        if not user:
            raise ProviderError("Configure PANDORA_LISTENBRAINZ_USERNAME or LISTENBRAINZ_USERNAME, and scrobble Pandora plays to ListenBrainz first.")
        try:
            limit = int(self.config.get("PANDORA_HISTORY_LIMIT", "200"))
        except ValueError:
            raise ProviderError("PANDORA_HISTORY_LIMIT must be a number between 1 and 1000.") from None
        if not 1 <= limit <= 1000:
            raise ProviderError("PANDORA_HISTORY_LIMIT must be between 1 and 1000.")
        tracks, cursor, scanned = [], None, 0
        # Bound work to 10 pages (up to 10,000 mixed-source listens).
        exhausted = False
        for _ in range(10):
            params = {"count": 1000}
            if cursor is not None:
                params["max_ts"] = cursor
            response = requests.get("https://api.listenbrainz.org/1/user/" + quote(user, safe="") + "/listens",
                                    params=params, timeout=30)
            if response.status_code != 200:
                raise ProviderError("ListenBrainz could not load Pandora listens. Check the username or try again later.", 502)
            listens = response.json().get("payload", {}).get("listens", [])
            if not listens:
                exhausted = True
                break
            scanned += len(listens)
            timestamps = []
            for listen in listens:
                timestamp = listen.get("listened_at")
                if not isinstance(timestamp, int):
                    continue
                timestamps.append(timestamp)
                metadata = listen.get("track_metadata", {})
                info = metadata.get("additional_info", {})
                if is_pandora(info) and metadata.get("track_name") and metadata.get("artist_name"):
                    tracks.append(track(metadata["track_name"], metadata["artist_name"], metadata.get("release_name"),
                                        info.get("duration_ms"), listened_at=timestamp))
            if len(tracks) >= limit:
                break
            if not timestamps or (cursor is not None and min(timestamps) >= cursor):
                raise ProviderError("ListenBrainz returned invalid history pagination.", 502)
            cursor = min(timestamps)
        return collection("pandora", "history", "Pandora listens", "https://www.pandora.com/", tracks[:limit],
                          already_submitted=True, scanned=scanned, truncated=not exhausted,
                          note="Only Pandora plays previously scrobbled to ListenBrainz are available; native Pandora history cannot be backfilled.")
