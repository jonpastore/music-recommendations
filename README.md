# TIDAL Playlist Bridge

Current local image version: `0.4.3`.

A self-hosted Unraid web app for:

- TIDAL device OAuth and playlist retrieval.
- Posting selected TIDAL playlist tracks to Discord.
- Submitting only user-confirmed historical listens to ListenBrainz.
- Posting generated ListenBrainz recommendation playlists to Discord.

The app never treats a saved playlist as listening history automatically. Check the confirmation box only when the selected tracks represent real previous listens.

## Run on Unraid

Import `unraid/templates/tidal-playlist-bridge.xml` into Unraid Docker Manager. The template exposes editable fields for the Discord webhook and ListenBrainz credentials. Map `/config` to `/mnt/user/appdata/tidal-playlist-bridge/config`.

To rebuild and redeploy a local release from this repository:

```bash
VERSION=0.4.3
docker build --build-arg VERSION="$VERSION" -t tidal-playlist-bridge:"$VERSION" .
docker rm -f tidal-playlist-bridge
# Recreate from the Unraid template, selecting tidal-playlist-bridge:$VERSION.
```

The container reports its running version at `GET /api/status`. Its mounted configuration can also use this root-owned file:

```dotenv
DISCORD_WEBHOOK_URL=...
LISTENBRAINZ_USERNAME=...
LISTENBRAINZ_TOKEN=...
```

Open `http://UNRAID-IP:8090/`, select **Connect TIDAL**, complete the device authorization, load a playlist, and choose the action to perform.

## Development

```bash
python3 -m unittest discover -s tests -v
docker build -t tidal-playlist-bridge:local .
```

TIDAL OAuth uses the `tidalapi` client library. TIDAL's official OAuth authorization model uses access and refresh tokens; the app stores its resulting session only in the mounted `/config` directory, never in Git.

## Service adapters

TIDAL, Spotify, YouTube, Apple Music, and Navidrome use account-specific authorization. Pandora does not provide a supported server-side playlist/history API, so it requires a device or browser scrobbler to submit actual plays to ListenBrainz. YouTube Music likewise requires a dedicated history scrobbler; the official YouTube Data API is used for ordinary YouTube playlists.
