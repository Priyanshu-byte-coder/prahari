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
  collapseAll();
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
      <button class="expand-btn" data-role="expand" title="Full screen + camera data">⛶</button>
      <video muted playsinline data-role="video"></video>
      <canvas class="box-overlay" data-role="boxes"></canvas>
      <div class="overlay" data-role="overlay">
        <div>${cam.reachable ? 'Press “Start wall”' : 'Unavailable'}</div>
        ${cam.reachable ? '' : `<div class="why">${cam.status}: ${cam.status_detail || ''}</div>`}
      </div>
      <div class="label">
        <span class="id">${cam.id}</span>
        <span class="loc">${cam.location || cam.name}</span>
        <span class="meta" data-role="meta">${cam.codec || ''} ${res}</span>
      </div>
      <div class="panel" data-role="panel"></div>`;
    tile.addEventListener('click', () => selectCamera(cam.id));
    tile.querySelector('[data-role=expand]').addEventListener('click', (e) => {
      e.stopPropagation();
      toggleExpand(cam.id);
    });
    wall.appendChild(tile);
  });
}

/* ------------------------------------------------------ live box overlay */

// One shared poll loop rather than a timer per tile -- a wall of 24 cameras
// each polling independently would hammer the API for no benefit.
function startOverlayLoop() {
  clearInterval(state.overlayTimer);
  state.overlayTimer = setInterval(updateOverlays, 800);
}

function updateOverlays() {
  const liveIds = [...state.players.entries()]
    .filter(([, p]) => p.hls && p.attempt === 0)
    .map(([id]) => id);
  liveIds.forEach(drawOverlay);
}

async function drawOverlay(id) {
  const tile = document.querySelector(`.tile[data-id="${id}"]`);
  const canvas = tile && tile.querySelector('[data-role=boxes]');
  if (!tile || !canvas) return;
  const cam = state.cameras.find((c) => c.id === id);
  if (!cam || !cam.width || !cam.height) return;

  let det;
  try {
    const res = await fetch(`/api/detections/${id}?limit=60`);
    det = await res.json();
  } catch (_) { return; }

  const ctx = canvas.getContext('2d');
  const dispW = canvas.clientWidth, dispH = canvas.clientHeight;
  canvas.width = dispW;
  canvas.height = dispH;
  ctx.clearRect(0, 0, dispW, dispH);
  if (!det.available) return;

  // Keep only the most recent sighting per track id.
  const latest = new Map();
  det.tracks.forEach((t) => latest.set(t.track_id, t));

  // Grid tiles use object-fit: cover, the expanded view uses contain -- the
  // scale math differs, so mirror whichever the tile is currently rendering.
  const expanded = tile.classList.contains('expanded');
  const scale = expanded
    ? Math.min(dispW / cam.width, dispH / cam.height)
    : Math.max(dispW / cam.width, dispH / cam.height);
  const drawW = cam.width * scale, drawH = cam.height * scale;
  const offX = (dispW - drawW) / 2, offY = (dispH - drawH) / 2;

  ctx.lineWidth = 2;
  ctx.font = '11px ui-monospace, monospace';
  ctx.textBaseline = 'alphabetic';
  latest.forEach((t) => {
    const [x1, y1, x2, y2] = t.bbox;
    const sx = offX + x1 * scale, sy = offY + y1 * scale;
    const sw = (x2 - x1) * scale, sh = (y2 - y1) * scale;
    const color = t.plate ? '#eab308' : '#22c55e';

    ctx.strokeStyle = color;
    ctx.strokeRect(sx, sy, sw, sh);

    const label = t.plate ? t.plate : `${t.class} #${t.track_id}`;
    const tw = ctx.measureText(label).width + 6;
    const ly = Math.max(12, sy - 3);
    ctx.fillStyle = color;
    ctx.fillRect(sx, ly - 11, tw, 14);
    ctx.fillStyle = '#0a0e14';
    ctx.fillText(label, sx + 3, ly);
  });
}

