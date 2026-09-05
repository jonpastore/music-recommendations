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
    lines = [f"**{name}**", "[Open in TIDAL](%s)" % url, ""]
    lines.extend(f"• {track.artist} — {track.title}" for track in tracks[:50])
    if len(tracks) > 50:
        lines.append(f"• …and {len(tracks) - 50} more")
    return "\n".join(lines)
