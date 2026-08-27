/* Prahari operator console.
 *
 * The integration rules from the Sentinel guide are implemented here, not just
 * documented: reconnect with exponential backoff, decoder warnings are never
 * fatal, only the cameras on the wall hold an open stream (each client gets its
 * own copy of the feed upstream), and the frame rate shown is MEASURED rather
 * than taken from the catalogue -- which we have proven disagrees with delivery.
 */

const state = {
  cameras: [],
  markers: new Map(),
  players: new Map(),   // cameraId -> { hls, video, timer, attempt }
  selected: null,
  map: null,
};

const $ = (id) => document.getElementById(id);

/* ------------------------------------------------------------------ data */

async function loadCameras() {
  const res = await fetch('/api/cameras');
  const data = await res.json();
  state.cameras = data.cameras;
  renderStats(data.summary);
  renderDepartments(data.summary.by_department);
  renderMarkers();
  renderWall();
}

function renderStats(s) {
  $('stat-total').textContent = s.total;
  $('stat-online').textContent = s.online;
  $('stat-down').textContent = s.total - s.online;
  $('stat-fps').textContent = s.fps_mismatch;
}

function renderDepartments(byDept) {
  const sel = $('f-dept');
  const current = sel.value;
  sel.innerHTML = '<option value="all">All</option>';
  Object.entries(byDept)
    .sort((a, b) => b[1] - a[1])
    .forEach(([dept, n]) => {
      const opt = document.createElement('option');
      opt.value = dept;
      opt.textContent = `${dept} (${n})`;
      sel.appendChild(opt);
    });
  sel.value = current || 'all';
}

function filtered() {
  const status = $('f-status').value;
  const dept = $('f-dept').value;
  return state.cameras.filter((c) => {
    if (dept !== 'all' && c.department !== dept) return false;
    if (status === 'reachable') return c.reachable;
    if (status === 'degraded') return !c.reachable;
    return true;
  });
}

/* ------------------------------------------------------------------- map */

function initMap() {
  state.map = L.map('map', { zoomControl: true }).setView([22.6, 71.6], 7);

  // Standard OSM tiles need no API key; the dark treatment is a CSS filter on
  // the tile pane, so the console still works on an air-gapped venue network
  // with a local tile cache.
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap contributors',
    maxZoom: 19,
  }).addTo(state.map);

  const legend = L.control({ position: 'bottomright' });
  legend.onAdd = () => {
    const div = L.DomUtil.create('div', 'legend');
    div.innerHTML = `
      <b>Camera status</b>
      <div class="row"><span class="dot" style="background:#22c55e"></span>Online</div>
      <div class="row"><span class="dot" style="background:#eab308"></span>Auth required (401)</div>
      <div class="row"><span class="dot" style="background:#ef4444"></span>Upstream error (5XX)</div>
      <div class="row"><span class="dot" style="background:#a855f7"></span>Timeout</div>
      <div class="row"><span class="dot" style="background:#64748b"></span>Unsurveyed</div>`;
    return div;
  };
  legend.addTo(state.map);
}

function renderMarkers() {
  state.markers.forEach((m) => state.map.removeLayer(m));
  state.markers.clear();

  const bounds = [];
  state.cameras.forEach((cam) => {
    if (cam.lat == null || cam.lon == null) return;
    const icon = L.divIcon({
      className: '',
      html: `<div class="cam-marker ${cam.status}"></div>`,
      iconSize: [14, 14],
    });
    const marker = L.marker([cam.lat, cam.lon], { icon, draggable: true })
      .addTo(state.map)
      .bindPopup(popupHtml(cam));

    // Drag-to-correct: most coordinates start as district-centroid guesses, and
    // route plausibility filtering depends on real inter-camera distance.
    marker.on('dragend', async (ev) => {
      const { lat, lng } = ev.target.getLatLng();
      await fetch(`/api/cameras/${cam.id}/geo`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lat, lon: lng }),
      });
      cam.lat = lat; cam.lon = lng; cam.geo_precision = 'operator_verified';
      marker.setPopupContent(popupHtml(cam));
    });

    marker.on('click', () => selectCamera(cam.id));
    state.markers.set(cam.id, marker);
    bounds.push([cam.lat, cam.lon]);
  });

  if (bounds.length) state.map.fitBounds(bounds, { padding: [40, 40] });
}