/* ------------------------------------------------------------ fullscreen */

function toggleExpand(id) {
  const tile = document.querySelector(`.tile[data-id="${id}"]`);
  if (!tile) return;
  if (tile.classList.contains('expanded')) collapseTile(id);
  else expandTile(id);
}

function expandTile(id) {
  collapseAll();
  const tile = document.querySelector(`.tile[data-id="${id}"]`);
  if (!tile) return;

  const backdrop = document.createElement('div');
  backdrop.className = 'tile-backdrop';
  backdrop.addEventListener('click', () => collapseTile(id));
  document.body.appendChild(backdrop);

  tile.classList.add('expanded');
  const btn = tile.querySelector('[data-role=expand]');
  if (btn) btn.textContent = '✕';

  refreshPanel(id);
  tile._panelTimer = setInterval(() => refreshPanel(id), 2000);
  document.addEventListener('keydown', escHandler);
}

function collapseTile(id) {
  const tile = document.querySelector(`.tile[data-id="${id}"]`);
  if (!tile) return;
  tile.classList.remove('expanded');
  const btn = tile.querySelector('[data-role=expand]');
  if (btn) btn.textContent = '⛶';
  clearInterval(tile._panelTimer);
  document.querySelectorAll('.tile-backdrop').forEach((b) => b.remove());
  document.removeEventListener('keydown', escHandler);
}

function collapseAll() {
  document.querySelectorAll('.tile.expanded').forEach((t) => collapseTile(t.dataset.id));
}

function escHandler(e) {
  if (e.key === 'Escape') collapseAll();
}

async function refreshPanel(id) {
  const tile = document.querySelector(`.tile[data-id="${id}"]`);
  if (!tile || !tile.classList.contains('expanded')) return;
  const panel = tile.querySelector('[data-role=panel]');
  const cam = state.cameras.find((c) => c.id === id);
  if (!cam || !panel) return;

  let det = { available: false, by_class: {}, unique_tracks: 0, tracks: [] };
  try {
    const res = await fetch(`/api/detections/${id}`);
    det = await res.json();
  } catch (_) { /* worker may not be running for this camera */ }

  const res_ = cam.width ? `${cam.width}x${cam.height}` : '—';
  const mismatch = cam.fps_disagreement
    ? ` <span style="color:var(--warn)">(catalogue: ${cam.catalogue_fps})</span>` : '';

  const classRows = Object.entries(det.by_class)
    .sort((a, b) => b[1] - a[1])
    .map(([k, v]) => `<div class="panel-row"><span>${k}</span><b>${v}</b></div>`)
    .join('') || '<div class="panel-empty">No detections yet.</div>';

  const recentRows = [...det.tracks].reverse().slice(0, 15).map((t) => `
    <div class="track-row">
      <span class="tid">#${t.track_id}</span>
      <span>${t.class}</span>
      <span class="conf">${Math.round(t.conf * 100)}%</span>
      <span class="pts">${t.pts_seconds.toFixed(1)}s</span>
    </div>`).join('') || '<div class="panel-empty">Run the ANPR worker against this camera to see live tracks:<br><code>python -m services.worker.run_worker --camera ' + id + '</code></div>';

  panel.innerHTML = `
    <div class="panel-head">
      <h3>Camera ${cam.id}</h3>
      <button class="panel-close" data-role="close" title="Close">✕</button>
    </div>
    <div class="panel-section">
      <h4>Metadata</h4>
      <div class="panel-row"><span>Name</span><b>${cam.name}</b></div>
      <div class="panel-row"><span>Location</span><b>${cam.location || '—'}</b></div>
      <div class="panel-row"><span>Department</span><b>${cam.department || '—'}</b></div>
      <div class="panel-row"><span>Status</span><b>${cam.status}</b></div>
      <div class="panel-row"><span>Transport</span><b>${cam.transport || '—'}</b></div>
      <div class="panel-row"><span>Codec</span><b>${cam.codec || '—'}</b></div>
      <div class="panel-row"><span>Resolution</span><b>${res_}</b></div>
      <div class="panel-row"><span>FPS (measured)</span><b>${cam.fps ?? '—'}${mismatch}</b></div>
      <div class="panel-row"><span>Geo precision</span><b>${cam.geo_precision || '—'}</b></div>
      <div class="panel-row"><span>Lat / Lon</span><b>${cam.lat != null ? cam.lat.toFixed(4) : '—'}, ${cam.lon != null ? cam.lon.toFixed(4) : '—'}</b></div>
      ${cam.status_detail ? `<div class="panel-row"><span>Detail</span><b style="color:var(--muted);font-weight:400">${cam.status_detail}</b></div>` : ''}
    </div>
    <div class="panel-section">
      <h4>Vehicle counts ${det.available ? `· ${det.unique_tracks} unique tracks` : ''}</h4>
      ${classRows}
    </div>
    <div class="panel-section panel-tracks">
      <h4>Recent tracks (stream PTS)</h4>
      ${recentRows}
    </div>`;

  panel.querySelector('[data-role=close]').addEventListener('click', () => collapseTile(id));
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
  const tile = document.querySelector(`.tile[data-id="${id}"]`);
  const canvas = tile && tile.querySelector('[data-role=boxes]');
  if (canvas) canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height);
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
startOverlayLoop();

