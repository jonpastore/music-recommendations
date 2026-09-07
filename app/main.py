import json
import os
import time
from pathlib import Path
from threading import RLock
from urllib.parse import quote

import requests
import tidalapi
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.playlist import Track, as_listenbrainz_payload, discord_playlist_messages, discord_request_lines
from app.integrations import create_router, source_status
from app.providers import ProviderError, save_json
from app.models import DispatchRequest, TrackInput
from app.plex_routes import create_router as create_plex_router, plex_status
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


def track_from_dict(value) -> Track:
    if isinstance(value, TrackInput):
        value = value.model_dump()
    return Track(value["title"], value["artist"], value.get("album"), value.get("duration_ms"), value.get("listened_at"))


app = FastAPI(title="Music Playlist Bridge")
app.include_router(create_router(lambda: settings(), lambda: CONFIG_DIR))
app.include_router(create_plex_router(lambda: settings(), lambda: CONFIG_DIR))
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.exception_handler(ProviderError)
async def provider_error(request, error):
    return JSONResponse(status_code=error.status, content={"detail": str(error)})


@app.exception_handler(requests.RequestException)
async def service_error(request, error):
    return JSONResponse(status_code=502, content={"detail": "A music service or Discord request failed. Check the configuration and try again; some messages may already have been sent."})

tidal_session: tidalapi.Session | None = None
tidal_login = None
tidal_pending_session = None
tidal_login_details = None
TIDAL_LOCK = RLock()


def save_tidal_session(session: tidalapi.Session) -> None:
    save_json(CONFIG_DIR / "tidal-session.json", session_data_for_storage(
        session.token_type, session.access_token, session.refresh_token,
        session.expiry_time, session.is_pkce,
    ))


def _load_tidal_session() -> tidalapi.Session:
    global tidal_session
    with TIDAL_LOCK:
        if tidal_session and tidal_session.check_login():
            save_tidal_session(tidal_session)
            return tidal_session
        saved = CONFIG_DIR / "tidal-session.json"
        if not saved.exists():
            raise HTTPException(400, "Connect TIDAL first")
        session = tidalapi.Session()
        credentials = json.loads(saved.read_text())
        credentials["expiry_time"] = expiry_time_from_storage(credentials.get("expiry_time"))
        if not session.load_oauth_session(**credentials):
            raise HTTPException(401, "TIDAL session expired; connect again")
        save_tidal_session(session)
        tidal_session = session
        return session


def load_tidal_session() -> tidalapi.Session:
    try:
        return _load_tidal_session()
    except tidalapi.exceptions.AuthenticationError:
        raise HTTPException(401, "TIDAL login has expired or been revoked. Connect TIDAL again to continue.") from None


def persist_active_tidal_session(session):
    with TIDAL_LOCK:
        # An in-flight playlist read must not undo a logout or account switch.
        if tidal_session is session:
            save_tidal_session(session)


@app.get("/api/status")
def status():
    config = settings()
    return {"tidal_login_pending": tidal_login is not None, "plex": plex_status(config), "sources": source_status(config, CONFIG_DIR), "version": os.environ.get("APP_VERSION", "development"), "discord": bool(config.get("DISCORD_WEBHOOK_URL")), "listenbrainz": bool(config.get("LISTENBRAINZ_TOKEN")), "tidal_session": (CONFIG_DIR / "tidal-session.json").exists()}


@app.post("/api/tidal/login")
def tidal_login_start():
    global tidal_login, tidal_pending_session, tidal_login_details
    with TIDAL_LOCK:
        if tidal_login and tidal_login_details:
            return tidal_login_details
        try:
            load_tidal_session()
            return {"complete": True}
        except HTTPException as error:
            if error.status_code not in {400, 401}:
                raise
        tidal_pending_session = tidalapi.Session()
        login, tidal_login = tidal_pending_session.login_oauth()
        tidal_login_details = {"verification_url": verification_url(login.verification_uri_complete)}
        return tidal_login_details


@app.post("/api/tidal/login/complete")
def tidal_login_complete():
    global tidal_session, tidal_login, tidal_pending_session, tidal_login_details
    with TIDAL_LOCK:
        if not tidal_login or not tidal_pending_session:
            load_tidal_session()
            return {"complete": True}
        if not tidal_login.done():
            return {"complete": False}
        try:
            if not tidal_login.result():
                raise ValueError("TIDAL did not accept authorization")
        except Exception:
            tidal_login = tidal_pending_session = tidal_login_details = None
            raise HTTPException(502, "TIDAL sign-in did not complete. Click Connect TIDAL to start again.") from None
        save_tidal_session(tidal_pending_session)
        tidal_session = tidal_pending_session
        tidal_login = tidal_pending_session = tidal_login_details = None
        return {"complete": True}


@app.post("/api/tidal/logout")
def tidal_logout():
    global tidal_session, tidal_login, tidal_pending_session, tidal_login_details
    with TIDAL_LOCK:
        (CONFIG_DIR / "tidal-session.json").unlink(missing_ok=True)
        if tidal_login:
            tidal_login.cancel()
        tidal_session = tidal_login = tidal_pending_session = tidal_login_details = None
        return {"logged_out": True}


@app.get("/api/tidal/playlists")
def tidal_playlists():
    session = load_tidal_session()
    result = [{"id": playlist.id, "name": playlist.name} for playlist in session.user.playlists()]
    persist_active_tidal_session(session)
    return result


@app.get("/api/tidal/playlists/{playlist_id}")
def tidal_playlist(playlist_id: str):
    session = load_tidal_session()
    playlist = tidalapi.Playlist(session, playlist_id)
    result = {"source": "tidal", "id": playlist.id, "name": playlist.name, "url": f"https://listen.tidal.com/playlist/{playlist.id}", "tracks": [
        {"title": track.name, "artist": track.artist.name, "album": track.album.name, "duration_ms": int(track.duration * 1000)} for track in playlist.tracks()
    ]}
    persist_active_tidal_session(session)
    return result


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
