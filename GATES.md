# Gates: additional music sources

OWNS: app/**, tests/**, requirements.txt, requirements-dev.txt, Dockerfile, README.md, .env.example, unraid/**, docs/**

Scope: Credential-ready Spotify and YouTube Music playlists and Pandora scrobbled listens through the existing Discord workflow.

- [x] G1: Provider and shared-flow regression tests pass with external services mocked.
  CHECK: /tmp/tidal-bridge-test-venv/bin/python -m unittest discover -s tests -v
  EXPECT: OK
  EVIDENCE: 2026-09-06: 30 tests passed locally and inside image eeb58146c175; processes exited 0 and unittest reported OK.
- [x] G2: Browser source selection, validation, loading, errors and mobile layout work.
  EVIDENCE: Playwright exercised all four sources and four serialized dispatch payloads, source switching, missing credentials, empty input, listen confirmation, and em-dash metadata preservation. 1280px desktop and 390px mobile screenshots inspected; no page errors or horizontal overflow. Artifacts: output/playwright/music-desktop.png and music-mobile.png (local only).
- [x] G3: Every required provider setting has a documented Unraid field; secrets remain server-side.
  EVIDENCE: XML/.env key parity and secret masking checks passed. Independent adversarial review and targeted re-review found no remaining blockers after partial-progress reporting and OAUTH_COOKIE_SECURE fixes; 30 tests and JS syntax check passed.
- [x] G4: Built image passes tests and redeployed app reports the new version with saved configuration preserved.
  EVIDENCE: Image sha256:eeb58146c1759cea0eb4743439278fe11592ad818687d08c3bc348599488452f passed 30 tests. peaches-unraid reports 0.5.0; root page returns HTTP 200; all deployed app hashes equal local files. Discord/ListenBrainz configuration, TIDAL session, port/mounts/labels retained. Server template contains all new fields and the 0.5.0 image; stopped rollback-0.4.4 retained with restart disabled.

Live account tests are a subsequent user-credential checkpoint, not a claim of this slice. Pandora history requires prior scrobbling; native-history backfill is not documented by Pandora.


## Plex playlist slice (0.6.0)

- [x] P1: Matching classifies present/missing/ambiguous, remembers choices, preserves original order and duplicates, and validates library/account boundaries.
  CHECK: /tmp/tidal-bridge-test-venv/bin/python -m unittest discover -s tests -v
  EXPECT: OK
  EVIDENCE: 2026-09-06: 56 tests passed locally and in production image sha256:7665e0baf7475fcd1d387be48570bb6edd71e13017e55b03d3a9744ab5d31471; unittest OK, exit 0.
- [x] P2: Create/update preserves playlist identity, protects originals until new items are confirmed, handles duplicate occurrences and interrupted cleanup, and refuses unrelated same-name lists.
  EVIDENCE: Batched create/update, duplicate occurrences, partial append/deletion recovery, lost create response, deleted managed playlist, changed namespace/metadata, and response-budget tests passed. Independent adversarial re-review closed all reported blockers, including targeted 23-test Plex verification. Candidate choices cannot change an unfinished save.
- [x] P3: Responsive UI shows availability, filters, resolves choices, restores drafts, requests only missing tracks, and invalidates edited results while preserving all original source flows.
  EVIDENCE: Playwright exercised all four source imports and dispatch payloads, candidate PATCH, exact missing-only payload with duration, draft/source restoration, saved result/link, UNIX-second timestamp, edited track/name stale guards, and manual counts. Desktop 1280px and mobile 390px screenshots inspected; no page errors or horizontal overflow. Final artifacts: output/playwright/plex-desktop-final.png and plex-mobile-final.png (local only).
- [x] P4: Plex settings are available in Unraid with masked token, docs explain matching/account/scan limits, and deployed files match the pushed source.
  EVIDENCE: Image sha256:7665e0baf7475fcd1d387be48570bb6edd71e13017e55b03d3a9744ab5d31471 passed 56 tests. Unraid reports 0.6.0, HTTP 200, all 16 app file hashes equal workspace, all four sources present. Template/env parity and secret masks verified; installed template fields preserve existing values. TIDAL session, Discord/ListenBrainz configuration, mounts and ports retained; stopped rollback-0.5.0 retained with restart disabled. Live browser shows the Plex setup message and all four sources without page errors.

Live Plex account matching/saves await PLEX_URL and PLEX_TOKEN; Spotify and YouTube Music also await credentials. Automated provider/Plex calls used mocks and browser fixtures; no test Discord messages were posted.

## Dark theme and TIDAL login controls (0.6.1)

- [x] Dark desktop/mobile layout and adjacent pending/completed-login notifications; logout/cancel and saved-session controls.
  EVIDENCE: Playwright verified pending versus complete feedback, logout/reconnect, reload reuse, one authorization start, dark color scheme, no page errors/overflow, all four source dispatch payloads, and Plex review regression. Screenshots: output/playwright/dark-login-desktop.png and dark-login-mobile.png (local only).
- [x] Credentials persist privately across restarts and refresh, while logout cannot be undone by an in-flight read.
  EVIDENCE: 67 tests pass locally and in production image ba370fae8b2d279c5256976e12e2c78e7a5a53e0decc9b45b877a29876c4f7f7. Tests cover active/pending separation, rejected/false/revoked authorization, valid-session reuse, private atomic storage, refresh writes, pending reuse and logout. Independent targeted review found no remaining material blockers.
- [x] Unraid deployment preserves configured services, and live TIDAL access works after container replacement.
  EVIDENCE: 0.6.1 is healthy; all 16 deployed app hashes match the workspace. Live saved authorization loaded 51 playlists without a new login. Credential-file mode is 0600; Plex still uses LAN. Prior 0.6.0 container retained stopped with restart disabled.
