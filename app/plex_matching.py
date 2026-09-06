"""Conservative, explainable matching against an indexed Plex music library."""
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher

from app.providers import ProviderError

MAX_CANDIDATE_ENTRIES = 20000


def normalize(value) -> str:
    text = unicodedata.normalize('NFKD', value or '').casefold()
    text = ''.join(char for char in text if not unicodedata.combining(char))
    return ' '.join(re.sub(r'[^\w]+', ' ', text).split())


def fingerprint(track: dict) -> str:
    fields = [normalize(track.get(key)) for key in ('title', 'artist', 'album')]
    fields.append(track.get('duration_ms'))
    return hashlib.sha256(json.dumps(fields).encode()).hexdigest()


def duration_matches(source: dict, target: dict) -> bool:
    first, second = source.get('duration_ms'), target.get('duration_ms')
    if not first or not second:
        return True
    return abs(first - second) <= max(2000, min(5000, first * .02))


def match_tracks(tracks: list[dict], library: list[dict], preferences: dict) -> list[dict]:
    by_title, by_artist = defaultdict(list), defaultdict(list)
    by_key = {item['rating_key']: item for item in library}
    for item in library:
        by_title[normalize(item['title'])].append(item)
        by_artist[normalize(item['artist'])].append(item)
    rows = []
    candidate_entries = 0
    for index, track in enumerate(tracks):
        title, artist = normalize(track['title']), normalize(track['artist'])
        exact = [item for item in by_title[title] if normalize(item['artist']) == artist]
        strong = [item for item in exact if
                  (not track.get('album') or normalize(item['album']) == normalize(track['album']))
                  and duration_matches(track, item)]
        candidates = list(exact)
        if not candidates:
            candidates = [item for item in by_artist[artist]
                          if SequenceMatcher(None, title, normalize(item['title'])).ratio() >= .7]
            candidates += [item for item in by_title[title] if item not in candidates and
                           SequenceMatcher(None, artist, normalize(item['artist'])).ratio() >= .6]
        candidate_entries += len(candidates) + 1  # Includes a possible remembered choice.
        if candidate_entries > MAX_CANDIDATE_ENTRIES:
            raise ProviderError('This list has too many Plex versions to review at once. Check a smaller group of tracks, or remove duplicate library copies, then try again.', 413)
        candidates.sort(key=lambda item: (
            item not in strong, normalize(item['title']) != title,
            normalize(item.get('album')) != normalize(track.get('album')), item['rating_key']))
        selected = strong[0] if len(strong) == 1 else None
        reason = 'Artist, title and available album/duration details match.' if selected else ''
        saved = preferences.get(fingerprint(track))
        remembered = by_key.get(saved.get('rating_key')) if saved else None
        if remembered and fingerprint(remembered) == saved.get('fingerprint'):
            selected = remembered
            candidates = [remembered] + [item for item in candidates if item != remembered]
            reason = 'Using the version you chose previously.'
        if selected:
            status = 'matched'
        elif candidates:
            status = 'ambiguous'
            reason = 'Choose a version: multiple copies or different album, title, or duration details.'
        else:
            status = 'missing'
            reason = 'No close match in this Plex library. Scan new media in Plex, then recheck.'
        if selected and selected not in candidates:
            candidates = [selected] + candidates
        rows.append({'index': index, 'track': track, 'status': status, 'match': selected,
                     'candidates': candidates, 'reason': reason})
    return rows


def counts(rows: list[dict]) -> dict:
    return {'total': len(rows), **{status: sum(row['status'] == status for row in rows)
                                 for status in ('matched', 'missing', 'ambiguous', 'skipped')}}
