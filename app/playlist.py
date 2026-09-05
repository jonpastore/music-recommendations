from dataclasses import dataclass


@dataclass(frozen=True)
class Track:
    title: str
    artist: str
    album: str | None = None
    duration_ms: int | None = None


def as_listenbrainz_payload(tracks: list[Track], listened_at: int) -> dict:
    """Build an honest historical-import payload for user-confirmed listens."""
    return {
        "listen_type": "import",
        "payload": [
            {
                "listened_at": listened_at - index,
                "track_metadata": {
                    "artist_name": track.artist,
                    "track_name": track.title,
                    "release_name": track.album,
                    "additional_info": {
                        "music_service": "tidal.com",
                        "music_service_name": "TIDAL",
                        "submission_client": "TIDAL Playlist Bridge",
                        **({"duration_ms": track.duration_ms} if track.duration_ms else {}),
                    },
                },
            }
            for index, track in enumerate(tracks)
        ],
    }


def discord_playlist_message(name: str, url: str, tracks: list[Track]) -> str:
    """Return the first Discord-safe message for backward compatibility."""
    return discord_playlist_messages(name, url, tracks)[0]


def discord_playlist_messages(name: str, url: str, tracks: list[Track]) -> list[str]:
    """Format unique artist/album choices as Discord-safe webhook messages."""
    messages: list[str] = []
    prefix = f"**{name}**\n[Open in TIDAL]({url})\n\n"
    current = prefix
    seen: set[tuple[str, str]] = set()
    for track in tracks:
        album = track.album or "Discography"
        key = (track.artist.casefold(), album.casefold())
        if key in seen:
            continue
        seen.add(key)
        line = f"• {track.artist} — {album}"
        if len(current) + len(line) + 1 > 2000 and current != prefix:
            messages.append(current.rstrip())
            current = f"**{name}** (continued)\n[Open in TIDAL]({url})\n\n"
        if len(line) + len(current) + 1 > 2000:
            line = line[: 1999 - len(current)] + "…"
        current += line + "\n"
    messages.append(current.rstrip())
    return messages
