# TIDAL Playlist Bridge

A self-hosted Unraid web app for:

- TIDAL device OAuth and playlist retrieval.
- Posting selected TIDAL playlist tracks to Discord.
- Submitting only user-confirmed historical listens to ListenBrainz.
- Posting generated ListenBrainz recommendation playlists to Discord.

The app never treats a saved playlist as listening history automatically. Check the confirmation box only when the selected tracks represent real previous listens.

## Run on Unraid

Build the image from this repository, import `unraid/templates/tidal-playlist-bridge.xml`, then set the repository image name in the template. Map `/config` to `/mnt/user/appdata/tidal-playlist-bridge` and add this root-owned file:

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
