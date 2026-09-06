"""Provider routes and short-lived, browser-bound OAuth handshakes."""
import secrets
import time
from threading import RLock

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse
from ytmusicapi.exceptions import YTMusicError

from app.pandora import Pandora
from app.providers import ProviderError, save_json
from app.spotify import Spotify
from app.youtube import YouTubeMusic

spotify_pending: dict[str, dict] = {}
youtube_pending: dict[str, dict] = {}
LOGIN_LOCK = RLock()


def new_login(pending: dict, value: dict) -> str:
    now = time.time()
    with LOGIN_LOCK:
        for key in list(pending):
            if pending[key]['expires_at'] < now:
                del pending[key]
        if len(pending) >= 100:
            raise ProviderError("Too many pending sign-ins. Try again in a few minutes.", 429)
        identifier = secrets.token_urlsafe(32)
        pending[identifier] = value
        return identifier


def set_login_cookie(response: Response, name: str, value: str, request: Request, config: dict):
    response.set_cookie(name, value, max_age=600, httponly=True, samesite="lax",
                        secure=request.url.scheme == "https" or config.get("OAUTH_COOKIE_SECURE", "").lower() in {"true", "1", "yes"}, path="/api/")


def source_status(config, directory):
    return {
        "tidal": {"configured": True, "connected": (directory / "tidal-session.json").exists()},
        "spotify": {
            "configured": bool(config.get("SPOTIFY_CLIENT_ID") and config.get("SPOTIFY_CLIENT_SECRET")),
            "connected": (directory / "spotify-session.json").exists() or bool(config.get("SPOTIFY_REFRESH_TOKEN")),
        },
        "youtube_music": {
            "configured": bool(config.get("YOUTUBE_MUSIC_AUTH_FILE") or
                               (config.get("YOUTUBE_CLIENT_ID") and config.get("YOUTUBE_CLIENT_SECRET"))),
            "connected": (directory / "youtube-music-session.json").exists() or bool(config.get("YOUTUBE_MUSIC_AUTH_FILE")),
        },
        "pandora": {
            "configured": bool(config.get("PANDORA_LISTENBRAINZ_USERNAME") or config.get("LISTENBRAINZ_USERNAME")),
            "history_source": "ListenBrainz scrobbles",
        },
    }


def create_router(settings, config_dir) -> APIRouter:
    router = APIRouter()

    def spotify():
        return Spotify(settings(), config_dir())

    def youtube():
        return YouTubeMusic(settings(), config_dir())

    def youtube_call(action):
        try:
            return action()
        except ProviderError:
            raise
        except (YTMusicError, ValueError, KeyError, OSError):
            raise ProviderError("YouTube Music could not complete this request. Check the OAuth credentials, reconnect, and verify the playlist is available.", 502) from None

    @router.post("/api/spotify/login")
    def spotify_login(request: Request, response: Response):
        state = secrets.token_urlsafe(32)
        url = spotify().authorization_url(state)
        login = new_login(spotify_pending, {"state": state, "expires_at": time.time() + 600})
        set_login_cookie(response, "spotify_login", login, request, settings())
        return {"authorization_url": url}

    @router.get("/api/spotify/callback")
    def spotify_callback(request: Request, state: str = "", code: str = "", error: str = ""):
        login = request.cookies.get("spotify_login", "")
        with LOGIN_LOCK:
            pending = spotify_pending.pop(login, None)
        if not pending or pending['expires_at'] < time.time() or not secrets.compare_digest(state, pending['state']):
            raise ProviderError("Spotify sign-in state is invalid or expired. Start sign-in again in the same browser.")
        if error or not code:
            raise ProviderError("Spotify sign-in was declined. You can reconnect when ready.")
        spotify().complete_login(code)
        response = HTMLResponse('<!doctype html><title>Spotify connected</title><p>Spotify connected. Return to the bridge and load your playlists.</p><a href="/">Return to bridge</a>')
        response.delete_cookie("spotify_login", path="/api/")
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    @router.get("/api/spotify/playlists")
    def spotify_playlists():
        return spotify().playlists()

    @router.get("/api/spotify/playlists/{identifier}")
    def spotify_playlist(identifier: str):
        return spotify().playlist(identifier)

    @router.post("/api/youtube_music/login")
    def youtube_login(request: Request, response: Response):
        data = youtube_call(lambda: youtube().credentials().get_code())
        if not all(data.get(key) for key in ('device_code', 'user_code', 'verification_url')):
            raise ProviderError("Google rejected device sign-in. Use a YouTube Data API OAuth client for TVs and Limited Input devices.")
        login = new_login(youtube_pending, {**data, 'expires_at': time.time() + min(data.get('expires_in', 600), 600),
                                           'next_poll': 0})
        set_login_cookie(response, "youtube_login", login, request, settings())
        return {key: data[key] for key in ('user_code', 'verification_url', 'interval') if key in data}

    @router.post("/api/youtube_music/login/complete")
    def youtube_complete(request: Request, response: Response):
        login = request.cookies.get('youtube_login', '')
        with LOGIN_LOCK:
            pending = youtube_pending.get(login)
            if not pending or pending['expires_at'] < time.time():
                youtube_pending.pop(login, None)
                raise ProviderError("Start YouTube Music sign-in first; the previous code may have expired.")
            if pending['next_poll'] > time.time():
                return {'complete': False, 'reason': 'Wait a few seconds before checking again.'}
            pending['next_poll'] = time.time() + pending.get('interval', 5)
        token = youtube_call(lambda: youtube().credentials().token_from_code(pending['device_code']))
        issue = token.get('error')
        if issue in {'authorization_pending', 'slow_down'}:
            if issue == 'slow_down':
                with LOGIN_LOCK:
                    pending['interval'] = pending.get('interval', 5) + 5
                    pending['next_poll'] = time.time() + pending['interval']
            return {'complete': False, 'reason': 'Finish Google authorization, then check again.'}
        with LOGIN_LOCK:
            youtube_pending.pop(login, None)
        if issue or not token.get('refresh_token') or not token.get('access_token'):
            raise ProviderError("Google sign-in was denied or expired. Start YouTube Music sign-in again.")
        token['expires_at'] = int(time.time()) + token.get('expires_in', 3600)
        save_json(youtube().token_path, token)
        response.delete_cookie('youtube_login', path='/api/')
        return {'complete': True}

    @router.get('/api/youtube_music/playlists')
    def youtube_playlists():
        return youtube_call(lambda: youtube().playlists())

    @router.get('/api/youtube_music/playlists/{identifier}')
    def youtube_playlist(identifier: str):
        return youtube_call(lambda: youtube().playlist(identifier))

    @router.get('/api/pandora/history')
    def pandora_history():
        return Pandora(settings()).history()

    return router
