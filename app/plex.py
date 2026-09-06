"""Plex inventory, saved match drafts and bridge-managed music playlists."""
import hashlib
import json
import time
import uuid
from pathlib import Path
from threading import RLock
from urllib.parse import quote, urlsplit

from plexapi.server import PlexServer
from plexapi.exceptions import NotFound

from app.plex_matching import counts, fingerprint, match_tracks, normalize
from app.providers import ProviderError, load_json, require, save_json

STATE_LOCK = RLock()
BATCH_SIZE = 100


class Plex:
    def __init__(self, config: dict, directory: Path):
        self.config = {**config, 'PLEX_MUSIC_LIBRARY': config.get('PLEX_MUSIC_LIBRARY') or 'Music'}
        self.path = directory / 'plex-state.json'
        self.server = None
        self.section = None

    def config_id(self) -> str:
        values = [self.config.get(key, '') for key in ('PLEX_URL', 'PLEX_TOKEN')]
        values.append(self.config.get('PLEX_MUSIC_LIBRARY', 'Music'))
        return hashlib.sha256(json.dumps(values).encode()).hexdigest()

    def connect(self):
        if self.server is not None:
            return
        require(self.config, 'PLEX_URL', 'PLEX_TOKEN', 'PLEX_MUSIC_LIBRARY')
        url = urlsplit(self.config['PLEX_URL'])
        if url.scheme not in {'http', 'https'} or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ProviderError('PLEX_URL must be an HTTP or HTTPS server address without credentials or query parameters.')
        self.server = PlexServer(self.config['PLEX_URL'].rstrip('/'), self.config['PLEX_TOKEN'], timeout=30)
        self.section = self.server.library.section(self.config['PLEX_MUSIC_LIBRARY'])
        if self.section.type != 'artist':
            raise ProviderError('PLEX_MUSIC_LIBRARY must name a music library, not a movie or TV library.')

    def namespace(self) -> str:
        self.connect()
        return hashlib.sha256(f'{self.config_id()}:{self.server.machineIdentifier}:{self.section.key}'.encode()).hexdigest()

    def state(self) -> dict:
        data = load_json(self.path)
        for key in ('scans', 'preferences', 'managed', 'jobs'):
            data.setdefault(key, {})
        return data

    def inventory(self):
        self.connect()
        objects = {str(item.ratingKey): item for item in self.section.searchTracks()}
        records = []
        for key, item in objects.items():
            if not key.isdigit():
                continue
            artist = item.originalTitle or item.grandparentTitle or ''
            if not item.title or not artist:
                continue
            records.append({'rating_key': key, 'title': item.title, 'artist': artist,
                            'album': item.parentTitle or None, 'duration_ms': item.duration or None})
        return records, objects

    def public_scan(self, scan: dict, data: dict) -> dict:
        fields = ('scan_id', 'source', 'playlist_name', 'playlist_url', 'library_name', 'server_name',
                  'library_tracks', 'checked_at', 'rows')
        result = {key: scan[key] for key in fields}
        result['counts'] = counts(scan['rows'])
        result['managed_playlist'] = data['managed'].get(scan['namespace'], {}).get(scan['source_key'])
        return result

    def _scan(self, data: dict, scan_id: str) -> dict:
        scan = data['scans'].get(scan_id)
        if not scan or scan['config_id'] != self.config_id():
            raise ProviderError('This saved check is unavailable for the current Plex settings. Check the playlist again.', 404)
        if scan['namespace'] != self.namespace():
            raise ProviderError('Plex server or library changed. Check the playlist again.', 409)
        return scan

    def match(self, payload: dict) -> dict:
        tracks = payload['tracks']
        if not tracks:
            raise ProviderError('Load or enter at least one track before checking Plex.')
        records, objects = self.inventory()
        del objects
        namespace = self.namespace()
        with STATE_LOCK:
            data = self.state()
            preferences = data['preferences'].get(namespace, {})
            source_key = hashlib.sha256(json.dumps([payload['source'], payload['playlist_url'] or payload['playlist_name']]).encode()).hexdigest()
            scan = {key: payload[key] for key in ('source', 'playlist_name', 'playlist_url')}
            scan.update(scan_id=uuid.uuid4().hex, namespace=namespace, config_id=self.config_id(),
                        source_key=source_key, checked_at=int(time.time()), library_name=self.section.title,
                        server_name=self.server.friendlyName, library_tracks=len(records),
                        rows=match_tracks(tracks, records, preferences))
            data['scans'][scan['scan_id']] = scan
            while len(data['scans']) > 20:
                protected = {job['scan_id'] for job in data['jobs'].values()}
                oldest = next((key for key in data['scans'] if key not in protected), None)
                if oldest is None:
                    break
                del data['scans'][oldest]
            save_json(self.path, data)
            return self.public_scan(scan, data)

    def get_scan(self, scan_id: str) -> dict:
        with STATE_LOCK:
            data = self.state()
            return self.public_scan(self._scan(data, scan_id), data)

    def drafts(self) -> list[dict]:
        with STATE_LOCK:
            data = self.state()
            relevant = [scan for scan in data['scans'].values() if scan['config_id'] == self.config_id()]
            namespace = self.namespace() if relevant else None
            scans = [self.public_scan(scan, data) for scan in relevant if scan['namespace'] == namespace]
            return [{key: scan[key] for key in ('scan_id', 'source', 'playlist_name', 'playlist_url', 'checked_at', 'counts')}
                    for scan in reversed(scans)]

    def choose(self, scan_id: str, index: int, rating_key: str | None) -> dict:
        with STATE_LOCK:
            data = self.state()
            scan = self._scan(data, scan_id)
            if any(job['scan_id'] == scan_id for job in data['jobs'].values()):
                raise ProviderError('This check has an unfinished Plex save. Finish saving it before changing match choices.', 409)
            if not 0 <= index < len(scan['rows']):
                raise ProviderError('That track is not part of this saved check.')
            row = scan['rows'][index]
            candidate = next((item for item in row['candidates'] if item['rating_key'] == rating_key), None)
            if rating_key is not None and candidate is None:
                raise ProviderError('Choose one of the Plex versions shown for this track.')
            row.update(status='matched' if candidate else 'skipped', match=candidate,
                       reason='Using your selected Plex version.' if candidate else 'You chose to leave this track out of the Plex playlist.')
            if candidate:
                data['preferences'].setdefault(scan['namespace'], {})[fingerprint(row['track'])] = {
                    'rating_key': rating_key, 'fingerprint': fingerprint(candidate)}
            save_json(self.path, data)
            return self.public_scan(scan, data)

    def _result(self, playlist, scan, action):
        total = counts(scan['rows'])
        return {'playlist_id': str(playlist.ratingKey), 'title': playlist.title,
                'web_url': f'https://app.plex.tv/desktop/#!/server/{quote(self.server.machineIdentifier, safe="")}/details?key={quote("/playlists/" + str(playlist.ratingKey), safe="")}',
                'tracks': total['matched'], 'omitted': total['total'] - total['matched'], 'action': action}

    def save_playlist(self, scan_id: str, mode: str, title: str) -> dict:
        if mode not in {'create', 'update'} or not title.strip():
            raise ProviderError('Choose create or update and enter a playlist name.')
        records, inventory = self.inventory()
        current_metadata = {item['rating_key']: fingerprint(item) for item in records}
        with STATE_LOCK:
            data = self.state()
            scan = self._scan(data, scan_id)
            if scan['namespace'] != self.namespace():
                raise ProviderError('Plex server or library changed. Recheck before saving.', 409)
            selected = [row['match']['rating_key'] for row in scan['rows'] if row['status'] == 'matched']
            if not selected:
                raise ProviderError('No tracks are matched yet. Choose a Plex version or add the missing music first.')
            if any(key not in inventory for key in selected):
                raise ProviderError('A matched track is no longer in this library. Recheck before saving.', 409)
            if any(current_metadata.get(row['match']['rating_key']) != fingerprint(row['match'])
                   for row in scan['rows'] if row['status'] == 'matched'):
                raise ProviderError('Matched track details changed in Plex. Recheck before saving.', 409)
            items = [inventory[key] for key in selected]
            managed = data['managed'].setdefault(scan['namespace'], {})
            existing = managed.get(scan['source_key'])
            job_key = scan['namespace'] + scan['source_key']
            job = data['jobs'].get(job_key)
            if job and job.get('kind') == 'create':
                return self._create_playlist(data, scan, items, selected, title)
            for other in self.server.playlists():
                if normalize(other.title) == normalize(title) and (not existing or str(other.ratingKey) != existing['id']):
                    raise ProviderError('A Plex playlist with this name already exists and is not this bridge playlist. Choose another name.', 409)
            if existing:
                try:
                    playlist = self.server.fetchItem('/playlists/' + existing['id'])
                except NotFound:
                    del managed[scan['source_key']]
                    data['jobs'].pop(job_key, None)
                    save_json(self.path, data)
                    raise ProviderError('The previous Plex playlist was deleted. Reload this saved check, then choose Create playlist to make a replacement.', 409) from None
                if playlist.playlistType != 'audio' or playlist.smart:
                    raise ProviderError('This Plex playlist is no longer a regular music playlist.', 409)
                actual = [str(item.ratingKey) for item in playlist.items()]
                if actual == selected and playlist.title == title:
                    data['jobs'].pop(scan['namespace'] + scan['source_key'], None)
                    save_json(self.path, data)
                    return self._result(playlist, scan, 'unchanged')
                if mode != 'update':
                    raise ProviderError('This source already has a Plex playlist. Choose Update playlist to replace its track list.', 409)
                self._update_playlist(data, scan, playlist, items, selected)
                if playlist.title != title:
                    playlist.editTitle(title)
                    playlist.reload()
                action = 'updated'
            else:
                if mode != 'create':
                    raise ProviderError('Create the Plex playlist before trying to update it.', 409)
                return self._create_playlist(data, scan, items, selected, title)
            managed[scan['source_key']] = {'id': str(playlist.ratingKey), 'title': title}
            save_json(self.path, data)
            return self._result(playlist, scan, action)

    def _create_playlist(self, data, scan, items, selected, title):
        """A unique staging name makes a lost create response safely discoverable."""
        job_key = scan['namespace'] + scan['source_key']
        job = data['jobs'].get(job_key)
        if not job:
            job = {'kind': 'create', 'scan_id': scan['scan_id'], 'selected': selected,
                   'title': title, 'staging_title': 'Music Bridge pending ' + uuid.uuid4().hex}
            data['jobs'][job_key] = job
            save_json(self.path, data)
        elif job['selected'] != selected or job['title'] != title:
            raise ProviderError('A previous create is unfinished. Restore its saved check and use the same playlist name to finish it.', 409)
        if job.get('playlist_id'):
            try:
                playlist = self.server.fetchItem('/playlists/' + job['playlist_id'])
            except NotFound:
                data['jobs'].pop(job_key, None)
                save_json(self.path, data)
                raise ProviderError('The pending Plex playlist was deleted. Choose Create playlist again to start over.', 409) from None
        else:
            found = [p for p in self.server.playlists() if p.title == job['staging_title']]
            if len(found) > 1:
                raise ProviderError('Multiple pending Plex playlists were found. Review them in Plex before retrying.', 409)
            playlist = found[0] if found else self.server.createPlaylist(title=job['staging_title'], items=items[:BATCH_SIZE])
            job['playlist_id'] = str(playlist.ratingKey)
            save_json(self.path, data)
        if playlist.playlistType != 'audio' or playlist.smart:
            raise ProviderError('The pending Plex playlist is no longer a regular music playlist.', 409)
        self._append_remaining(playlist, items, selected, [], [])
        # Recheck name collisions after recovery, before renaming the staging list.
        if any(normalize(p.title) == normalize(title) and str(p.ratingKey) != str(playlist.ratingKey)
               for p in self.server.playlists()):
            raise ProviderError('Another Plex playlist now uses that name. Rename it in Plex, then retry this saved check.', 409)
        if playlist.title != title:
            playlist.editTitle(title)
            playlist.reload()
        data['managed'].setdefault(scan['namespace'], {})[scan['source_key']] = {
            'id': str(playlist.ratingKey), 'title': title}
        data['jobs'].pop(job_key, None)
        save_json(self.path, data)
        return self._result(playlist, scan, 'created')

    def _append_remaining(self, playlist, items, selected, old_keys, old_ids):
        """Verify a source prefix on every retry and append only its missing suffix."""
        while True:
            current = list(playlist.items())
            keys = [str(item.ratingKey) for item in current]
            original_ids = [str(item.playlistItemID) for item in current[:len(old_ids)]]
            appended = keys[len(old_keys):]
            if (original_ids != old_ids or keys[:len(old_keys)] != old_keys or
                    len(appended) > len(selected) or appended != selected[:len(appended)]):
                raise ProviderError('The Plex playlist changed during the save. The original playlist has been kept; review it in Plex before retrying.', 409)
            if len(appended) == len(selected):
                return current
            playlist.addItems(items[len(appended):len(appended) + BATCH_SIZE])
            playlist.reload()
            if len(playlist.items()) <= len(current):
                raise ProviderError('Plex did not confirm the new tracks. The original playlist has been kept. Retry this saved check to continue.', 409)

    def _update_playlist(self, data, scan, playlist, items, selected):
        """Append and verify first; remove old item instances only after confirmation."""
        job_key = scan['namespace'] + scan['source_key']
        job = data['jobs'].get(job_key)
        current = list(playlist.items())
        if not job:
            job = {'scan_id': scan['scan_id'], 'playlist_id': str(playlist.ratingKey), 'selected': selected,
                   'old_ids': [str(item.playlistItemID) for item in current],
                   'old_keys': [str(item.ratingKey) for item in current], 'phase': 'append'}
            data['jobs'][job_key] = job
            save_json(self.path, data)
        elif job['selected'] != selected or job['playlist_id'] != str(playlist.ratingKey):
            raise ProviderError('An earlier update is unfinished. Restore its saved check and finish that update first.', 409)
        if job['phase'] == 'append':
            old_count = len(job['old_ids'])
            current = self._append_remaining(playlist, items, selected, job['old_keys'], job['old_ids'])
            job.update(phase='cleanup', new_ids=[str(item.playlistItemID) for item in current[old_count:]])
            save_json(self.path, data)
        allowed = set(job['old_ids'] + job['new_ids'])
        current_ids = [str(item.playlistItemID) for item in current]
        new_items = [item for item in current if str(item.playlistItemID) in set(job['new_ids'])]
        if (not set(current_ids) <= allowed or
                [str(item.playlistItemID) for item in new_items] != job['new_ids'] or
                [str(item.ratingKey) for item in new_items] != selected):
            raise ProviderError('The Plex playlist changed during the update. No further tracks were removed; review it in Plex.', 409)
        for item in current:
            identifier = str(item.playlistItemID)
            if identifier in job['old_ids']:
                # Use occurrence IDs, not track keys, so duplicates are handled correctly.
                self.server.query(f'/playlists/{playlist.ratingKey}/items/{identifier}', method=self.server._session.delete)
        playlist.reload()
        if [str(item.ratingKey) for item in playlist.items()] != selected:
            raise ProviderError('The update is incomplete. Check Plex, then retry this saved playlist to resume.', 502)
        data['jobs'].pop(job_key, None)
        save_json(self.path, data)
