# Music Playlist Bridge

Current local image version: `0.6.0`.

A self-hosted Unraid web app that loads TIDAL, Spotify, and YouTube Music playlists, plus Pandora listens recorded in ListenBrainz. Match those tracks to your Plex music library, review what you have or are missing, and recreate the playlist in Plex. Review/edit the tracks, choose unique artists, unique albums, or full tracks, and post to Discord. Every request entry uses `!requestlist `, even for a single entry, and a separate `!auto on` follows only after successful posting.

Playlist imports do not automatically become listening history. The optional ListenBrainz action requires confirmation and a historical listening time. Pandora scrobbles are already in ListenBrainz and are never re-submitted. ListenBrainz recommendations are account-wide, may take time to update, and are not generated instantly from the selected list. No recommendations means no Discord or auto message.

## Run on Unraid

Import `unraid/templates/tidal-playlist-bridge.xml` into Docker Manager. Use image `tidal-playlist-bridge:0.6.0`, port `8090`, and map `/config` to `/mnt/user/appdata/tidal-playlist-bridge/config`. Open `http://UNRAID-IP:8090/`.

All fields below are available in the Unraid template. You can instead put them in the mounted `/config/.env` (one `KEY=value` per line, no shell quoting). Nonempty file values override container environment values. Store secrets in your Unraid configuration, never in Git. Saved OAuth tokens are persisted in `/config` across rebuilds. Changing an environment field requires applying/recreating the container; changing `.env` is picked up on the next request.

This is a single-user app for a trusted LAN. There is no application account/login layer. Put authenticated access in front of it if exposing it beyond your trusted network.

| Setting | Purpose |
| --- | --- |
| `PLEX_URL` | Plex server address reachable from the bridge, e.g. `http://peaches-unraid:32400` |
| `PLEX_TOKEN` | Plex user token; playlists belong to this user |
| `PLEX_MUSIC_LIBRARY` | Exact music library name; defaults to `Music` |
| `DISCORD_WEBHOOK_URL` | Required for Discord posting |
| `LISTENBRAINZ_USERNAME` | Recommendations account and default Pandora history account |
| `LISTENBRAINZ_TOKEN` | Required to submit confirmed historical listens |
| `SPOTIFY_CLIENT_ID` | Spotify developer application client ID |
| `SPOTIFY_CLIENT_SECRET` | Spotify developer application secret |
| `SPOTIFY_REDIRECT_URI` | Exact registered callback; default `http://127.0.0.1:8090/api/spotify/callback` |
| `SPOTIFY_REFRESH_TOKEN` | Optional alternative to signing in through the interface |
| `YOUTUBE_CLIENT_ID` | Google OAuth client ID for **TVs and Limited Input devices** |
| `YOUTUBE_CLIENT_SECRET` | Matching Google OAuth secret |
| `YOUTUBE_MUSIC_AUTH_FILE` | Optional alternative: container path to a `ytmusicapi` browser-auth JSON file |
| `PANDORA_LISTENBRAINZ_USERNAME` | Optional override for the account receiving Pandora scrobbles |
| `OAUTH_COOKIE_SECURE` | Set `true` when using an HTTPS reverse proxy; default `false` for LAN/loopback HTTP |
| `PANDORA_HISTORY_LIMIT` | Maximum Pandora listens to load, 1–1000; default 200 |

### TIDAL

Choose TIDAL, click **Connect TIDAL**, open the sign-in link, authorize, then click **Finish TIDAL login** and **Load playlists**. This retains the existing TIDAL device OAuth integration and saved session.

### Spotify

