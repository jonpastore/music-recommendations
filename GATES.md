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
