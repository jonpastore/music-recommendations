# Music source integration plan

Goal: extend the existing Unraid application with Spotify and YouTube Music playlists and actual Pandora listens, ready for credential testing. Preserve TIDAL and the Discord requestlist/auto sequence. Target: credential-ready slice; live account verification waits for user credentials.

Architecture: individual provider adapters normalize to the current title/artist/album/duration model. Source metadata travels through Discord and ListenBrainz formatting. A single source selector feeds the existing editable track list. No background posting or inferred playlist listens.

## Tasks and acceptance

1. Spotify (`app/spotify.py`, provider routes, tests): authorization-code sign-in with expiring, browser-bound state; optional refresh token from environment; token refresh and restricted file persistence; paginate /me/playlists and /playlists/{id}/items; skip unavailable items and podcasts; explain ownership/403 and rate limits.
2. YouTube Music (`app/youtube.py`, provider routes, tests): pinned ytmusicapi client; device sign-in and saved OAuth; optional browser-auth file; complete playlist pagination and normalized artist/album metadata; actionable missing/expired auth errors.
3. Pandora (`app/pandora.py`, provider routes, tests): import actual timestamped Pandora scrobbles from ListenBrainz, filtering by source and paginating a bounded window. Never present recentFavorites as chronological listens. Explain scrobbler setup and the inability to backfill plays not recorded there.
4. Shared UI/dispatch (`app/main.py`, `app/static/*`, `app/playlist.py`, tests): preserve TIDAL login and all formats; source selection, loading/error/empty states, review/edit tracks; correct source links and listen metadata; user confirmation before submitting historical listens; do not re-submit Pandora listens already in ListenBrainz.
5. Configuration/docs: add every consumed setting to .env.example and Unraid template, mask credentials, document OAuth steps and limits. Build next image and update server/template for credential entry with existing config intact.

Verification: unittest provider fixtures for authentication, pagination, missing metadata, error paths, source attribution and Discord sequencing; browser exercise of each source and existing TIDAL controls; image tests and deployment status. Never send real Discord messages or submit listens in tests.

Python/FastAPI and browser JS: use existing unittest and syntax checks; no repository lint/complexity tooling exists. Keep provider-specific modules bounded, inspect token boundaries and branching manually, exclude vendor code. Independent review before release. Root owns all writes; a read-only researcher verified Pandora feasibility.

Sources: Spotify current Web API /playlists/{id}/items and authorization-code docs; ytmusicapi 1.12.2 OAuth and playlist references; Pandora recentFavorites/GraphQL overview; ListenBrainz core listens API. URLs and operational setup are recorded in README.

## Verification and review record

2026-09-06: all five work packages implemented. 30 unit/integration tests pass locally and in the 0.5.0 container. Browser fixtures passed for all four source flows, metadata preservation (including em dashes), validation/error states, and responsive layout at 390px. An independent adversarial review found partial-operation reporting and TLS-proxy cookie-policy gaps; both were addressed and re-reviewed with no remaining blocker. Exactly-once external posting remains future hardening: the app never automatically retries writes, reports confirmed/uncertain progress, and documents checking external state before manual retries. Live account tests await user-supplied Spotify/Google credentials and Pandora scrobbles.
