from dataclasses import dataclass


SOURCES = {"tidal": ("TIDAL", "tidal.com"), "spotify": ("Spotify", "spotify.com"),
           "youtube_music": ("YouTube Music", "music.youtube.com"), "pandora": ("Pandora", "pandora.com")}


@dataclass(frozen=True)
class Track:
    title: str
    artist: str
    album: str | None = None
    duration_ms: int | None = None
    listened_at: int | None = None


def as_listenbrainz_payload(tracks: list[Track], listened_at: int, source: str = "tidal") -> dict:
    """Build an honest historical-import payload for user-confirmed listens."""
    return {
        "listen_type": "import",
        "payload": [
            {
                "listened_at": track.listened_at or listened_at - index,
                "track_metadata": {
                    "artist_name": track.artist,
                    "track_name": track.title,
                    "release_name": track.album,
                    "additional_info": {
                        "music_service": SOURCES[source][1],
                        "music_service_name": SOURCES[source][0],
                        "submission_client": "TIDAL Playlist Bridge",
                        **({"duration_ms": track.duration_ms} if track.duration_ms else {}),
                    },
                },
            }
            for index, track in enumerate(tracks)
        ],
    }


def discord_playlist_message(name: str, url: str, tracks: list[Track], mode: str = "album") -> str:
    """Return the first Discord-safe message for backward compatibility."""
    return discord_playlist_messages(name, url, tracks, mode)[0]


def discord_request_lines(items: list[str]) -> list[str]:
    return ["!requestlist " + " ".join(item.split()) for item in items]


def discord_playlist_messages(name: str, url: str, tracks: list[Track], mode: str = "album", source: str = "tidal") -> list[str]:
    """Format unique artist/album choices as Discord-safe webhook messages."""
    messages: list[str] = []
    name = " ".join(name.split())[:200]
    url = url[:500]
    service = SOURCES[source][0]
    prefix = f"**{name}**\n[Open in {service}]({url})\n\n"
    current = prefix
    seen: set[tuple[str, str]] = set()
    items: list[str] = []
    for track in tracks:
        if mode == "tracks":
            label = track.title
            key = (track.artist.casefold(), track.title.casefold())
        elif mode == "discography":
            label = "Discography"
            key = (track.artist.casefold(), label.casefold())
        else:
            label = track.album or "Discography"
            key = (track.artist.casefold(), label.casefold())
        if key in seen:
            continue
        seen.add(key)
        items.append(f"{track.artist} — {label}")
    for line in discord_request_lines(items):
        if len(current) + len(line) + 1 > 2000 and current != prefix:
            messages.append(current.rstrip())
            current = f"**{name}** (continued)\n[Open in {service}]({url})\n\n"
        if len(line) + len(current) + 1 > 2000:
            line = line[: 1999 - len(current)] + "…"
        current += line + "\n"
    messages.append(current.rstrip())
    return messages
