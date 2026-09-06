"""Shared provider boundaries: safe errors, private token storage and track shapes."""
import json
import os
import re
import tempfile
from pathlib import Path


class ProviderError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def save_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as file:
        temporary = Path(file.name)
        try:
            json.dump(value, file)
            file.flush()
            os.fsync(file.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (ValueError, OSError):
        raise ProviderError(f"Cannot read {path.name}; reconnect the service.") from None


def require(config: dict, *keys: str) -> None:
    missing = [key for key in keys if not config.get(key)]
    if missing:
        raise ProviderError("Configure " + ", ".join(missing) + " in Unraid first.")


def playlist_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value):
        raise ProviderError("Enter a valid playlist ID.")
    return value


def track(title: str, artist: str, album=None, duration_ms=None, **extra) -> dict:
    return {"title": title, "artist": artist, "album": album, "duration_ms": duration_ms, **extra}


def collection(source: str, identifier: str, name: str, url: str, tracks: list, skipped: int = 0, **extra) -> dict:
    return {"source": source, "id": identifier, "name": name, "url": url,
            "tracks": tracks, "skipped": skipped, **extra}
