"""Shared input contracts for import, Discord and Plex actions."""
from typing import Literal
from pydantic import BaseModel, Field, field_validator


class TrackInput(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    artist: str = Field(min_length=1, max_length=500)
    album: str | None = Field(default=None, max_length=500)
    duration_ms: int | None = Field(default=None, gt=0)
    listened_at: int | None = Field(default=None, gt=0)

    @field_validator("title", "artist", "album")
    @classmethod
    def clean_text(cls, value):
        if value is None:
            return None
        value = " ".join(value.split())
        if not value:
            raise ValueError("Track fields cannot be blank")
        return value


class DispatchRequest(BaseModel):
    playlist_name: str = Field(max_length=200)
    playlist_url: str = Field(max_length=500)
    tracks: list[TrackInput] = Field(max_length=5000)
    discord_format: Literal["album", "discography", "tracks"] = "album"
    source: Literal["tidal", "spotify", "youtube_music", "pandora"] = "tidal"
    confirmed_listens: bool = False
    listened_at: int | None = Field(default=None, gt=0)