/* ------------------------------------------------------- route tracing (G3)
 *
 * A judge supplies a registration number and expects to see where the vehicle
 * went. The API does the reasoning; this draws it: numbered pins in travel
 * order, a polyline between them, and a legible reason next to any leg the
 * engine judged physically impossible. Showing the rejected leg matters as
 * much as showing the route -- it is the difference between a system that
 * found a car and a system that can explain itself.
 */

state.routeLayer = null;
state.routeMarkers = [];
state.lastRouteQuery = null;

function clearRoute() {
  if (state.routeLayer) { state.map.removeLayer(state.routeLayer); state.routeLayer = null; }
  state.routeMarkers.forEach((m) => state.map.removeLayer(m));
  state.routeMarkers = [];
  $('route-result').hidden = true;
  $('route-result').innerHTML = '';
  $('route-status').textContent = '';
  $('route-status').className = 'route-status';
  state.lastRouteQuery = null;
}

function routeQueryString() {
  const plate = $('route-plate').value.trim();
  const params = new URLSearchParams({
    plate,
    max_distance: $('route-fuzz').value,
    drop_implausible: $('route-clean').checked ? 'true' : 'false',
  });
  return { plate, qs: params.toString() };
}

async function traceRoute() {
  const { plate, qs } = routeQueryString();
  if (!plate) {
    $('route-status').textContent = 'enter a registration number';
    $('route-status').className = 'route-status err';
    return;
  }

  clearRoute();
  state.lastRouteQuery = qs;
  $('route-status').textContent = 'searching…';

  let data;
  try {
    const res = await fetch(`/api/route?${qs}`);
    data = await res.json();
  } catch (err) {
    $('route-status').textContent = 'route lookup failed';
    $('route-status').className = 'route-status err';
    return;
  }

  const s = data.summary;
  if (!data.sightings.length) {
    $('route-status').textContent = `no sightings of ${plate}`;
    $('route-status').className = 'route-status err';
    return;
  }

  $('route-status').textContent =
    `${s.sightings} sightings across ${s.cameras} cameras`;
  $('route-status').className = 'route-status ok';

  drawRouteOnMap(data);
  renderRoutePanel(data, plate);
}

