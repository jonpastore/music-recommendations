'use strict';
const byId = id => document.getElementById(id);
const sourceNames = {tidal: 'TIDAL', spotify: 'Spotify', youtube_music: 'YouTube Music', pandora: 'Pandora'};
const help = {
  tidal: 'Connect your TIDAL account, then load a playlist.',
  spotify: 'Connect Spotify to load your playlists. Spotify permits reading contents of playlists you own or collaborate on.',
  youtube_music: 'Connect to load your library, or paste a public playlist link. YouTube Music uses the unofficial ytmusicapi client.',
  pandora: 'Loads Pandora plays already scrobbled to ListenBrainz. Configure a Pandora-compatible scrobbler first; earlier unrecorded plays cannot be recovered.'
};
let source = 'tidal';
let originalTracks = [];
let busy = false;
function report(text, error = false) {
  byId('status').textContent = text;
  byId('status').classList.toggle('error', error);
}
async function api(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({detail: response.statusText}));
  if (!response.ok) {
    const message = Array.isArray(data.detail) ? data.detail.map(x => `${x.loc.slice(1).join('.')}: ${x.msg}`).join('\n') : data.detail;
    throw Error(message || 'Request failed. Try again.');
  }
  return data;
}
async function work(message, action) {
  if (busy) return;
  busy = true;
  document.querySelectorAll('button, #source, #playlist').forEach(el => { el.disabled = true; });
  report(message + '…');
  try { await action(); }
  catch (error) { report(error.message, true); }
  finally {
    busy = false;
    document.querySelectorAll('button, #source, #playlist').forEach(el => { el.disabled = false; });
  }
}
function sourceChanged() {
  source = byId('source').value;
  originalTracks = [];
  const name = sourceNames[source];
  const history = source === 'pandora';
  byId('source-help').textContent = help[source];
  byId('connect').textContent = 'Connect ' + name;
  byId('connect').hidden = history;
  byId('finish-login').textContent = 'Finish ' + name + ' login';
  byId('finish-login').hidden = !['tidal', 'youtube_music'].includes(source);
  byId('load').textContent = history ? 'Load Pandora listens' : 'Load playlists';
  byId('playlist-picker').hidden = history;
  byId('playlist').replaceChildren(new Option('Load playlists to choose one', ''));
  byId('playlist-name').value = name + (history ? ' listens' : ' playlist');
  byId('playlist-url').value = '';
  byId('playlist-input').value = '';
  byId('tracks').value = '';
  byId('track-summary').textContent = 'No tracks loaded.';
  byId('login-instructions').hidden = true;
  byId('listen-confirmation').hidden = history;
  byId('confirmed').checked = false;
  byId('listened-at').value = '';
  byId('recommendations').textContent = history ? 'Post existing recommendations' : 'Submit listens and post recommendations';
  byId('recommendations-help').textContent = history
    ? 'These plays are already in ListenBrainz. This action posts your available recommendations without submitting the listens again.'
    : 'Submit confirmed previous listens, then post your available ListenBrainz recommendation playlists. Recommendations may take time to appear.';
  report(help[source]);
}
function displayList(data) {
  originalTracks = data.tracks;
  byId('playlist-name').value = data.name;
  byId('playlist-url').value = data.url;
  byId('tracks').value = data.tracks.map(trackLine).join('\n');
  byId('confirmed').checked = false;
  const summary = `${data.tracks.length} tracks loaded` + (data.skipped ? ` · ${data.skipped} unavailable entries skipped` : '') + '.';
  byId('track-summary').textContent = summary;
  report(data.tracks.length ? summary + (data.note ? '\n' + data.note : '') + (data.truncated ? '\nShowing the configured history window.' : '')
    : source === 'pandora' ? 'No Pandora listens found in the scanned ListenBrainz history. Set up scrobbling and play some music first.' : 'This playlist has no available music tracks.');
}
function trackLine(track) { return `${track.artist} — ${track.title}${track.album ? ' — ' + track.album : ''}`; }
function tracksForRequest() {
  const lines = byId('tracks').value.split('\n').map(x => x.trim()).filter(Boolean);
  if (!lines.length) throw Error('Load a playlist or enter at least one track first.');
  const originals = new Map();
  originalTracks.forEach(track => {
    const line = trackLine(track);
    if (!originals.has(line)) originals.set(line, []);
    originals.get(line).push(track);
  });
  return lines.map((line, index) => {
    const original = originals.get(line)?.shift();
    if (original) return {...original};
    const [artist, title, ...albumParts] = line.split(' — ');
    if (!artist?.trim() || !title?.trim()) throw Error(`Line ${index + 1}: use Artist — Track — Album (album is optional).`);
    return {artist: artist.trim(), title: title.trim(), album: albumParts.join(' — ').trim() || null};
  });
}
function requestData() {
  return {source, playlist_name: byId('playlist-name').value, playlist_url: byId('playlist-url').value,
    discord_format: byId('format').value, tracks: tracksForRequest(), confirmed_listens: byId('confirmed').checked,
    listened_at: byId('listened-at').value ? Math.floor(new Date(byId('listened-at').value).getTime() / 1000) : null};
}
function parsePlaylistInput(value) {
  value = value.trim();
  if (source === 'spotify' && value.startsWith('spotify:playlist:')) return value.slice(17);
  if (value.startsWith('http')) {
    const url = new URL(value);
    const domains = {tidal: ['tidal.com', 'www.tidal.com', 'listen.tidal.com'], spotify: ['open.spotify.com'], youtube_music: ['music.youtube.com', 'www.youtube.com', 'youtube.com']};
    if (!domains[source].includes(url.hostname)) throw Error('This link does not match the selected music source.');
    if (source === 'youtube_music') return url.searchParams.get('list') || '';
    return url.pathname.match(/\/playlist\/([A-Za-z0-9_-]+)/)?.[1] || '';
  }
  return value;
}
async function loadPlaylist(id) {
  if (!/^[A-Za-z0-9_-]{1,200}$/.test(id)) throw Error('Enter a valid playlist link or ID.');
  displayList(await api(`/api/${source}/playlists/${encodeURIComponent(id)}`));
}
byId('source').addEventListener('change', sourceChanged);
byId('connect').addEventListener('click', () => work('Starting sign-in', async () => {
  const data = await api(`/api/${source}/login`, {method: 'POST'});
  byId('login-link').href = data.authorization_url || data.verification_url;
  byId('login-text').textContent = data.user_code ? `Enter code ${data.user_code} on the sign-in page, then click Finish YouTube Music login.`
    : source === 'spotify' ? 'Open the sign-in page. Once connected, return here and load your playlists.' : 'Sign in to TIDAL, then return here and click Finish TIDAL login.';
  byId('login-instructions').hidden = false;
  report('Sign-in is ready. Open the link above to continue.');
}));
byId('finish-login').addEventListener('click', () => work('Checking sign-in', async () => {
  const data = await api(`/api/${source}/login/complete`, {method: 'POST'});
  report(data.complete ? `${sourceNames[source]} connected. Load your playlists to continue.` : data.reason || 'Finish authorization on the sign-in page, then check again.');
  if (data.complete) byId('login-instructions').hidden = true;
}));
byId('load').addEventListener('click', () => work('Loading ' + sourceNames[source], async () => {
  if (source === 'pandora') return displayList(await api('/api/pandora/history'));
  const playlists = await api(`/api/${source}/playlists`);
  byId('playlist').replaceChildren(new Option(playlists.length ? 'Select a playlist' : 'No playlists found', ''));
  playlists.forEach(item => byId('playlist').add(new Option(item.name, item.id)));
  report(playlists.length ? `${playlists.length} playlists loaded. Choose one above.` : 'No playlists found. You can try a playlist link instead.');
}));
byId('playlist').addEventListener('change', () => { if (byId('playlist').value) work('Loading tracks', () => loadPlaylist(byId('playlist').value)); });
byId('load-by-id').addEventListener('click', () => work('Loading tracks', () => loadPlaylist(parsePlaylistInput(byId('playlist-input').value))));
byId('send').addEventListener('click', () => work('Posting requests to Discord', async () => {
  const result = await api('/api/dispatch', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(requestData())});
  report(`Posted ${result.discord_messages} Discord messages, ending with !auto on.`);
}));
byId('recommendations').addEventListener('click', () => work('Checking ListenBrainz recommendations', async () => {
  const data = requestData();
  if (source !== 'pandora' && !data.confirmed_listens) throw Error('Confirm that you actually listened to these tracks first.');
  if (source !== 'pandora' && !data.listened_at) throw Error('Choose when you listened first.');
  const result = await api('/api/recommendations', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)});
  report(`${result.listenbrainz_submitted} listens submitted. ` + (result.posted ? `${result.count} recommendations posted, followed by !auto on.` : result.reason));
}));
sourceChanged();
api('/api/status').then(data => {
  byId('configuration').textContent = `Version ${data.version} · Discord ${data.discord ? 'configured' : 'not configured'} · ListenBrainz ${data.listenbrainz ? 'configured' : 'not configured'}`;
}).catch(error => { byId('configuration').textContent = error.message; });