function popupHtml(cam) {
  const res = cam.width ? `${cam.width}x${cam.height}` : '—';
  const mismatch = cam.fps_disagreement
    ? ` <span style="color:#eab308">(catalogue says ${cam.catalogue_fps})</span>`
    : '';
  return `
    <b>${cam.id} · ${cam.location || cam.name}</b>
    <table>
      <tr><td>Department</td><td>${cam.department || '—'}</td></tr>
      <tr><td>Status</td><td>${cam.status}</td></tr>
      <tr><td>Transport</td><td>${cam.transport || '—'}</td></tr>
      <tr><td>Codec</td><td>${cam.codec || '—'}</td></tr>
      <tr><td>Resolution</td><td>${res}</td></tr>
      <tr><td>FPS</td><td>${cam.fps ?? '—'}${mismatch}</td></tr>
      <tr><td>Geo</td><td>${cam.geo_precision || '—'}</td></tr>
    </table>
    ${cam.status_detail ? `<div style="margin-top:6px;color:#94a3b8;font-size:10px">${cam.status_detail}</div>` : ''}`;
}

function selectCamera(id) {
  state.selected = id;
  document.querySelectorAll('.tile').forEach((t) =>
    t.classList.toggle('selected', t.dataset.id === id));
  const tile = document.querySelector(`.tile[data-id="${id}"]`);
  if (tile) tile.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

/* ------------------------------------------------------------ video wall */

function renderWall() {
  stopAll();
  const wall = $('wall');
  wall.innerHTML = '';
  const limit = parseInt($('f-count').value, 10);
  const cams = filtered().slice(0, limit);

  cams.forEach((cam) => {
    const tile = document.createElement('div');
    tile.className = 'tile';
    tile.dataset.id = cam.id;
    const res = cam.width ? `${cam.width}x${cam.height}` : '';
    tile.innerHTML = `
      <span class="badge" data-role="badge">idle</span>
      <video muted playsinline data-role="video"></video>
      <div class="overlay" data-role="overlay">
        <div>${cam.reachable ? 'Press “Start wall”' : 'Unavailable'}</div>
        ${cam.reachable ? '' : `<div class="why">${cam.status}: ${cam.status_detail || ''}</div>`}
      </div>
      <div class="label">
        <span class="id">${cam.id}</span>
        <span class="loc">${cam.location || cam.name}</span>
        <span class="meta" data-role="meta">${cam.codec || ''} ${res}</span>
      </div>`;
    tile.addEventListener('click', () => selectCamera(cam.id));
    wall.appendChild(tile);
  });
}

function tileParts(id) {
  const tile = document.querySelector(`.tile[data-id="${id}"]`);
  if (!tile) return null;
  return {
    tile,
    video: tile.querySelector('[data-role=video]'),
    badge: tile.querySelector('[data-role=badge]'),
    overlay: tile.querySelector('[data-role=overlay]'),
    meta: tile.querySelector('[data-role=meta]'),
  };
}

function setBadge(id, text, cls) {
  const p = tileParts(id);
  if (!p) return;
  p.badge.className = `badge ${cls}`;
  p.badge.innerHTML = cls === 'live'
    ? `<span class="pulse blink"></span> ${text}` : text;
}

function startCamera(cam) {
  const parts = tileParts(cam.id);
  if (!parts || !cam.hls_url || !cam.reachable) return;

  const entry = state.players.get(cam.id) || { attempt: 0 };
  state.players.set(cam.id, entry);
  entry.video = parts.video;
  setBadge(cam.id, 'connecting', 'connecting');

  const attach = () => {
    if (entry.hls) { entry.hls.destroy(); entry.hls = null; }

    if (!Hls.isSupported()) {
      parts.video.src = cam.hls_url;      // Safari plays HLS natively
      parts.video.play().catch(() => {});
      return;
    }

    const hls = new Hls({
      lowLatencyMode: false,  // gateway serves plain HLS; see gateway.py
      backBufferLength: 10,
      manifestLoadingTimeOut: 20000,
      fragLoadingTimeOut: 30000,
      // The upstream restarts feeds; retries are handled by our own backoff
      // below so that a dead camera does not spin in a tight loop.
      manifestLoadingMaxRetry: 1,
      levelLoadingMaxRetry: 1,
      fragLoadingMaxRetry: 2,
    });
    entry.hls = hls;

    hls.on(Hls.Events.MANIFEST_PARSED, () => {
      parts.video.play().catch(() => {});
      parts.overlay.style.display = 'none';
      setBadge(cam.id, 'live', 'live');
      entry.attempt = 0;                  // recovered: reset the backoff
      updatePlayingCount();
    });

    hls.on(Hls.Events.ERROR, (_evt, data) => {
      if (!data.fatal) {
        // Decoder complaints while joining mid-stream are expected on this
        // grid and self-correct once the first keyframe lands. Never fatal.
        console.debug(`[cam ${cam.id}] non-fatal ${data.details}`);
        return;
      }
      if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
        console.warn(`[cam ${cam.id}] media error, recovering`);
        hls.recoverMediaError();
        return;
      }
      scheduleReconnect(cam);
    });

    hls.loadSource(cam.hls_url);
    hls.attachMedia(parts.video);
  };

  attach();
  measureFps(cam.id);
}