function drawRouteOnMap(data) {
  const points = data.sightings
    .filter((s) => s.lat != null && s.lon != null)
    .map((s) => [s.lat, s.lon]);

  if (points.length > 1) {
    state.routeLayer = L.polyline(points, {
      color: '#ff6b00', weight: 3, opacity: 0.85, dashArray: '6 4',
    }).addTo(state.map);
  }

  data.sightings.forEach((s, i) => {
    if (s.lat == null || s.lon == null) return;
    const marker = L.marker([s.lat, s.lon], {
      icon: L.divIcon({
        className: '',
        html: `<div class="route-marker">${i + 1}</div>`,
        iconSize: [22, 22],
      }),
      zIndexOffset: 1000,
    }).addTo(state.map);
    marker.bindPopup(
      `<b>${i + 1}. ${s.location || 'camera ' + s.camera_id}</b>
       <table>
         <tr><td>Camera</td><td>${s.camera_id}</td></tr>
         <tr><td>Seen</td><td>${s.first_seen_iso || '—'}</td></tr>
         <tr><td>Dwell</td><td>${s.dwell_seconds}s</td></tr>
         <tr><td>Plate read</td><td>${s.plate_read}</td></tr>
         <tr><td>Edit distance</td><td>${s.plate_distance}</td></tr>
         <tr><td>Class</td><td>${s.vehicle_class}</td></tr>
       </table>`);
    state.routeMarkers.push(marker);
  });

  if (points.length) {
    state.map.fitBounds(points.length > 1 ? points : [points[0]],
      { padding: [60, 60], maxZoom: 14 });
  }
}

function renderRoutePanel(data, plate) {
  const s = data.summary;
  const box = $('route-result');
  box.hidden = false;

  const rows = data.sightings.map((sight, i) => {
    const hop = data.hops[i];  // leg leaving this sighting
    const fuzzy = sight.plate_distance > 0;
    const legHtml = hop ? `
      <div class="leg ${hop.plausible ? '' : 'bad'}">
        ${hop.plausible ? '↓' : '⚠'}
        ${hop.distance_km != null ? `${hop.distance_km} km` : 'distance unknown'} ·
        ${Math.round(hop.gap_seconds)}s
        ${hop.implied_speed_kmh != null ? `· ${hop.implied_speed_kmh} km/h` : ''}
        ${hop.note ? `<br>${hop.note}` : ''}
      </div>` : '';

    return `
      <div class="hop-row">
        <div class="hop-rail">
          <div class="hop-dot">${i + 1}</div>
          ${hop ? `<div class="hop-line ${hop.plausible ? '' : 'bad'}"></div>` : ''}
        </div>
        <div class="hop-body">
          <div class="where">${sight.location || 'Camera ' + sight.camera_id}
            <span class="when">· cam ${sight.camera_id}</span></div>
          <div class="when">${sight.first_seen_iso || 'timing not anchored'}
            · dwell ${sight.dwell_seconds}s</div>
          <div class="plate ${fuzzy ? 'fuzzy' : ''}">${sight.plate_read}
            ${fuzzy ? `(fuzzy, distance ${sight.plate_distance})` : '(exact)'}</div>
          ${legHtml}
        </div>
      </div>`;
  }).join('');

  box.innerHTML = `
    <h3>Movement of ${plate}</h3>
    <div class="route-summary">
      <span>Sightings <b>${s.sightings}</b></span>
      <span>Cameras <b>${s.cameras}</b></span>
      <span>Exact <b>${s.exact_matches}</b></span>
      <span>Fuzzy <b>${s.fuzzy_matches}</b></span>
      <span>Distance <b>${s.route_distance_km} km</b></span>
      <span>Span <b>${Math.round(s.time_span_seconds)}s</b></span>
      ${s.implausible_hops ? `<span style="color:var(--err)">Rejected legs <b>${s.implausible_hops}</b></span>` : ''}
    </div>
    <div class="route-hops">${rows}</div>`;
}

$('btn-route').addEventListener('click', traceRoute);
$('route-plate').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') traceRoute();
});
$('btn-route-clear').addEventListener('click', clearRoute);
$('btn-route-csv').addEventListener('click', () => {
  const { plate, qs } = routeQueryString();
  if (!plate) return;
  // The CSV endpoint is the artifact the organisers asked for: detected
  // vehicles with corresponding timestamps.
  window.open(`/api/route/export.csv?${qs}`, '_blank');
});
