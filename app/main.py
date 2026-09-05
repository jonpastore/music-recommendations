import json
import os
import time
from pathlib import Path

import requests
import tidalapi
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.playlist import Track, as_listenbrainz_payload, discord_playlist_messages
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


class DispatchRequest(BaseModel):
    playlist_name: str
    playlist_url: str
    tracks: list[dict]
    confirmed_listens: bool = False
    discord_format: str = "album"


def track_from_dict(value: dict) -> Track:
    return Track(value["title"], value["artist"], value.get("album"), value.get("duration_ms"))


app = FastAPI(title="TIDAL Playlist Bridge")
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
    return {"version": os.environ.get("APP_VERSION", "development"), "discord": bool(config.get("DISCORD_WEBHOOK_URL")), "listenbrainz": bool(config.get("LISTENBRAINZ_TOKEN")), "tidal_session": (CONFIG_DIR / "tidal-session.json").exists()}


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
    return {"id": playlist.id, "name": playlist.name, "url": f"https://listen.tidal.com/playlist/{playlist.id}", "tracks": [
        {"title": track.name, "artist": track.artist.name, "album": track.album.name, "duration_ms": int(track.duration * 1000)} for track in playlist.tracks()
    ]}


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
    messages = discord_playlist_messages(request.playlist_name, request.playlist_url, tracks, request.discord_format)
    for message in messages:
        response = requests.post(config["DISCORD_WEBHOOK_URL"], json={"content": message}, timeout=30)
        response.raise_for_status()
    submitted = 0
    if request.confirmed_listens:
        if not config.get("LISTENBRAINZ_TOKEN"):
            raise HTTPException(400, "LISTENBRAINZ_TOKEN is not configured")
        payload = as_listenbrainz_payload(tracks, int(time.time()))
        lb_response = requests.post("https://api.listenbrainz.org/1/submit-listens", json=payload, headers={"Authorization": f"Token {config['LISTENBRAINZ_TOKEN']}"}, timeout=30)
        lb_response.raise_for_status()
        submitted = len(tracks)
    return {"discord_posted": True, "discord_messages": len(messages), "listenbrainz_submitted": submitted}


@app.post("/api/recommendations")
def recommendations():
    config = settings()
    user = config.get("LISTENBRAINZ_USERNAME")
    webhook = config.get("DISCORD_WEBHOOK_URL")
    if not user or not webhook:
        raise HTTPException(400, "LISTENBRAINZ_USERNAME and DISCORD_WEBHOOK_URL are required")
    data = requests.get(f"https://api.listenbrainz.org/1/user/{user}/playlists/recommendations", timeout=30).json()
    playlists = data.get("playlists", [])
    if not playlists:
        return {"posted": False, "reason": "No recommendations available yet"}
    names = "\n".join(f"• {item.get('title', 'Untitled playlist')}" for item in playlists)
    requests.post(webhook, json={"content": f"New ListenBrainz recommendations for **{user}**:\n{names}\nhttps://listenbrainz.org/user/{user}/playlists/"}, timeout=30).raise_for_status()
    return {"posted": True, "count": len(playlists)}


@app.get("/", response_class=HTMLResponse)
def home():
    return HTML


HTML = """<!doctype html><title>TIDAL Playlist Bridge</title><style>body{font:16px system-ui;max-width:760px;margin:3rem auto;padding:0 1rem}textarea,input,select{width:100%;margin:.4rem 0;padding:.6rem}button{padding:.6rem 1rem;margin:.3rem 0}pre{background:#eee;padding:1rem;white-space:pre-wrap}</style><h1>TIDAL Playlist Bridge</h1><p>Post selected playlist tracks to Discord. Confirming listens is only for tracks actually heard in the past.</p><button onclick=login()>Connect TIDAL</button><button onclick=finishLogin()>Finish TIDAL login</button><button onclick=playlists()>Load TIDAL playlists</button><select id=p onchange=fetchPlaylist(this.value)><option>Select a playlist</option></select><label>Playlist name<input id=n value="TIDAL playlist"></label><label>Playlist link<input id=u></label><label>Tracks, one per line: Artist — Track — Album<textarea id=t rows=10></textarea></label><label><input id=c type=checkbox style="width:auto"> I confirm these are real prior listens</label><br><label>Discord post format<select id=f><option value="discography">Unique artists — Discography</option><option value="album" selected>Unique artist — Album</option><option value="tracks">Full track list</option></select></label><button onclick=send()>Post selected tracks</button><button onclick=recs()>Post ListenBrainz recommendations</button><pre id=o>Loading…</pre><script>const o=document.querySelector('#o');async function api(url,opts={}){let r=await fetch(url,opts);let j=await r.json().catch(()=>({detail:r.statusText}));if(!r.ok)throw Error(j.detail||JSON.stringify(j));return j}async function show(action,work){try{o.textContent=action+'…';let x=await work();o.textContent=JSON.stringify(x,null,2)}catch(e){o.textContent='Error: '+e.message}}async function login(){await show('Starting TIDAL sign-in',async()=>{let x=await api('/api/tidal/login',{method:'POST'});open(x.verification_url,'_blank');return {next:'Sign in to TIDAL in the new tab, then return here and click Finish TIDAL login.'}})}async function finishLogin(){await show('Checking TIDAL authorization',()=>api('/api/tidal/login/complete',{method:'POST'}))}async function playlists(){await show('Loading TIDAL playlists',async()=>{let x=await api('/api/tidal/playlists');p.innerHTML='<option>Select a playlist</option>'+x.map(v=>`<option value="${v.id}">${v.name}</option>`).join('');return {loaded:x.length}})}async function fetchPlaylist(id){if(!id)return;let x=await api('/api/tidal/playlists/'+id);n.value=x.name;u.value=x.url;t.value=x.tracks.map(v=>`${v.artist} — ${v.title} — ${v.album||''}`).join('\\n')}async function send(){let tracks=t.value.split('\\n').filter(Boolean).map(x=>{let [artist,title,album]=x.split(' — ');return {artist,title,album}});o.textContent=JSON.stringify(await api('/api/dispatch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({playlist_name:n.value,playlist_url:u.value,tracks,confirmed_listens:c.checked,discord_format:f.value})}),null,2)}async function recs(){o.textContent=JSON.stringify(await api('/api/recommendations',{method:'POST'}),null,2)}api('/api/status').then(x=>o.textContent='Configuration: '+JSON.stringify(x,null,2)).catch(e=>o.textContent=e)</script>"""