function scheduleReconnect(cam) {
  const entry = state.players.get(cam.id);
  if (!entry) return;
  if (entry.hls) { entry.hls.destroy(); entry.hls = null; }

  entry.attempt = (entry.attempt || 0) + 1;
  // Exponential backoff starting near 2s, capped at 30s, with jitter so a wall
  // of tiles does not stampede the gateway in lockstep.
  const base = Math.min(30000, 2000 * 2 ** (entry.attempt - 1));
  const delay = Math.round(base * (0.75 + Math.random() * 0.5));

  setBadge(cam.id, `retry ${Math.round(delay / 1000)}s`, 'error');
  const parts = tileParts(cam.id);
  if (parts) {
    parts.overlay.style.display = 'flex';
    parts.overlay.innerHTML =
      `<div>Reconnecting…</div><div class="why">attempt ${entry.attempt}</div>`;
  }
  updatePlayingCount();

  clearTimeout(entry.timer);
  entry.timer = setTimeout(() => startCamera(cam), delay);
}

/* Measure delivered frame rate from the decoder, because the catalogue's
 * number is demonstrably wrong on this grid. */
function measureFps(id) {
  const entry = state.players.get(id);
  if (!entry) return;
  let lastFrames = 0;
  let lastTime = performance.now();

  clearInterval(entry.fpsTimer);
  entry.fpsTimer = setInterval(() => {
    const parts = tileParts(id);
    if (!parts || !entry.video) return;
    const q = entry.video.getVideoPlaybackQuality
      ? entry.video.getVideoPlaybackQuality()
      : null;
    const frames = q ? q.totalVideoFrames : entry.video.webkitDecodedFrameCount;
    if (frames == null) return;
    const now = performance.now();
    const dt = (now - lastTime) / 1000;
    if (dt > 0 && lastFrames) {
      const fps = (frames - lastFrames) / dt;
      const cam = state.cameras.find((c) => c.id === id);
      const res = cam && cam.width ? `${cam.width}x${cam.height}` : '';
      parts.meta.textContent =
        `${cam?.codec || ''} ${res} · ${fps.toFixed(1)}fps measured`;
    }
    lastFrames = frames;
    lastTime = now;
  }, 3000);
}

function stopCamera(id) {
  const entry = state.players.get(id);
  if (!entry) return;
  clearTimeout(entry.timer);
  clearInterval(entry.fpsTimer);
  if (entry.hls) entry.hls.destroy();
  if (entry.video) { entry.video.removeAttribute('src'); entry.video.load(); }
  state.players.delete(id);
  setBadge(id, 'idle', '');
  const parts = tileParts(id);
  if (parts) parts.overlay.style.display = 'flex';
  updatePlayingCount();
}

function stopAll() {
  [...state.players.keys()].forEach(stopCamera);
}

function updatePlayingCount() {
  const live = [...state.players.values()].filter((p) => p.hls && p.attempt === 0).length;
  $('stat-playing').textContent = live;
}

/* ------------------------------------------------------------------ wire */

function startWall() {
  const limit = parseInt($('f-count').value, 10);
  // Only cameras on the wall hold a connection: each client gets its own copy
  // of the stream upstream, so idle tiles must not stay attached.
  filtered().filter((c) => c.reachable).slice(0, limit).forEach((cam, i) => {
    // Stagger connects so the gateway is not hit by N simultaneous joins.
    setTimeout(() => startCamera(cam), i * 400);
  });
}

$('btn-play').addEventListener('click', startWall);
$('btn-stop').addEventListener('click', stopAll);
['f-status', 'f-dept', 'f-count'].forEach((id) =>
  $(id).addEventListener('change', renderWall));

$('btn-sync').addEventListener('click', async () => {
  const btn = $('btn-sync');
  btn.disabled = true;
  btn.textContent = 'Syncing…';
  try {
    const res = await fetch('/api/registry/sync', { method: 'POST' });
    const d = await res.json();
    btn.textContent = d.added?.length
      ? `+${d.added.length} new` : `${d.total} in sync`;
    await loadCameras();
  } catch (err) {
    btn.textContent = 'Sync failed';
  }
  setTimeout(() => { btn.disabled = false; btn.textContent = 'Sync catalogue'; }, 2500);
});

initMap();
loadCameras();
