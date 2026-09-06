# Plex playlist matching and availability

Target: credential-ready Plex matching, saved choices/drafts, create/update, informative responsive UI; preserve existing source imports, Discord commands and ListenBrainz behavior. Carry forward user authorization to commit, push, update the Unraid template and deploy to peaches-unraid.

## Contract

1. Add PLEX_URL, masked PLEX_TOKEN, PLEX_MUSIC_LIBRARY (default Music). Connect with PlexAPI 4.18.2, bounded request timeouts, sanitize upstream errors and never return tokens or local file paths.
2. Match full ordered source tracks against the configured music library. Use conservative title/artist/album/duration matching. Never silently choose between versions. Return matched/missing/ambiguous/skipped rows with explanations and candidates. Preserve repeated source tracks. 'In Plex' means indexed in that library; users should scan new media first.
3. Save latest 20 scan drafts and explicit match choices under /config, scoped to Plex server/library/account token identity. Recheck fresh inventory after acquiring media. Invalidated configuration or track changes require a new check; arbitrary rating keys cannot be injected.
4. Create a regular Plex playlist using only matched tracks in source order. Store the source-to-Plex playlist mapping. Updates apply only to bridge-managed playlists, require an explicit UI update action, preserve the playlist identity, and never overwrite an unrelated same-name playlist. Append and verify new items before deleting old item instances; persist progress and report interrupted changes safely. Repeat completed saves are no-ops when the playlist still matches. Batch mutations in groups of 100; use a persisted unique staging name to recover an uncertain create. On retries, verify the appended prefix and continue only its remaining suffix. Block edits to an unfinished save's match choices. Validate current target metadata before writing, including recycled rating keys.
5. Redesign UI: source/setup sidebar, ordered track review, clear counts and accessible filters, per-row candidate choice, missing-only Discord requests, Plex save with included/omitted counts, saved-draft restore, collapsible raw track editor, friendly actionable empty/error/loading/configuration states. Preserve all TIDAL/Spotify/YouTube/Pandora and recommendation controls.

## API contract for frontend

GET /api/status adds plex: {configured:boolean, library_name:string} (no network request).
POST /api/plex/match accepts {source,playlist_name,playlist_url,tracks} using existing DispatchRequest track shape.
Response: {scan_id,source,playlist_name,playlist_url,library_name,server_name,library_tracks,checked_at,rows,counts,managed_playlist}.
rows: [{index,track,status:'matched'|'missing'|'ambiguous'|'skipped',match:candidate|null,candidates:[candidate],reason}].
candidate: {rating_key:string,title,artist,album,duration_ms}.
counts: {total,matched,missing,ambiguous,skipped}.
managed_playlist: null or {id:string,title:string}.
PATCH /api/plex/matches/{scan_id} accepts {index:int,rating_key:string|null}; null explicitly skips the row. Returns updated scan. Choices must be candidates from this scan.
GET /api/plex/drafts returns [{scan_id,source,playlist_name,playlist_url,checked_at,counts}].
GET /api/plex/matches/{scan_id} returns saved scan (restoring is not a fresh scan).
POST /api/plex/playlists accepts {scan_id,mode:'create'|'update',title:string}; returns {playlist_id,title,web_url,tracks,omitted,action:'created'|'updated'|'unchanged'}.
Errors use existing {detail:string}; no Plex mutations on match/search/status/restore. Draft scans remain separate from editable frontend state; edits/source changes invalidate scan until rechecked. Missing-only Discord uses original track rows with status missing, not ambiguous/skipped.

## Ownership / verification

Root owns backend, tests, configuration, docs, integration, commit and deployment. UI worker owns app/static/** in isolated worktree /tmp/music-bridge-plex-ui; cherry-pick only its UI commit. No workers may edit the other's files.
Backend tests: conservative and ambiguous matches, mixed-artist albums, missing metadata, duplicate/order preservation, saved preferences, namespace isolation, invalid selections, zero matches, wrong library/auth failure, duplicate save, safe update/partial failure and unrelated name collisions. Browser fixtures: all source flows, availability filters, choices, missing-only dispatch, save/update, draft restore, edited/stale state, narrow viewport and keyboard states. Independent review of final integrated behavior. Image tests and deployed-file hash/version checks.
