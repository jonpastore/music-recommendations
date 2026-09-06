import json
import os
import time
from pathlib import Path
from typing import Literal
from urllib.parse import quote

import requests
import tidalapi
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from app.playlist import Track, as_listenbrainz_payload, discord_playlist_messages, discord_request_lines
from app.integrations import create_router, source_status
from app.providers import ProviderError
from app.tidal import expiry_time_from_storage, session_data_for_storage, verification_url

CONFIG_DIR = Path(os.environ.get("CONFIG_DIR", "/config"))
ENV_FILE = CONFIG_DIR / ".env"


def settings() -> dict[str, str]:
    values = dict(os.environ)
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                if value:
                    values[key] = value
    return values


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


def track_from_dict(value) -> Track:
    if isinstance(value, TrackInput):
        value = value.model_dump()
    return Track(value["title"], value["artist"], value.get("album"), value.get("duration_ms"), value.get("listened_at"))


app = FastAPI(title="Music Playlist Bridge")
app.include_router(create_router(lambda: settings(), lambda: CONFIG_DIR))
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.exception_handler(ProviderError)
async def provider_error(request, error):
    return JSONResponse(status_code=error.status, content={"detail": str(error)})


@app.exception_handler(requests.RequestException)
async def service_error(request, error):
    return JSONResponse(status_code=502, content={"detail": "A music service or Discord request failed. Check the configuration and try again; some messages may already have been sent."})

tidal_session: tidalapi.Session | None = None
tidal_login = None


def save_tidal_session(session: tidalapi.Session) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (CONFIG_DIR / "tidal-session.json").write_text(json.dumps(session_data_for_storage(
        session.token_type, session.access_token, session.refresh_token,
        session.expiry_time, session.is_pkce,
    )))


def load_tidal_session() -> tidalapi.Session:
    global tidal_session
    if tidal_session and tidal_session.check_login():
        return tidal_session
    saved = CONFIG_DIR / "tidal-session.json"
    if not saved.exists():
        raise HTTPException(400, "Connect TIDAL first")
    tidal_session = tidalapi.Session()
    credentials = json.loads(saved.read_text())
    credentials["expiry_time"] = expiry_time_from_storage(credentials.get("expiry_time"))
    if not tidal_session.load_oauth_session(**credentials):
        raise HTTPException(401, "TIDAL session expired; connect again")
    return tidal_session


@app.get("/api/status")
def status():
    config = settings()
    return {"sources": source_status(config, CONFIG_DIR), "version": os.environ.get("APP_VERSION", "development"), "discord": bool(config.get("DISCORD_WEBHOOK_URL")), "listenbrainz": bool(config.get("LISTENBRAINZ_TOKEN")), "tidal_session": (CONFIG_DIR / "tidal-session.json").exists()}


@app.post("/api/tidal/login")
def tidal_login_start():
    global tidal_session, tidal_login
    tidal_session = tidalapi.Session()
    login, tidal_login = tidal_session.login_oauth()
    return {"verification_url": verification_url(login.verification_uri_complete)}


@app.post("/api/tidal/login/complete")
def tidal_login_complete():
    if not tidal_login or not tidal_session:
        raise HTTPException(400, "Start TIDAL login first")
    if not tidal_login.done():
        return {"complete": False}
    tidal_login.result()
    save_tidal_session(tidal_session)
    return {"complete": True}


@app.get("/api/tidal/playlists")
def tidal_playlists():
    session = load_tidal_session()
    return [{"id": playlist.id, "name": playlist.name} for playlist in session.user.playlists()]


@app.get("/api/tidal/playlists/{playlist_id}")
def tidal_playlist(playlist_id: str):
    session = load_tidal_session()
    playlist = tidalapi.Playlist(session, playlist_id)
    return {"source": "tidal", "id": playlist.id, "name": playlist.name, "url": f"https://listen.tidal.com/playlist/{playlist.id}", "tracks": [
        {"title": track.name, "artist": track.artist.name, "album": track.album.name, "duration_ms": int(track.duration * 1000)} for track in playlist.tracks()
    ]}


def post_discord_messages(webhook: str, messages: list[str], submitted: int = 0) -> None:
    confirmed = 0
    for message in messages:
        try:
            response = requests.post(webhook, json={"content": message, "allowed_mentions": {"parse": []}}, timeout=30)
            response.raise_for_status()
        except requests.RequestException:
            raise HTTPException(502, f"Posting stopped after {confirmed} confirmed Discord messages and {submitted} confirmed listens. The last message may also have been accepted. Check Discord and ListenBrainz before posting again; no automatic retry was made.") from None
        confirmed += 1