1. Create a Spotify developer application and configure the client ID and secret. Add the exact `SPOTIFY_REDIRECT_URI` to its allowlist. Spotify's current development-mode access restrictions apply, including the app owner's Premium requirement and authorized-user access. See [Spotify development-mode changes](https://developer.spotify.com/documentation/web-api/references/changes/february-2026).
2. Spotify requires HTTPS redirects except for explicit loopback IP addresses. Plain `http://peaches-unraid:8090` callbacks are not accepted. For the default local setup, run this on the computer whose browser you will use:

   ```bash
   ssh -N -L 8090:127.0.0.1:8090 root@peaches-unraid
   ```

   Then open **`http://127.0.0.1:8090/`** in that browser and perform the entire sign-in there. Register `http://127.0.0.1:8090/api/spotify/callback` in Spotify. This keeps the browser-bound sign-in cookie on the same origin. Alternatively use an HTTPS reverse proxy, set `OAUTH_COOKIE_SECURE=true`, and register its `/api/spotify/callback` URL. Start sign-in through that HTTPS URL.
3. Choose Spotify, click **Connect Spotify**, open the sign-in link, and grant `playlist-read-private playlist-read-collaborative`. Return to the bridge and load playlists. Tokens refresh automatically and are stored as private files. An existing refresh token with those scopes can be provided instead.
4. Spotify currently permits playlist item access only when you own the playlist or are a collaborator. Followed/editorial/generated playlists may be listed but their contents can return 403. The adapter uses the current `/v1/playlists/{id}/items` endpoint, follows all pages, and skips unavailable tracks and podcast episodes.

API references: [authorization code](https://developer.spotify.com/documentation/web-api/tutorials/code-flow), [redirect URI requirements](https://developer.spotify.com/documentation/web-api/concepts/redirect_uri), [playlist items](https://developer.spotify.com/documentation/web-api/reference/get-playlists-items).

### YouTube Music

1. Enable **YouTube Data API v3** in your Google Cloud project. Configure the consent screen and add your account as a test user if the project is in testing. Create an OAuth client of type **TVs and Limited Input devices**; enter its ID and secret in the Unraid fields above.
2. Choose YouTube Music, click **Connect YouTube Music**, open Google's link and enter the displayed code. After authorization click **Finish YouTube Music login**, then **Load playlists**. The token persists in `/config/youtube-music-session.json`; the client refreshes it as needed.
3. Alternatively, follow the library's [browser authentication instructions](https://ytmusicapi.readthedocs.io/en/stable/setup/browser.html), save `browser.json` in the config mount, and set `YOUTUBE_MUSIC_AUTH_FILE=/config/browser.json`. This file contains sensitive session credentials. Browser authentication takes precedence over saved device OAuth; clear the field to return to device OAuth.
4. Public playlists can also be loaded by link or ID without signing in. Loading your private library requires authentication. The adapter requests all library playlists and all playlist tracks rather than the library's default first-page limits.

This integration uses the **unofficial `ytmusicapi` client**, which emulates YouTube Music's web requests; it is not an official YouTube Music API. Google's OAuth credentials alone do not provide a native Music playlist API. See [ytmusicapi OAuth setup](https://ytmusicapi.readthedocs.io/en/stable/setup/oauth.html) and [playlist methods](https://ytmusicapi.readthedocs.io/en/stable/reference/playlists.html). Changes to YouTube Music can require a client update.

### Pandora listens

**Scrobbling is required for actual Pandora history.** Pandora's documented partner GraphQL API provides [recent favorites](https://developer.pandora.com/docs/reference/graphql-api/listener/get-a-listeners-recent-favorites/), a ranked summary of favorites, not a chronological listen log. This app does not invent a native history endpoint or ask for a Pandora password.

1. Configure a Pandora-compatible scrobbler to submit your actual plays to ListenBrainz. For browser playback, [Web Scrobbler](https://github.com/web-scrobbler/web-scrobbler) supports ListenBrainz; connect it to your ListenBrainz account and listen on Pandora in that browser. Plays from other devices require a scrobbler on those devices.
2. Set `LISTENBRAINZ_USERNAME`, or `PANDORA_LISTENBRAINZ_USERNAME` if the history belongs to another account. No Pandora API key or password is needed. History reads use the public [ListenBrainz listens API](https://listenbrainz.readthedocs.io/en/latest/users/api/core.html).
3. Choose Pandora and click **Load Pandora listens**. The app scans up to 10 pages / 10,000 recent mixed-source listens, keeps entries whose service or origin is Pandora, and returns up to `PANDORA_HISTORY_LIMIT`. Original timestamps are retained. Missing source tags cannot reliably be identified as Pandora and are excluded.
4. Review and post the tracks to Discord. **Post existing recommendations** uses the configured `LISTENBRAINZ_USERNAME`'s existing recommendations and does not submit the Pandora listens again.

Only previously recorded scrobbles are available. Earlier native Pandora history cannot be backfilled through this integration. If nothing appears, verify that the scrobbler has submitted a completed play with Pandora source metadata.

## Match and recreate playlists in Plex

1. Add your media to Plex and let its music library scan finish. Set `PLEX_URL`, `PLEX_TOKEN`, and `PLEX_MUSIC_LIBRARY` in Unraid. The server URL must be reachable **from the bridge container**; `127.0.0.1` inside it refers to the bridge, not a separate Plex container. For your server, `http://peaches-unraid:32400` may be appropriate if Plex exposes that port.
2. Load a full source playlist or restore one of your saved checks. Check it against Plex. Nothing is posted or changed in Plex during matching.
3. Review the availability counts and track list:
   - **In Plex:** one confident match, or the version you selected.
   - **Missing:** no close match found in the configured library.
   - **Needs a choice:** there are multiple copies or different album/title/duration details. Choose the intended version; the bridge remembers your choice.
   - **Skipped:** you explicitly left the track out of the Plex playlist.
4. Request only missing tracks through Discord, or use the existing all-track action. Ambiguous and skipped rows are not automatically treated as missing. Artist/album deduplication only affects Discord requests; Plex uses the original individual tracks and preserves their order and repeats.
5. Create the Plex playlist with its name and matched tracks. The UI reports how many tracks will be included and left out. Missing/unresolved tracks are never silently replaced with another recording. Playlists use existing Plex library entries; the bridge does not copy audio or need your media directories mounted.
6. After acquiring more music, scan the Plex library and recheck the saved source list. Then explicitly update its Plex playlist. Only playlists created and tracked by this bridge are updated; unrelated same-name playlists are left alone. Source URL identifies the source playlist (manual lists without a URL use their name).

Find your token using Plex's [authentication token instructions](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/), then enter it only in your Unraid/config settings. The XML method described there yields a temporary token that may need renewal; Plex also links instructions for a permanent token. The bridge uses the [Python PlexAPI client](https://python-plexapi.readthedocs.io/en/stable/modules/playlist.html). The token's Plex user owns the created playlists. Tokens are never sent to the browser or included in Plex links.

**Matching is conservative.** It compares normalized title/artist, album when supplied, and duration when both sides have it. It preserves words such as “live” or “remix” instead of silently stripping them. Tracks on Various Artists albums use their track artist. YouTube videos with incomplete metadata may need a manual choice or corrected source details. “In Plex” means the item is indexed in that music library; it is not a fresh filesystem/playback check. Keep your Plex library scanned to remove stale items.

The latest 20 checks, complete source track lists, manual choices, and source-to-Plex playlist identities persist in `/config/plex-state.json` (private file permissions). Checks needed for interrupted updates are retained. They are scoped to server, library and token settings so changing accounts cannot reuse another account's choices or playlist IDs. A restored check shows its original timestamp; recheck for current availability. Editing tracks invalidates the UI's availability results until you check again.

**Updates protect the existing playlist.** The bridge adds the desired sequence and verifies it before removing old playlist-item occurrences, preserving the playlist ID and handling repeated tracks individually. Requests are batched in groups of at most 100 tracks. Progress is saved so a retry can resume a partial append or cleanup. New playlists use a temporary, unique name until all tracks are confirmed, which lets the bridge recover a create whose response was lost. If you delete a managed playlist in Plex, retry, reload the saved check, and explicitly create its replacement. If Plex cannot confirm an operation, the UI explains the uncertainty; check the playlist before retrying the same saved check. There can temporarily be both old and new items during an interrupted update. The bridge does not claim an atomic transaction across Plex and its local state file. A check allows up to 20,000 candidate entries across its rows; lists with excessive duplicate versions are rejected with an instruction to check a smaller group, never silently truncated. Each check/save reads the full library index, so large libraries can take longer; avoid editing a playlist in Plex while the bridge is saving it.

## Build and development

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -v
node --check app/static/app.js
VERSION=0.6.0
docker build --build-arg VERSION="$VERSION" -t tidal-playlist-bridge:"$VERSION" .
```

Recreate the Unraid container with the new image using the existing port, config mount, environment, labels and restart policy. Keep the previous stopped container/image available until `GET /api/status` reports the new version and the interface responds. Disable automatic restart on a retained rollback container to avoid a port conflict on reboot. Do not delete the config mount.

Tests mock external services and cover pagination, source attribution, auth state, errors, and ordered Discord posts. Credential-free tests cannot prove live provider account permissions or the receiving Discord bot's interpretation of webhook commands; verify those with your account after supplying configuration.

Posts are not automatically retried. Partial failures report the confirmed message/listen count; the last timed-out operation may still have been accepted. Check Discord/ListenBrainz before manually retrying, since external APIs do not offer an exactly-once guarantee here.
