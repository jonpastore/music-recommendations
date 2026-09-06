"""Validated Plex actions. Browser-supplied keys never bypass saved match candidates."""
from typing import Literal

import requests
from fastapi import APIRouter
from plexapi.exceptions import NotFound, PlexApiException, Unauthorized
from pydantic import BaseModel, Field, field_validator

from app.models import DispatchRequest
from app.plex import Plex
from app.providers import ProviderError


class MatchChoice(BaseModel):
    index: int = Field(ge=0)
    rating_key: str | None = Field(default=None, pattern=r'^\d{1,20}$')


class PlaylistSave(BaseModel):
    scan_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    mode: Literal['create', 'update']
    title: str = Field(min_length=1, max_length=200)

    @field_validator('title')
    @classmethod
    def title_not_blank(cls, value):
        value = ' '.join(value.split())
        if not value:
            raise ValueError('Enter a playlist name')
        return value


def plex_status(config: dict) -> dict:
    return {'configured': bool(config.get('PLEX_URL') and config.get('PLEX_TOKEN')),
            'library_name': config.get('PLEX_MUSIC_LIBRARY') or 'Music'}


def create_router(settings, config_dir) -> APIRouter:
    router = APIRouter()

    def call(action, writing=False):
        try:
            return action(Plex(settings(), config_dir()))
        except ProviderError:
            raise
        except Unauthorized:
            raise ProviderError('Plex rejected the token. Check PLEX_TOKEN and its access to your music library.', 401) from None
        except NotFound:
            raise ProviderError('Plex could not find that music library or playlist. Check PLEX_MUSIC_LIBRARY and recheck your tracks.', 404) from None
        except (requests.RequestException, PlexApiException, OSError, ValueError, KeyError):
            message = ('Plex could not confirm the save. Your check is saved; review the playlist in Plex before retrying. '
                       'If an update stopped partway through, retry the same saved check to resume safely.' if writing else
                       'Plex could not load your music library. Check the server address, token and library name, then try again.')
            raise ProviderError(message, 502) from None

    @router.post('/api/plex/match')
    def match(request: DispatchRequest):
        return call(lambda client: client.match(request.model_dump()))

    @router.get('/api/plex/drafts')
    def drafts():
        return call(lambda client: client.drafts())

    @router.get('/api/plex/matches/{scan_id}')
    def get_match(scan_id: str):
        return call(lambda client: client.get_scan(scan_id))

    @router.patch('/api/plex/matches/{scan_id}')
    def choose(scan_id: str, request: MatchChoice):
        return call(lambda client: client.choose(scan_id, request.index, request.rating_key))

    @router.post('/api/plex/playlists')
    def save(request: PlaylistSave):
        return call(lambda client: client.save_playlist(request.scan_id, request.mode, request.title), writing=True)

    return router