@app.post("/api/dispatch")
def dispatch(request: DispatchRequest):
    config = settings()
    tracks = [track_from_dict(track) for track in request.tracks]
    if not tracks:
        raise HTTPException(400, "Select at least one track")
    if not config.get("DISCORD_WEBHOOK_URL"):
        raise HTTPException(400, "DISCORD_WEBHOOK_URL is not configured")
    if request.discord_format not in {"album", "discography", "tracks"}:
        raise HTTPException(400, "Unknown Discord format")
    messages = discord_playlist_messages(request.playlist_name, request.playlist_url, tracks, request.discord_format, request.source)
    messages.append("!auto on")
    post_discord_messages(config["DISCORD_WEBHOOK_URL"], messages)
    return {"discord_posted": True, "discord_messages": len(messages)}


@app.post("/api/recommendations")
def recommendations(request: DispatchRequest):
    config = settings()
    if request.source != "pandora":
        if not request.confirmed_listens:
            raise HTTPException(400, "Confirm that these tracks represent actual previous listens before submitting.")
        if not request.listened_at or request.listened_at > int(time.time()):
            raise HTTPException(400, "Choose when you listened; the time cannot be in the future.")
    user = config.get("LISTENBRAINZ_USERNAME")
    webhook = config.get("DISCORD_WEBHOOK_URL")
    token = config.get("LISTENBRAINZ_TOKEN")
    tracks = [track_from_dict(track) for track in request.tracks]
    if not user or not webhook or (request.source != "pandora" and not token):
        raise HTTPException(400, "LISTENBRAINZ_USERNAME, LISTENBRAINZ_TOKEN, and DISCORD_WEBHOOK_URL are required")
    if not tracks:
        raise HTTPException(400, "Select at least one track")
    submitted = 0
    if request.source != "pandora":
        if any(track.listened_at and track.listened_at > int(time.time()) for track in tracks):
            raise HTTPException(400, "Listen timestamps cannot be in the future.")
        payload = as_listenbrainz_payload(tracks, request.listened_at, request.source)
        for offset in range(0, len(tracks), 100):
            try:
                response = requests.post("https://api.listenbrainz.org/1/submit-listens", json={
                    "listen_type": "import", "payload": payload["payload"][offset:offset + 100]},
                    headers={"Authorization": f"Token {token}"}, timeout=30)
                response.raise_for_status()
            except requests.RequestException:
                raise HTTPException(502, f"Import stopped after {submitted} confirmed listens. The last batch may also have been accepted. Check ListenBrainz before submitting again; no Discord messages were sent.") from None
            submitted += len(payload["payload"][offset:offset + 100])
    try:
        response = requests.get(f"https://api.listenbrainz.org/1/user/{quote(user, safe='')}/playlists/recommendations", timeout=30)
        response.raise_for_status()
    except requests.RequestException:
        raise HTTPException(502, f"{submitted} listens were submitted, but recommendations could not be loaded. Check ListenBrainz before re-submitting; no Discord messages were sent.") from None
    playlists = response.json().get("playlists", [])
    if not playlists:
        return {"listenbrainz_submitted": submitted, "posted": False, "reason": "No recommendations available yet"}
    titles = [(item.get("playlist") or item).get("title", "Untitled playlist") for item in playlists]
    # Keep recommendation commands within Discord's 2,000-character limit too.
    messages, current = [], f"New ListenBrainz recommendations for **{user}**:\n"
    for line in discord_request_lines(titles):
        line = line[:1999]
        if len(current) + len(line) + 1 > 2000:
            messages.append(current.rstrip())
            current = ""
        current += line + "\n"
    if current.strip():
        messages.append(current.rstrip())
    link = f"https://listenbrainz.org/user/{quote(user, safe='')}/playlists/"
    if messages and len(messages[-1]) + len(link) + 1 <= 2000:
        messages[-1] += "\n" + link
    else:
        messages.append(link)
    messages.append("!auto on")
    post_discord_messages(webhook, messages, submitted)
    return {"listenbrainz_submitted": submitted, "posted": True, "count": len(playlists)}


@app.get("/", response_class=HTMLResponse)
def home():
    return HTML


HTML = (Path(__file__).parent / "static" / "index.html").read_text()
