/* Prahari console — one shell, six views, live data.
 *
 * Data comes from two places and nowhere else:
 *   /api/cameras, /api/wall, /tile/<id>.jpg   this server (seed + geo + real frames)
 *   /api/v1/<path>                            the core API, proxied with the
 *                                             console's own account so the
 *                                             operator never meets a login form
 *
 * Nothing here invents a number. When a field is missing the UI says so rather
 * than filling the gap -- a wrong plate shown to an officer is worse than no
 * plate, and the same rule applies to a camera's health and a hop's speed.
 */
'use strict';

const S = {
  view: 'map',
  cameras: [],
  wall: {},
  wallRunning: 0,
  sel: null,
  q: '',
  district: 'all',
  status: 'all',
  layers: { wedges: true, labels: true, heat: false },
  basemap: 'dark',
  fitPending: false,
  grid: null,
  cols: 3,
  focus: true,
  trace: { plate: '', data: null, sel: null, loading: false, error: null, probable: true },
  alerts: { rows: null, sel: null, severity: 'all', state: 'all', error: null },
  watch: { rows: null, sel: null, severity: 'all', error: null },
  admin: { tab: 'health', audit: null, error: null, verifying: false, verified: null },
};

/* ── plumbing ───────────────────────────────────────────────────── */

const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

async function getJSON(url) {
  const r = await fetch(url);
  const body = await r.json().catch(() => ({ detail: 'unreadable response' }));
  if (!r.ok) throw new Error(body.detail ? JSON.stringify(body.detail) : `HTTP ${r.status}`);
  return body;
}
async function postJSON(url, body) {
  const r = await fetch(url, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
  const out = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(out.detail ? JSON.stringify(out.detail) : `HTTP ${r.status}`);
  // The wall answers 200 with {ok:false,error} when it cannot start at all.
  // Treating that as success is how thirty tiles sat on "idle" saying nothing.
  if (out.ok === false) throw new Error(out.error || 'refused');
  return out;
}

function toast(msg, tone) {
  const el = document.createElement('div');
  el.className = 'toast rise';
  el.innerHTML = `<span class="sq" style="background:${tone || 'var(--jade)'}"></span><span>${esc(msg)}</span>`;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 3200);
}

/* ── camera model ───────────────────────────────────────────────── */

// A camera is DOWN when the grid will not serve it at all. Cameras 17, 18 and
// 22 have been down at the grid for days -- that is the data, not a probe bug.
// A live RTSP attempt is ground truth and overrides the catalogue's stale
// HLS-only probe: cameras 17/18/22 read DOWN on that probe (HLS is gated
// behind a grid session we don't hold) but open fine over RTSP, which needs
// no session at all. So an actual wall attempt always wins; the static probe
// is only a best guess for a camera the wall has never tried to pull.
function health(cam) {
  const w = S.wall[cam.camera_id];
  if (w && w.status && w.status !== 'idle' && w.status !== 'stopped') {
    if (w.has_frame) return w.stale ? 'DEGRADED' : 'LIVE';
    if (w.status === 'live' || w.status === 'connecting') return 'CONNECTING';
    if (w.status === 'retrying') return w.frames > 0 ? 'DEGRADED' : 'DOWN';
  }
  const probe = cam.transport_probe || {};
  const resolvable = probe.hls === true || (!!cam.transports && !!cam.transports.hls && probe.hls !== false);
  return resolvable ? 'READY' : 'DOWN';
}
const HCOL = {
  LIVE: 'var(--jade)', READY: 'var(--jade)', CONNECTING: 'var(--amber)',
  DEGRADED: 'var(--amber)', DOWN: 'var(--coral)',
};
const hcol = (h) => HCOL[h] || 'var(--faint)';

const placed = (c) => c.geo && typeof c.geo.lat === 'number' && typeof c.geo.lon === 'number';
const camName = (c) => (c.geo && c.geo.landmark) || c.location_raw || c.name || `Camera ${c.camera_id}`;

function visibleCameras() {
  const q = S.q.trim().toLowerCase();
  return S.cameras.filter((c) => {
    const h = health(c);
    if (S.status === 'LIVE' && !(h === 'LIVE' || h === 'READY')) return false;
    if (S.status === 'DEGRADED' && !(h === 'DEGRADED' || h === 'CONNECTING')) return false;
    if (S.status === 'DOWN' && h !== 'DOWN') return false;
    if (S.district !== 'all' && (c.district_code || 'UNKNOWN') !== S.district) return false;
    if (q) {
      const hay = `${camName(c)} ${c.camera_id} ${c.district_code || ''}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

function counts() {
  const c = { all: S.cameras.length, LIVE: 0, DEGRADED: 0, DOWN: 0 };
  S.cameras.forEach((cam) => {
    const h = health(cam);
    if (h === 'LIVE' || h === 'READY') c.LIVE++;
    else if (h === 'DOWN') c.DOWN++;
    else c.DEGRADED++;
  });
  return c;
}

/* ── icons ──────────────────────────────────────────────────────── */

const I = {
  search: '<circle cx="11" cy="11" r="6.5"></circle><path d="m16 16 4.5 4.5"></path>',
  tick: '<path d="m4 12.5 5 5L20 6.5"></path>',
  reset: '<path d="M20 11a8 8 0 1 0-2.3 6"></path><path d="M20 4v7h-7"></path>',
  play: '<circle cx="12" cy="12" r="9"></circle><path d="M10 8.5 16 12l-6 3.5v-7Z"></path>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2"></rect>',
  down: '<path d="M12 3v11"></path><path d="m7.5 10 4.5 4 4.5-4"></path><path d="M4 19h16"></path>',
  speed: '<path d="M12 14a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z"></path><path d="m15.5 8.5-2 2"></path><path d="M4.5 18a9 9 0 1 1 15 0"></path>',
  warn: '<path d="M12 4 2.5 20h19L12 4Z"></path><path d="M12 10v4"></path><path d="M12 17h.01"></path>',
  chain: '<path d="M10.5 13.5a4 4 0 0 0 5.7 0l2.3-2.3a4 4 0 0 0-5.7-5.7l-1.3 1.3"></path><path d="M13.5 10.5a4 4 0 0 0-5.7 0l-2.3 2.3a4 4 0 0 0 5.7 5.7l1.3-1.3"></path>',
  cam: '<rect x="3" y="6" width="18" height="13" rx="2"></rect><circle cx="12" cy="12.5" r="3.4"></circle>',
  trace: '<path d="M4 18c4.5 0 3.5-6 8-6s3.5-6 8-6"></path>',
};
const svg = (paths, size, color, w) =>
  `<svg width="${size || 14}" height="${size || 14}" viewBox="0 0 24 24" fill="none" stroke="${color || 'currentColor'}" stroke-width="${w || 1.9}" stroke-linecap="round" stroke-linejoin="round">${paths}</svg>`;

/* ── shared filter-bar bits ─────────────────────────────────────── */

function searchField(placeholder) {
  return `<div class="field ${S.q ? 'hot' : ''}" style="width:214px">
    ${svg(I.search, 13, '#68807F', 2)}
    <input class="grow" id="fq" value="${esc(S.q)}" placeholder="${esc(placeholder)}" autocomplete="off">
  </div>`;
}

function statusSeg() {
  const c = counts();
  const defs = [['all', 'All', 'var(--dim)', c.all], ['LIVE', 'Live', 'var(--jade)', c.LIVE],
    ['DEGRADED', 'Degraded', 'var(--amber)', c.DEGRADED], ['DOWN', 'Down', 'var(--coral)', c.DOWN]];
  return `<div class="seg">${defs.map(([k, label, col, n]) =>
    `<button data-status="${k}" class="${S.status === k ? 'on' : ''}">
      <span class="dot" style="width:6px;height:6px;background:${col}"></span>${label}
      <span class="n">${n}</span>
    </button>`).join('')}</div>`;
}

function districtField() {
  const set = ['all', ...Array.from(new Set(S.cameras.map((c) => c.district_code || 'UNKNOWN'))).sort()];
  return `<div class="field">
    <span class="lbl">District</span>
    <select id="fdistrict">${set.map((d) =>
      `<option value="${esc(d)}" ${S.district === d ? 'selected' : ''}>${d === 'all' ? 'all districts' : esc(d.toLowerCase().replace(/_/g, ' '))}</option>`).join('')}</select>
  </div>`;
}

function wireFilters(root) {
  const q = $('#fq', root);
  if (q) {
    q.addEventListener('input', (e) => {
      S.q = e.target.value;
      render({ keepFocus: '#fq', caret: e.target.selectionStart });
    });
  }
  root.querySelectorAll('[data-status]').forEach((b) =>
    b.addEventListener('click', () => { S.status = b.dataset.status; render(); }));
  const d = $('#fdistrict', root);
  if (d) d.addEventListener('change', (e) => { S.district = e.target.value; render(); });
  const r = $('#freset', root);
  if (r) r.addEventListener('click', () => { S.q = ''; S.district = 'all'; S.status = 'all'; render(); });
}

/* ── view: live map ─────────────────────────────────────────────── */

/* Real Gujarat map, on the vendored Leaflet. The map object outlives a render:
 * #views is rebuilt wholesale on every state change, so the map container is
 * created once and re-parented into the fresh markup, then told to re-measure.
 * Destroying and rebuilding it per keystroke would refetch every tile. */
// Gujarat, corner to corner: Kutch's west tip to the Rajasthan/MP border, and
// the Rann down to Valsad. The map is clamped to this so the console cannot be
// panned off into an ocean of empty tiles.
const GUJARAT_BOUNDS = [[20.0, 68.1], [24.8, 74.6]];
const HAVE_LEAFLET = typeof L !== 'undefined' && !!L.map;
const MAPS = {};   // key -> {host, map, layers}

function mapHost(key) {
  if (!MAPS[key]) MAPS[key] = { host: document.createElement('div'), map: null, layers: {} };
  const m = MAPS[key];
  m.host.style.cssText = 'position:absolute;inset:0;background:#0B1316';
  return m;
}

// CARTO's free XYZ tiles now gate on Referer/Origin: a plain fetch (curl, no
// Referer) gets a real tile, but the browser gets a watermarked "API key
// required" placeholder — this is what left the map looking broken. Rather
// than depend on a third party that can revoke free access without notice,
// the dark basemap is built from the one tile source that stays open with no
// key and no allowlist — OpenStreetMap's own tiles — recoloured with a CSS
// filter on the tile pane. No external dependency, nothing to expire.
const BASEMAPS = {
  dark:      ['https://tile.openstreetmap.org/{z}/{x}/{y}.png', '© OpenStreetMap contributors', 'invert(92%) hue-rotate(180deg) brightness(0.95) contrast(0.92)'],
  streets:   ['https://tile.openstreetmap.org/{z}/{x}/{y}.png', '© OpenStreetMap contributors', 'none'],
  satellite: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', '© Esri', 'none'],
};

function ensureMap(key, onReady) {
  if (!HAVE_LEAFLET) return null;
  const m = mapHost(key);
  if (!m.map) {
    const bounds = L.latLngBounds(GUJARAT_BOUNDS[0], GUJARAT_BOUNDS[1]);
    m.map = L.map(m.host, {
      zoomControl: false, attributionControl: true,
      maxBounds: bounds.pad(0.35), maxBoundsViscosity: 0.7,
      minZoom: 6, maxZoom: 18, fadeAnimation: false,
    }).fitBounds(bounds);
    L.control.zoom({ position: 'topleft' }).addTo(m.map);
    m.layers.base = tileLayerFor(S.basemap).addTo(m.map);
    applyBasemapFilter(m, S.basemap);
    m.layers.pins = L.layerGroup().addTo(m.map);
    m.layers.wedges = L.layerGroup().addTo(m.map);
    m.layers.heat = L.layerGroup().addTo(m.map);
    m.map.on('zoomend', () => onReady && onReady(m, true));
  }
  // Measure after the browser has laid the container out, not before: a
  // setTimeout(0) can land ahead of layout and leave Leaflet believing it is
  // 0x0, which paints a grey box. rAF runs after layout.
  const settle = () => { m.map.invalidateSize(); onReady && onReady(m, false); };
  if (typeof requestAnimationFrame === 'function') requestAnimationFrame(() => requestAnimationFrame(settle));
  else setTimeout(settle, 0);

  // A pane resize (rail collapse, window drag) must re-measure too.
  if (!m.ro && typeof ResizeObserver === 'function') {
    m.ro = new ResizeObserver(() => m.map && m.map.invalidateSize());
    m.ro.observe(m.host);
  }
  return m;
}

// Basemap tiles come off a CDN, so a filtered network shows a grey void with
// no clue why. Count the failures and say so instead of leaving a blank map.
function tileLayerFor(key) {
  const layer = L.tileLayer(BASEMAPS[key][0], {
    maxZoom: 19, attribution: BASEMAPS[key][1], detectRetina: false,
  });
  let bad = 0, good = 0;
  layer.on('tileerror', () => {
    bad++;
    if (bad === 6 && good === 0 && !S.tileWarned) {
      S.tileWarned = true;
      toast('Basemap tiles are not loading — the network may be blocking ' +
            new URL(BASEMAPS[key][0].replace('{s}', 'a')).hostname +
            '. Camera positions still work.', 'var(--amber)');
    }
  });
  layer.on('tileload', () => { good++; });
  return layer;
}

// "Dark" is OSM's own tiles run through a CSS filter on the tile pane, not a
// separately hosted dark tileset — invert + hue-rotate turns light-on-white
// cartography into light-on-ink without a second tile server to depend on.
function applyBasemapFilter(m, key) {
  const pane = m.map.getPane('tilePane');
  if (pane) pane.style.filter = BASEMAPS[key][2] || 'none';
}

function setBasemap(key) {
  S.basemap = key;
  S.tileWarned = false;
  Object.values(MAPS).forEach((m) => {
    if (!m.map || !m.layers.base) return;
    m.map.removeLayer(m.layers.base);
    m.layers.base = tileLayerFor(key).addTo(m.map);
    m.layers.base.bringToBack();
    applyBasemapFilter(m, key);
  });
}

// A field-of-view wedge in real metres. Only drawn once the view is close
// enough for a 60 m throw to be more than a pixel — below that it is a lie
// dressed as detail, so the camera stays a dot.
function fovPolygon(lat, lon, bearing, fovDeg, rangeM) {
  const pts = [[lat, lon]];
  const R = 6378137;
  const steps = 14;
  for (let i = 0; i <= steps; i++) {
    const a = (bearing - fovDeg / 2 + (fovDeg * i) / steps) * Math.PI / 180;
    const dLat = (rangeM * Math.cos(a)) / R * 180 / Math.PI;
    const dLon = (rangeM * Math.sin(a)) / (R * Math.cos(lat * Math.PI / 180)) * 180 / Math.PI;
    pts.push([lat + dLat, lon + dLon]);
  }
  return pts;
}

function paintMap(m, zoomOnly) {
  const vis = visibleCameras().filter(placed);
  m.layers.pins.clearLayers();
  m.layers.wedges.clearLayers();
  m.layers.heat.clearLayers();
  const z = m.map.getZoom();

  vis.forEach((c) => {
    const h = health(c);
    const col = hcolHex(h);
    const isSel = S.sel === c.camera_id;

    if (S.layers.heat) {
      L.circle([c.geo.lat, c.geo.lon], {
        radius: 9000, stroke: false, fillColor: '#F2A93B', fillOpacity: 0.16, interactive: false,
      }).addTo(m.layers.heat);
    }
    if (S.layers.wedges && c.geo.bearing_deg != null && z >= 13) {
      L.polygon(fovPolygon(c.geo.lat, c.geo.lon, c.geo.bearing_deg, c.geo.fov_deg || 70, c.geo.range_m || 60), {
        color: col, weight: 1, fillColor: col, fillOpacity: isSel ? 0.3 : 0.15, interactive: false,
      }).addTo(m.layers.wedges);
    }

    const marker = L.circleMarker([c.geo.lat, c.geo.lon], {
      radius: isSel ? 9 : 6, color: isSel ? '#F2A93B' : col,
      weight: isSel ? 3 : 1.5, fillColor: col, fillOpacity: 0.95,
    }).addTo(m.layers.pins);
    marker.on('click', () => { S.sel = c.camera_id; render(); });
    marker.bindTooltip(
      `<b>${esc(camName(c))}</b><br>cam ${esc(c.camera_id)} · ${esc(c.district_code || 'UNKNOWN')} · ${h}`,
      { direction: 'top', opacity: 0.95 });
    if (S.layers.labels && z >= 10) {
      L.marker([c.geo.lat, c.geo.lon], {
        interactive: false,
        icon: L.divIcon({ className: '', html: `<div class="maplabel">${esc(camName(c))}</div>`, iconAnchor: [-10, 8] }),
      }).addTo(m.layers.pins);
    }
  });

  if (!zoomOnly && S.fitPending) {
    S.fitPending = false;
    const pts = vis.map((c) => [c.geo.lat, c.geo.lon]);
    if (pts.length) m.map.fitBounds(L.latLngBounds(pts).pad(0.25));
  }
}

// The route drawn on the same Gujarat map as the grid: legs coloured by kind,
// the implausible one dashed in coral so it reads as a refusal, not a path.
function paintTrace(m) {
  const t = S.trace;
  const hops = (t.data && Array.isArray(t.data.hops)) ? t.data.hops : [];
  const shown = t.probable ? hops : hops.filter((h) => (h.kind || '').toUpperCase() !== 'PROBABLE');
  const pl = shown.filter((h) => typeof h.lat === 'number' && typeof h.lon === 'number');

  m.layers.pins.clearLayers();
  m.layers.wedges.clearLayers();
  m.layers.heat.clearLayers();
  if (!pl.length) return;

  const cur = shown.find((h) => h.n === t.sel) || shown[0];
  const kcol = (h) => h.flag ? '#FF6B5A' : (h.kind || '').toUpperCase() === 'PROBABLE' ? '#B08CF5' : '#F2A93B';

  for (let i = 1; i < pl.length; i++) {
    const a = pl[i - 1], b = pl[i];
    const flagged = !!b.flag;
    const prob = (b.kind || '').toUpperCase() === 'PROBABLE';
    L.polyline([[a.lat, a.lon], [b.lat, b.lon]], {
      color: kcol(b), weight: 3, opacity: 0.95,
      dashArray: flagged ? '4 8' : prob ? '8 7' : null,
    }).addTo(m.layers.wedges);
  }

  pl.forEach((h) => {
    const isSel = cur && cur.n === h.n;
    const col = kcol(h);
    L.circleMarker([h.lat, h.lon], {
      radius: isSel ? 13 : 10, color: isSel ? '#EAF2F1' : col, weight: isSel ? 3 : 1.5,
      fillColor: col, fillOpacity: 1,
    }).addTo(m.layers.pins)
      .on('click', () => { S.trace.sel = h.n; render(); })
      .bindTooltip(`<b>hop ${h.n} — ${esc(h.name || 'cam ' + h.camera_id)}</b><br>${esc(String(h.pts || '').slice(11, 19))} · ${esc(h.band || '')}` +
        (h.flag ? `<br><span style="color:#FF6B5A">${esc(h.flag)}</span>` : ''), { direction: 'top', opacity: .95 });
    L.marker([h.lat, h.lon], {
      interactive: false,
      icon: L.divIcon({ className: '', html: `<div class="hopnum">${h.n}</div>`, iconSize: [18, 18], iconAnchor: [9, 9] }),
    }).addTo(m.layers.pins);
  });

  if (S.traceFit) {
    S.traceFit = false;
    m.map.fitBounds(L.latLngBounds(pl.map((h) => [h.lat, h.lon])).pad(0.3));
  }
}

function hcolHex(h) {
  return ({ LIVE: '#3FD2A4', READY: '#3FD2A4', CONNECTING: '#F2A93B', DEGRADED: '#F2A93B', DOWN: '#FF6B5A' })[h] || '#68807F';
}

// The camera list is its own node so a live poll can refresh it without
// rebuilding the view around the map.
function cameraListHTML() {
  const vis = visibleCameras();
  if (!vis.length) return '<div class="empty">No camera matches this filter.</div>';
  const rank = { DOWN: 0, DEGRADED: 1, CONNECTING: 1, LIVE: 2, READY: 3 };
  return vis.slice().sort((a, b) =>
    ((rank[health(a)] ?? 4) - (rank[health(b)] ?? 4)) || Number(a.camera_id) - Number(b.camera_id)
  ).map((c) => {
    const h = health(c);
    const w = S.wall[c.camera_id] || {};
    const transport = w.transport || (h === 'DOWN' ? 'no transport' : 'not pulling');
    return `<div class="row ${S.sel === c.camera_id ? 'on' : ''}" data-cam="${esc(c.camera_id)}">
      <span class="dot" style="background:${hcol(h)}"></span>
      <div class="grow">
        <div style="font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(camName(c))}</div>
        <div style="display:flex;gap:8px;margin-top:2px">
          <span class="mono" style="font-size:10.5px;color:var(--ghost)">cam ${esc(c.camera_id)}</span>
          <span class="mono" style="font-size:10.5px;color:var(--faint)">${esc(c.district_code || 'UNKNOWN')}</span>
        </div>
      </div>
      <div style="text-align:right;flex:none">
        <div class="mono" style="font-size:10.5px;color:${hcol(h)}">${h}</div>
        <div class="mono" style="font-size:10.5px;color:var(--ghost);margin-top:2px">${esc(transport)}</div>
      </div>
    </div>`;
  }).join('');
}

function viewMap() {
  const vis = visibleCameras();
  const on = vis.filter(placed);
  const unplaced = S.cameras.filter((c) => !placed(c)).length;

  const selCam = S.cameras.find((c) => c.camera_id === S.sel);

  return `
  <div class="filters">
    ${svg('<path d="M3 5h18l-7 8v6l-4 2v-8L3 5Z"></path>', 15, '#68807F', 1.8)}
    ${searchField('name or camera id')}
    ${statusSeg()}
    ${districtField()}
    <span style="width:1px;height:22px;background:var(--line);flex:none"></span>
    ${['wedges', 'labels', 'heat'].map((k) =>
      `<button class="toggle ${S.layers[k] ? 'on' : ''}" data-layer="${k}">
        <span class="box">${svg(I.tick, 10, '#0B1316', 3.4)}</span>
        ${k === 'heat' ? 'Sighting heat' : k[0].toUpperCase() + k.slice(1)}
      </button>`).join('')}
    <div class="grow"></div>
    <span class="mono" style="font-size:12px;color:var(--dim)">${vis.length} of ${S.cameras.length} cameras</span>
    <button class="btn" id="freset">${svg(I.reset, 13, '#9BB0B2', 2)} Reset</button>
  </div>

  <div class="body">
    <aside class="pane left">
      <div class="pane-head"><span class="lbl">Cameras</span><span class="mono" style="font-size:11px;color:var(--faint)">sorted by health</span></div>
      <div class="scroll" id="camList">${cameraListHTML()}</div>
      <div style="flex:none;padding:11px 14px;border-top:1px solid var(--line);background:var(--surface)">
        <div style="display:flex;align-items:center;justify-content:space-between">
          <span class="lbl" style="color:var(--violet)">Unplaced</span>
          <span class="mono" style="font-size:11px;color:var(--faint)">${unplaced} cameras</span>
        </div>
        <div style="margin-top:5px;font-size:11.5px;line-height:1.45;color:var(--faint)">
          No trustworthy coordinate in the catalogue. They still stream and still read plates, they just cannot be drawn.
        </div>
      </div>
    </aside>

    <div class="map-wrap" id="mapWrap">
      <div class="overlay tr" style="z-index:600">
        <div class="lbl" style="margin-bottom:6px">Basemap</div>
        <div class="seg" style="height:28px">
          ${Object.keys(BASEMAPS).map((k) =>
            `<button data-base="${k}" class="${S.basemap === k ? 'on' : ''}" style="height:22px;padding:0 9px;font-size:11.5px">${k}</button>`).join('')}
        </div>
        <div style="height:1px;background:var(--line);margin:10px 0"></div>
        <div class="lbl" style="margin-bottom:6px">Health</div>
        <div class="legend-row"><span class="dot" style="background:var(--jade)"></span>Live or ready</div>
        <div class="legend-row"><span class="dot" style="background:var(--amber)"></span>Degraded</div>
        <div class="legend-row"><span class="dot" style="background:var(--coral)"></span>Down at the grid</div>
        <div style="height:1px;background:var(--line);margin:9px 0"></div>
        <div class="legend-row"><span style="width:8px;height:8px;background:#F2A93B33;border:1px solid var(--amber)"></span>Field of view, from zoom 13</div>
      </div>
      <div class="overlay bl" style="z-index:600;display:flex;align-items:center;gap:12px;padding:8px 13px">
        <span class="mono" style="font-size:10.5px;color:var(--faint)">${on.length} drawn · ${unplaced} unplaced</span>
        <button class="btn" id="fitBtn" style="height:24px;padding:0 10px;font-size:11.5px">Fit to filter</button>
      </div>
    </div>

    <aside class="pane right">
      <div class="scroll">${selCam ? cameraDetail(selCam) : '<div class="empty">Pick a camera on the map or in the list.</div>'}</div>
    </aside>
  </div>`;
}

function cameraDetail(c) {
  const h = health(c);
  const w = S.wall[c.camera_id] || {};
  const g = c.geo || {};
  const age = w.age_s == null ? (h === 'DOWN' ? 'no frame' : 'not pulling') : `frame ${w.age_s.toFixed(1)} s old`;
  return `
  <div style="padding:16px;border-bottom:1px solid var(--line)">
    <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px">
      <div style="min-width:0">
        <div style="font-family:var(--display);font-weight:700;font-size:17px;letter-spacing:-.015em;line-height:1.25">${esc(camName(c))}</div>
        <div style="display:flex;gap:9px;margin-top:5px">
          <span class="mono" style="font-size:11px;color:var(--ghost)">cam ${esc(c.camera_id)}</span>
          <span class="mono" style="font-size:11px;color:var(--faint)">${esc(c.district_code || 'UNKNOWN')}</span>
        </div>
      </div>
      <span style="display:flex;align-items:center;gap:7px;height:24px;padding:0 10px;border-radius:999px;background:${hcol(h)}1F;flex:none">
        <span class="sq" style="border-radius:50%;background:${hcol(h)}"></span>
        <span class="mono" style="font-size:10.5px;color:${hcol(h)}">${h}</span>
      </span>
    </div>
  </div>

  <div style="padding:14px 16px;border-bottom:1px solid var(--line)">
    <div class="card" style="overflow:hidden;position:relative;background:#070E10">
      ${w.has_frame
        ? `<img src="/tile/${encodeURIComponent(c.camera_id)}.jpg?t=${Date.now()}" alt="" style="width:100%;display:block;aspect-ratio:16/9;object-fit:cover">`
        : `<div style="aspect-ratio:16/9;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;color:var(--faint)">
             ${svg(I.cam, 24, '#2E4248', 1.5)}
             <span class="mono" style="font-size:11px">${h === 'DOWN' ? 'no signal at the grid' : 'not pulling — start the wall'}</span>
           </div>`}
      <div class="tag tl"><span class="sq" style="border-radius:50%;background:${hcol(h)}"></span>${h}</div>
      <div class="tag tr">${esc(age)}</div>
    </div>
    <div style="display:flex;gap:8px;margin-top:10px">
      <button class="btn primary grow" data-goto-wall="${esc(c.camera_id)}">Open in wall</button>
      <button class="btn grow" data-pull="${esc(c.camera_id)}">${w.status === 'running' ? 'Stop feed' : 'Start feed'}</button>
    </div>
  </div>

  <div style="padding:14px 16px;border-bottom:1px solid var(--line)">
    <div class="lbl" style="margin-bottom:10px">Placement</div>
    <div class="kv">
      <div><div class="k">Coordinates</div><div class="v">${placed(c) ? `${g.lat.toFixed(4)}, ${g.lon.toFixed(4)}` : 'not resolved'}</div></div>
      <div><div class="k">Confidence</div><div class="v" style="color:${g.coord_conf === 'HIGH' ? 'var(--jade)' : g.coord_conf === 'LOW' ? 'var(--coral)' : 'var(--amber)'}">${esc(g.coord_conf || 'NONE')}</div></div>
      <div><div class="k">Bearing and field</div><div class="v">${g.bearing_deg == null ? 'not surveyed' : `${g.bearing_deg}°, ${g.fov_deg || 70}° field, ${g.range_m || 60} m`}</div></div>
      <div><div class="k">Install</div><div class="v">${esc(c.install_type || 'FIX')}</div></div>
    </div>
    ${g.coord_source ? `<div style="margin-top:9px;font-size:11.5px;color:var(--faint)">Coordinate source: ${esc(g.coord_source)}. ${g.coord_conf === 'MEDIUM' ? 'Geocoded from the location text, not surveyed on the ground.' : ''}</div>` : ''}
  </div>

  <div style="padding:14px 16px">
    <div class="lbl" style="margin-bottom:10px">Transports</div>
    ${transportRows(c, w).map((row) => {
      return `<div style="display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid #182429">
        <span class="mono" style="font-size:11.5px;width:44px;color:var(--ink)">${row.t}</span>
        <span class="mono" style="font-size:10.5px;color:${row.col}">${row.state}</span>
        <div class="grow"></div>
        <span class="mono" style="font-size:10px;color:var(--ghost);max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(row.url || '—')}</span>
      </div>`;
    }).join('')}
    <div style="margin-top:10px;font-size:11.5px;line-height:1.45;color:var(--faint)">
      RTSP and WebRTC run direct to the grid's public IP with no session needed; HLS goes through the CDN host and needs a signed-in session.
    </div>
  </div>`;
}

// Real per-transport state for the detail panel: RTSP and HLS read from what
// the wall actually observed for this camera, not the catalogue's one-time
// probe -- that probe only ever tested HLS and is what made 17/18/22 read
// DOWN despite opening fine over RTSP.
function transportRows(c, w) {
  const numeric = /^\d+$/.test(String(c.camera_id));
  const camNN = numeric ? String(c.camera_id).padStart(2, '0') : null;
  const rtspUrl = camNN ? `rtsp://103.250.160.189:8554/stream/cam${camNN}` : null;
  const whepUrl = camNN ? `http://103.250.160.189:8889/stream/cam${camNN}/whep` : null;
  // The catalogue's own transports.hls predates the current integrator's
  // guide (old host/path shape); construct the documented one instead.
  const hlsUrl = camNN ? `https://cctv.corp8.cloud/cam${camNN}/index.m3u8` : (c.transports || {}).hls;

  const rtspTried = w && w.status && w.status !== 'idle' && w.status !== 'stopped';
  const rtspLive = rtspTried && w.transport === 'rtsp';
  const rtspRow = rtspUrl
    ? { t: 'rtsp', url: rtspUrl,
        state: rtspLive ? (w.has_frame ? 'reachable' : 'connecting') : (rtspTried && w.transport !== 'rtsp' ? 'not reachable' : 'not yet tried'),
        col: rtspLive ? (w.has_frame ? 'var(--jade)' : 'var(--amber)') : (rtspTried && w.transport !== 'rtsp' ? 'var(--coral)' : 'var(--faint)') }
    : { t: 'rtsp', url: null, state: 'no numeric id', col: 'var(--faint)' };

  const hlsLive = rtspTried && w.transport === 'hls';
  const hlsRow = { t: 'hls', url: hlsUrl,
    state: hlsLive ? (w.has_frame ? 'reachable' : 'connecting') : (S.grid && S.grid.state === 'signed in' ? 'session ready' : 'needs GRID_KEY'),
    col: hlsLive && w.has_frame ? 'var(--jade)' : (S.grid && S.grid.state === 'signed in' ? 'var(--amber)' : 'var(--faint)') };

  const whepRow = { t: 'whep', url: whepUrl, state: 'not pulled by this console', col: 'var(--faint)' };

  return [rtspRow, hlsRow, whepRow];
}

/* ── view: video wall ───────────────────────────────────────────── */

function viewWall() {
  const vis = visibleCameras();
  const sel = S.cameras.find((c) => c.camera_id === S.sel) || vis[0];
  const stamp = S.frameStamp || 0;

  const tile = (c) => {
    const h = health(c);
    const w = S.wall[c.camera_id] || {};
    const transport = w.transport || (h === 'DOWN' ? 'no transport' : 'not pulling');
    return `<div class="tile ${sel && sel.camera_id === c.camera_id ? 'on' : ''}" data-cam="${esc(c.camera_id)}">
      <div class="frame">
        ${w.has_frame
          ? `<img src="/tile/${encodeURIComponent(c.camera_id)}.jpg?t=${stamp}" alt="" loading="lazy">`
          : `<div class="ph">${svg(I.cam, 20, '#2E4248', 1.5)}<span>${h === 'DOWN' ? 'NO SIGNAL' : (w.status === 'connecting' ? 'connecting…' : 'idle')}</span>${h === 'DOWN' && w.detail ? `<span style="color:var(--ghost)">${esc(String(w.detail).slice(0, 40))}</span>` : ''}</div>`}
        <div class="tag tl"><span class="sq" style="border-radius:50%;background:${hcol(h)}"></span>${h}</div>
        <div class="tag tr" style="color:${w.stale ? 'var(--amber)' : 'var(--dim)'}">${w.age_s == null ? '—' : `${w.age_s.toFixed(1)} s`}</div>
      </div>
      <div class="cap">
        <div class="grow">
          <div class="nm">${esc(camName(c))}</div>
          <div class="meta">cam ${esc(c.camera_id)} · ${esc(transport)}${w.codec ? ` · ${esc(w.codec)} ${esc(w.resolution || '')}` : ''}</div>
        </div>
      </div>
    </div>`;
  };

  const selHealth = sel ? health(sel) : 'DOWN';
  const selWall = sel ? (S.wall[sel.camera_id] || {}) : {};

  return `
  <div class="filters">
    ${searchField('camera or district')}
    ${statusSeg()}
    ${districtField()}
    <span style="width:1px;height:22px;background:var(--line);flex:none"></span>
    <div class="seg">${[2, 3, 4].map((n) =>
      `<button data-cols="${n}" class="${S.cols === n ? 'on' : ''}"><span class="mono">${n} × ${n}</span></button>`).join('')}</div>
    <button class="toggle ${S.focus ? 'on' : ''}" id="focusToggle">
      <span class="box">${svg(I.tick, 10, '#0B1316', 3.4)}</span>Focus pane
    </button>
    <div class="grow"></div>
    <span class="mono" style="font-size:12px;color:var(--dim)">${vis.length} feeds · ${S.wallRunning} pulling</span>
    <button class="btn" id="wallStop">${svg(I.stop, 13, '#FF6B5A', 2)} Stop all</button>
    <button class="btn primary" id="wallStart">${svg(I.play, 13, '#0B1316', 2)} Start wall</button>
  </div>

  <div class="body" style="gap:0">
    ${S.focus && sel ? `
    <div class="stage">
      <div class="player">
        ${selWall.has_frame
          ? `<img src="/tile/${encodeURIComponent(sel.camera_id)}.jpg?t=${stamp}" alt="">`
          : `<div class="ph">${svg(I.cam, 34, '#2E4248', 1.4)}
               <span class="mono" style="font-size:12.5px">${selHealth === 'DOWN' ? 'NO SIGNAL — neither transport is reachable' : 'no frame yet — start the wall'}</span></div>`}
        <div class="hud top">
          <div class="chipd" style="display:flex;align-items:center;gap:8px">
            <span class="${selWall.has_frame ? 'blink' : ''} sq" style="border-radius:50%;background:${hcol(selHealth)}"></span>
            <span class="mono" style="font-size:11.5px;letter-spacing:.1em">${selHealth}</span>
          </div>
          <div class="chipd">${esc(camName(sel))}</div>
          <div class="chipd m">cam ${esc(sel.camera_id)} · ${esc(sel.district_code || 'UNKNOWN')}</div>
        </div>
        <div class="hud tr">
          <div class="chipd m">${selWall.age_s == null ? 'no frame' : `frame ${selWall.age_s.toFixed(1)} s old`}</div>
          ${selWall.transport ? `<div class="chipd m" style="background:${selWall.transport === 'rtsp' ? 'var(--jade-soft)' : 'var(--amber-soft)'};color:${selWall.transport === 'rtsp' ? 'var(--jade)' : 'var(--amber)'}">${esc(selWall.transport)}${selWall.codec ? ` · ${esc(selWall.codec)} ${esc(selWall.resolution || '')}` : ''}</div>` : ''}
        </div>
      </div>
      <div class="card" style="flex:none;padding:12px 14px;display:flex;align-items:center;gap:14px">
        <span class="lbl">This feed</span>
        <span class="mono" style="font-size:11.5px;color:var(--dim)">${esc((sel.geo && sel.geo.landmark) || sel.location_raw || '—')}</span>
        <div class="grow"></div>
        <button class="btn" data-pull="${esc(sel.camera_id)}">${selWall.status === 'running' ? 'Stop this feed' : 'Start this feed'}</button>
        <button class="btn" data-goto-map="${esc(sel.camera_id)}">Show on map</button>
      </div>
    </div>` : ''}

    <div class="${S.focus ? '' : 'grow'}" style="${S.focus ? 'width:470px;flex:none;' : ''}display:flex;flex-direction:column;min-width:0;min-height:0;border-left:${S.focus ? '1px solid var(--line)' : 'none'}">
      <div class="scroll">
        <div class="tiles" style="grid-template-columns:repeat(${S.cols}, minmax(0, 1fr))">
          ${vis.map(tile).join('') || '<div class="empty">No feed matches this filter.</div>'}
        </div>
      </div>
    </div>
  </div>`;
}

/* ── view: route trace ──────────────────────────────────────────── */

function viewTrace() {
  const t = S.trace;
  const hops = t.data && Array.isArray(t.data.hops) ? t.data.hops : [];
  const shown = t.probable ? hops : hops.filter((h) => (h.kind || '').toUpperCase() !== 'PROBABLE');
  const cur = shown.find((h) => h.n === t.sel) || shown[0] || null;

  const kindCol = (h) => {
    const k = (h.kind || '').toUpperCase();
    if (h.flag) return 'var(--coral)';
    if (k === 'PROBABLE') return 'var(--violet)';
    return 'var(--amber)';
  };

  const placedHops = shown.filter((h) => typeof h.lat === 'number' && typeof h.lon === 'number');

  return `
  <div class="filters">
    <div class="field hot" style="width:236px;height:34px">
      <span class="lbl" style="color:var(--amber)">Plate</span>
      <input class="grow mono" id="tracePlate" value="${esc(t.plate)}" placeholder="GJ01AB1234"
             style="font-size:14px;letter-spacing:.06em" autocomplete="off">
    </div>
    <button class="btn primary" id="traceGo" style="height:34px" ${t.loading || !t.plate.trim() ? 'disabled' : ''}>${t.loading ? 'Tracing…' : 'Trace'}</button>
    <button class="toggle ${t.probable ? 'on' : ''}" id="probToggle" style="height:34px">
      <span class="box">${svg(I.tick, 10, '#0B1316', 3.4)}</span>Show probable hops
    </button>
    <div class="grow"></div>
    ${t.data ? `<span class="mono" style="font-size:12px;color:var(--dim)">${shown.length} hops${t.data.fuzzy ? ' · fuzzy match' : ''}</span>` : ''}
    <button class="btn" id="traceCsv" ${hops.length ? '' : 'disabled'}>${svg(I.down, 13, '#9BB0B2', 1.9)} CSV</button>
  </div>

  <div class="body">
    <aside class="pane left" style="width:346px">
      <div class="pane-head"><span class="lbl">Hops in order</span><span class="mono" style="font-size:11px;color:var(--ghost)">${esc(t.plate)}</span></div>
      <div class="scroll" style="padding:14px 16px">
        ${t.error ? `<div class="empty" style="color:var(--coral)">${esc(t.error)}</div>` : ''}
        ${!t.error && !t.data ? `<div class="empty">${t.plate.trim() ? 'Press Trace to reconstruct this plate’s route.' : 'Enter a plate above, then press Trace.'}</div>` : ''}
        ${!t.error && t.data && shown.length === 0 ? '<div class="empty">No sighting of this plate in the window.</div>' : ''}
        ${shown.map((h, i) => {
          const col = kindCol(h);
          const isSel = cur && cur.n === h.n;
          const contiguous = i === 0 || shown[i - 1].n === h.n - 1;
          return `<div class="rise" data-hop="${h.n}" style="display:flex;gap:13px;cursor:pointer">
            <div style="display:flex;flex-direction:column;align-items:center;flex:none;width:28px">
              <span style="display:flex;align-items:center;justify-content:center;width:28px;height:28px;border-radius:50%;border:1.5px solid ${col};background:${isSel ? col : '#0E181C'};color:${isSel ? '#0B1316' : col};font-family:var(--mono);font-size:12px;flex:none">${h.n}</span>
              ${i < shown.length - 1 ? '<span style="width:1.5px;flex:1;background:var(--line);min-height:16px"></span>' : ''}
            </div>
            <div class="grow" style="padding-bottom:14px">
              <div style="padding:11px 13px;border:1px solid ${isSel ? '#F2A93B66' : 'var(--line)'};border-radius:7px;background:${isSel ? 'var(--raised)' : 'var(--surface)'}">
                <div style="display:flex;align-items:center;justify-content:space-between;gap:8px">
                  <span style="font-size:13.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(h.name || `Camera ${h.camera_id}`)}</span>
                  <span class="band ${esc((h.band || 'NONE').toUpperCase())}" style="flex:none">${esc(h.band || '—')}</span>
                </div>
                <div style="display:flex;align-items:center;gap:10px;margin-top:6px">
                  <span class="mono" style="font-size:12px;color:var(--dim)">${esc(String(h.pts || '').slice(11, 19) || '—')}</span>
                  <span class="mono" style="font-size:10.5px;color:var(--ghost)">cam ${esc(h.camera_id)}</span>
                </div>
                <div style="display:flex;align-items:center;gap:8px;margin-top:9px;padding-top:9px;border-top:1px solid #1E2C31">
                  ${svg(I.speed, 12, h.flag ? '#FF6B5A' : '#9BB0B2', 2)}
                  <span class="mono" style="font-size:11.5px;color:${h.flag ? 'var(--coral)' : 'var(--dim)'}">
                    ${h.implied_speed_kmh == null ? (i === 0 ? 'first sighting' : 'speed not computed')
                      : contiguous ? `${h.implied_speed_kmh} km/h implied` : 'not recomputed, hop hidden'}
                  </span>
                </div>
                ${h.flag ? `<div style="display:flex;gap:8px;align-items:flex-start;margin-top:9px;padding:9px 10px;border-radius:5px;background:var(--coral-soft)">
                  ${svg(I.warn, 13, '#FF6B5A', 2)}
                  <span style="font-size:11.5px;line-height:1.45;color:#FFB4A8">${esc(h.flag)}</span></div>` : ''}
                ${h.reid_similarity != null ? `<div style="margin-top:8px;font-size:11.5px;color:var(--violet)">Corroborated by appearance at ${h.reid_similarity}</div>` : ''}
              </div>
            </div>
          </div>`;
        }).join('')}
      </div>
    </aside>

    <div class="map-wrap" id="traceMapWrap">
      <div class="overlay tl" style="z-index:600">
        <div class="lbl" style="margin-bottom:6px">Hop kind</div>
        <div class="legend-row"><span style="width:16px;height:2.5px;background:var(--amber)"></span>Confirmed read</div>
        <div class="legend-row"><span style="width:16px;height:2.5px;background:var(--violet)"></span>Probable, corroborated</div>
        <div class="legend-row"><span style="width:16px;height:2.5px;background:var(--coral)"></span>Implausible leg</div>
        ${placedHops.length ? '' : '<div style="margin-top:9px;font-size:11.5px;color:var(--faint);max-width:190px">No hop in this trace carries a coordinate, so nothing can be drawn.</div>'}
      </div>
    </div>

    <aside class="pane right" style="width:334px">
      <div class="scroll">${cur ? hopDetail(cur, t) : '<div class="empty">No hop selected.</div>'}</div>
    </aside>
  </div>`;
}

function hopDetail(h, t) {
  const col = h.flag ? 'var(--coral)' : (h.kind || '').toUpperCase() === 'PROBABLE' ? 'var(--violet)' : 'var(--amber)';
  return `
  <div style="padding:16px;border-bottom:1px solid var(--line)">
    <div style="display:flex;align-items:center;gap:10px">
      <span style="display:flex;align-items:center;justify-content:center;width:26px;height:26px;border-radius:50%;background:${col};color:#0B1316;font-family:var(--mono);font-size:12px;flex:none">${h.n}</span>
      <div class="grow">
        <div style="font-family:var(--display);font-weight:700;font-size:16px;line-height:1.3">${esc(h.name || `Camera ${h.camera_id}`)}</div>
        <div class="mono" style="font-size:10.5px;color:var(--ghost);margin-top:2px">cam ${esc(h.camera_id)}</div>
      </div>
    </div>
  </div>
  <div style="padding:14px 16px;border-bottom:1px solid var(--line)">
    <div class="lbl" style="margin-bottom:10px">Plate read</div>
    <div style="display:flex;align-items:center;justify-content:space-between;gap:10px">
      <span class="plate lg">${esc(t.plate)}</span>
      <span class="band ${esc((h.band || 'NONE').toUpperCase())}">${esc(h.band || '—')}</span>
    </div>
    ${h.crop_url ? `<div class="card" style="margin-top:12px;overflow:hidden;background:#070E10">
        <img src="${esc(h.crop_url)}" alt="" style="width:100%;display:block"
             onerror="this.parentNode.innerHTML='<div style=&quot;padding:22px;text-align:center;color:var(--faint);font-size:12px&quot;>crop not retrievable from object storage</div>'">
      </div>` : ''}
  </div>
  <div style="padding:14px 16px;border-bottom:1px solid var(--line)">
    <div class="kv">
      <div><div class="k">Seen at</div><div class="v">${esc(String(h.pts || '').slice(11, 19) || '—')}</div></div>
      <div><div class="k">Kind</div><div class="v" style="color:${col}">${esc(h.kind || '—')}</div></div>
      <div><div class="k">Implied speed</div><div class="v" style="color:${h.flag ? 'var(--coral)' : 'var(--ink)'}">${h.implied_speed_kmh == null ? 'not applicable' : `${h.implied_speed_kmh} km/h`}</div></div>
      <div><div class="k">Corroboration</div><div class="v">${h.reid_similarity == null ? 'none' : h.reid_similarity}</div></div>
    </div>
  </div>
  ${h.flag ? `<div style="padding:14px 16px">
    <div class="lbl" style="margin-bottom:9px;color:var(--coral)">Why this leg is flagged</div>
    <div style="font-size:13px;line-height:1.55;color:#FFB4A8">${esc(h.flag)}</div>
  </div>` : ''}`;
}

/* ── view: alerts ───────────────────────────────────────────────── */

const SEVCOL = { CRITICAL: 'var(--coral)', HIGH: 'var(--amber)', MEDIUM: 'var(--violet)', LOW: 'var(--faint)' };
const STCOL = { NEW: 'var(--coral)', ACKNOWLEDGED: 'var(--amber)', ACTIONED: 'var(--jade)', DISMISSED: 'var(--faint)' };

function viewAlerts() {
  const a = S.alerts;
  const rows = a.rows || [];
  const vis = rows.filter((r) => {
    if (a.severity !== 'all' && (r.severity || '').toUpperCase() !== a.severity) return false;
    if (a.state !== 'all' && (r.state || '').toUpperCase() !== a.state) return false;
    const q = S.q.trim().toLowerCase();
    if (q && !`${r.plate_text || ''} ${r.camera_name || ''} ${r.reason || ''}`.toLowerCase().includes(q)) return false;
    return true;
  });
  const cur = vis.find((r) => r.id === a.sel) || vis[0] || null;
  const cnt = (k, field) => rows.filter((r) => k === 'all' || (r[field] || '').toUpperCase() === k).length;

  return `
  <div class="filters">
    ${searchField('plate, camera, FIR')}
    <div class="seg">${['all', 'CRITICAL', 'HIGH', 'MEDIUM'].map((k) =>
      `<button data-sev="${k}" class="${a.severity === k ? 'on' : ''}">
        ${k === 'all' ? 'All' : k[0] + k.slice(1).toLowerCase()}<span class="n">${cnt(k, 'severity')}</span></button>`).join('')}</div>
    <div class="seg">${['all', 'NEW', 'ACKNOWLEDGED', 'ACTIONED', 'DISMISSED'].map((k) =>
      `<button data-astate="${k}" class="${a.state === k ? 'on' : ''}"><span class="mono" style="font-size:11.5px">${k === 'all' ? 'ALL' : k === 'ACKNOWLEDGED' ? 'ACK' : k}</span><span class="n">${cnt(k, 'state')}</span></button>`).join('')}</div>
    <div class="grow"></div>
    <span class="mono" style="font-size:12px;color:var(--dim)">${vis.length} in queue</span>
    <button class="btn" id="alertsReload">${svg(I.reset, 13, '#9BB0B2', 2)} Reload</button>
  </div>

  <div class="body">
    <aside class="pane left" style="width:472px">
      <div class="scroll">
        ${a.error ? `<div class="empty" style="color:var(--coral)">${esc(a.error)}</div>` : ''}
        ${!a.error && a.rows === null ? '<div class="empty">Loading the queue…</div>' : ''}
        ${!a.error && a.rows && vis.length === 0 ? `<div class="empty">
            ${rows.length === 0 ? 'The queue is empty. Nothing on the grid has matched the watchlist yet.' : 'Nothing in the queue matches this filter.'}
          </div>` : ''}
        ${vis.map((r) => {
          const sev = (r.severity || 'MEDIUM').toUpperCase();
          const st = (r.state || 'NEW').toUpperCase();
          return `<div class="row ${cur && cur.id === r.id ? 'on' : ''}" data-alert="${r.id}" style="align-items:flex-start;border-left-color:${cur && cur.id === r.id ? 'var(--amber)' : SEVCOL[sev]}">
            <span class="sq" style="background:${SEVCOL[sev]};margin-top:5px"></span>
            <div class="grow">
              <div style="display:flex;align-items:center;gap:10px">
                <span class="mono" style="font-size:15px;letter-spacing:.05em">${esc(r.plate_text || 'no plate')}</span>
                <span class="band ${esc((r.band || 'NONE').toUpperCase())}">${esc(r.band || '')}</span>
                ${r.count > 1 ? `<span class="mono" style="padding:1px 7px;border-radius:999px;background:#22343A;font-size:10px;color:var(--dim)">×${r.count} cameras</span>` : ''}
              </div>
              <div style="margin-top:5px;font-size:13px;color:#C6D5D5;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(r.reason || '—')}</div>
              <div style="display:flex;align-items:center;gap:9px;margin-top:6px">
                <span class="mono" style="font-size:10.5px;color:var(--faint)">${esc(r.camera_name || `cam ${r.camera_id}`)}</span>
                <span class="mono" style="font-size:10.5px;color:var(--faint)">${esc(String(r.pts || '').slice(11, 19))}</span>
              </div>
            </div>
            <div style="flex:none;text-align:right">
              <span class="mono" style="padding:2px 8px;border-radius:3px;background:${STCOL[st]}1F;font-size:10px;color:${STCOL[st]}">${st === 'ACKNOWLEDGED' ? 'ACK' : st}</span>
              <div class="mono" style="font-size:10px;color:var(--ghost);margin-top:7px">${esc((r.category || '').replace(/_/g, ' '))}</div>
            </div>
          </div>`;
        }).join('')}
      </div>
    </aside>

    <div class="grow" style="display:flex;flex-direction:column;min-width:0;background:var(--void)">
      <div class="scroll" style="padding:20px 24px">${cur ? alertDetail(cur) : '<div class="empty">No alert selected.</div>'}</div>
    </div>
  </div>`;
}

function alertDetail(r) {
  const sev = (r.severity || 'MEDIUM').toUpperCase();
  const st = (r.state || 'NEW').toUpperCase();
  const canAck = st === 'NEW';
  const canAction = st === 'ACKNOWLEDGED';
  const closed = st === 'ACTIONED' || st === 'DISMISSED';
  return `
  <div style="display:flex;align-items:flex-start;gap:20px">
    <div class="grow">
      <div style="display:flex;align-items:center;gap:12px">
        <span style="display:flex;align-items:center;gap:7px;height:26px;padding:0 11px;border-radius:4px;background:${SEVCOL[sev]}1F;font-family:var(--mono);font-size:11px;letter-spacing:.08em;color:${SEVCOL[sev]}">
          <span class="sq" style="background:${SEVCOL[sev]}"></span>${sev}</span>
        <span class="mono" style="font-size:11.5px;color:var(--faint)">alert #${esc(r.id)}</span>
        <span class="mono" style="font-size:11.5px;color:var(--faint)">${esc((r.category || '').replace(/_/g, ' '))}</span>
      </div>
      <div style="font-family:var(--display);font-weight:700;font-size:34px;letter-spacing:.02em;margin-top:12px;line-height:1.1">${esc(r.plate_text || 'no plate')}</div>
      <div style="margin-top:8px;font-size:15px;color:#C6D5D5">${esc(r.reason || '—')}</div>
    </div>
    <div style="flex:none;text-align:right">
      <div class="lbl">Current state</div>
      <div class="mono" style="margin-top:8px;padding:7px 14px;border-radius:5px;background:${STCOL[st]}1F;font-size:14px;letter-spacing:.06em;color:${STCOL[st]}">${st}</div>
    </div>
  </div>

  <div class="card" style="display:flex;gap:10px;margin-top:20px;padding:14px 16px;align-items:center">
    ${canAck ? `<button class="btn primary tall" data-act="ACKNOWLEDGED" data-id="${r.id}">${svg(I.tick, 15, '#0B1316', 2.3)} Acknowledge</button>` : ''}
    ${canAction ? `<button class="btn tall" data-act="ACTIONED" data-id="${r.id}" style="border-color:var(--jade);background:var(--jade-soft);color:var(--jade)">Mark actioned</button>` : ''}
    ${!closed ? `<button class="btn tall" data-act="DISMISSED" data-id="${r.id}">Dismiss</button>` : ''}
    ${closed ? `<div style="display:flex;align-items:center;gap:9px;height:38px;padding:0 16px;border-radius:5px;background:var(--raised);color:var(--faint);font-size:13.5px">Closed. Reopening needs a supervisor.</div>` : ''}
    <div class="grow"></div>
    <button class="btn tall" data-trace-plate="${esc(r.plate_text || '')}">${svg(I.trace, 15, '#B08CF5', 1.9)} Trace this plate</button>
    <button class="btn tall" data-goto-map="${esc(r.camera_id)}">Show on map</button>
  </div>

  <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin-top:14px">
    <div class="card" style="padding:14px 16px">
      <div class="lbl">The read that raised it</div>
      <div style="display:flex;align-items:center;gap:12px;margin-top:12px">
        <span class="plate">${esc(r.plate_text || 'no plate')}</span>
        <span class="band ${esc((r.band || 'NONE').toUpperCase())}">${esc(r.band || '—')}</span>
      </div>
      <div class="kv" style="margin-top:14px">
        <div><div class="k">Camera</div><div class="v" style="font-family:var(--sans);font-size:13px">${esc(r.camera_name || `cam ${r.camera_id}`)}</div></div>
        <div><div class="k">Seen at</div><div class="v">${esc(String(r.pts || '').slice(11, 19) || '—')}</div></div>
        <div><div class="k">District</div><div class="v" style="font-family:var(--sans);font-size:13px">${esc(r.district_code || '—')}</div></div>
        <div><div class="k">Sighting</div><div class="v" style="font-size:11px">${esc(String(r.sighting_id || '—').slice(0, 14))}</div></div>
      </div>
    </div>
    <div class="card" style="padding:14px 16px">
      <div class="lbl">Watchlist entry</div>
      <div class="kv" style="margin-top:12px">
        <div><div class="k">Category</div><div class="v" style="font-family:var(--sans);font-size:13px">${esc((r.category || '—').replace(/_/g, ' '))}</div></div>
        <div><div class="k">Severity</div><div class="v" style="color:${SEVCOL[sev]}">${sev}</div></div>
        <div><div class="k">Entry</div><div class="v">#${esc(r.watchlist_id ?? '—')}</div></div>
        <div><div class="k">Raised</div><div class="v">${esc(String(r.created_at || '').slice(11, 19) || '—')}</div></div>
      </div>
      <div style="display:flex;align-items:center;gap:8px;margin-top:14px;padding-top:12px;border-top:1px solid var(--line)">
        ${svg(I.chain, 13, '#B08CF5', 1.9)}
        <span class="mono" style="font-size:11px;color:var(--faint)">every transition is appended to the audit chain</span>
      </div>
    </div>
  </div>`;
}

/* ── view: watchlist ────────────────────────────────────────────── */

function viewWatchlist() {
  const w = S.watch;
  const rows = w.rows || [];
  const vis = rows.filter((r) => {
    if (w.severity !== 'all' && (r.severity || '').toUpperCase() !== w.severity) return false;
    const q = S.q.trim().toLowerCase();
    if (q && !`${r.plate_norm || ''} ${r.reason || ''} ${r.category || ''}`.toLowerCase().includes(q)) return false;
    return true;
  });
  const cur = vis.find((r) => r.id === w.sel) || vis[0] || null;
  const cnt = (k) => rows.filter((r) => k === 'all' || (r.severity || '').toUpperCase() === k).length;
  const cols = '132px 132px 92px 1fr 118px 96px';

  return `
  <div class="filters">
    ${searchField('plate or reason')}
    <div class="seg">${['all', 'CRITICAL', 'HIGH', 'MEDIUM'].map((k) =>
      `<button data-wsev="${k}" class="${w.severity === k ? 'on' : ''}">
        ${k === 'all' ? 'All' : k[0] + k.slice(1).toLowerCase()}<span class="n">${cnt(k)}</span></button>`).join('')}</div>
    <div class="grow"></div>
    <span class="mono" style="font-size:12px;color:var(--dim)">${vis.length} of ${rows.length} entries</span>
    <button class="btn" id="watchReload">${svg(I.reset, 13, '#9BB0B2', 2)} Reload</button>
  </div>

  <div class="body">
    <div class="grow" style="display:flex;flex-direction:column;min-width:0;background:var(--void)">
      <div style="display:grid;grid-template-columns:${cols};padding:0 20px;height:36px;align-items:center;border-bottom:1px solid var(--line);background:#0E181C;flex:none">
        ${['Plate', 'Category', 'Severity', 'Reason', 'Class', 'Valid to'].map((h) => `<span class="lbl">${h}</span>`).join('')}
      </div>
      <div class="scroll">
        ${w.error ? `<div class="empty" style="color:var(--coral)">${esc(w.error)}</div>` : ''}
        ${!w.error && w.rows === null ? '<div class="empty">Loading…</div>' : ''}
        ${!w.error && w.rows && vis.length === 0 ? `<div class="empty">${rows.length === 0 ? 'The watchlist is empty. Add an entry or import a CSV.' : 'No entry matches this filter.'}</div>` : ''}
        ${vis.map((r) => {
          const sev = (r.severity || 'MEDIUM').toUpperCase();
          return `<div class="row ${cur && cur.id === r.id ? 'on' : ''}" data-watch="${r.id}" style="display:grid;grid-template-columns:${cols};padding:0 20px;height:52px;gap:0">
            <span class="mono" style="font-size:13.5px;letter-spacing:.04em">${esc(r.plate_norm || '—')}</span>
            <span style="font-size:12.5px;color:var(--dim)">${esc((r.category || '').replace(/_/g, ' '))}</span>
            <span style="display:flex;align-items:center;gap:7px"><span class="sq" style="background:${SEVCOL[sev]}"></span><span class="mono" style="font-size:11px;color:${SEVCOL[sev]}">${sev}</span></span>
            <span style="font-size:12.5px;color:#C6D5D5;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding-right:18px">${esc(r.reason || '—')}</span>
            <span class="mono" style="font-size:11px;color:${r.classification === 'SECRET' ? 'var(--coral)' : r.classification === 'CONFIDENTIAL' ? 'var(--amber)' : 'var(--dim)'}">${esc(r.classification || '—')}</span>
            <span class="mono" style="font-size:11.5px;color:var(--dim)">${esc(String(r.valid_until || '—').slice(0, 10))}</span>
          </div>`;
        }).join('')}
      </div>
    </div>

    <aside class="pane right wide">
      <div class="scroll">
        ${cur ? `
        <div style="padding:18px">
          <span class="plate lg">${esc(cur.plate_norm || '—')}</span>
          <div style="display:flex;align-items:center;gap:9px;margin-top:12px">
            <span class="mono" style="display:flex;align-items:center;gap:6px;height:24px;padding:0 10px;border-radius:4px;background:${SEVCOL[(cur.severity || 'MEDIUM').toUpperCase()]}1F;font-size:10.5px;color:${SEVCOL[(cur.severity || 'MEDIUM').toUpperCase()]}">
              <span class="sq" style="background:${SEVCOL[(cur.severity || 'MEDIUM').toUpperCase()]}"></span>${esc((cur.severity || '').toUpperCase())}</span>
            <span class="mono" style="font-size:10.5px;color:var(--amber)">${esc(cur.classification || '')}</span>
          </div>
          <div style="margin-top:14px;font-size:13.5px;line-height:1.55;color:#C6D5D5">${esc(cur.reason || '—')}</div>
        </div>
        <div style="padding:0 18px 18px">
          <div class="kv">
            <div><div class="k">Canonical form</div><div class="v" style="color:var(--violet)">${esc(cur.plate_canon || '—')}</div></div>
            <div><div class="k">Category</div><div class="v" style="font-family:var(--sans);font-size:12.5px">${esc((cur.category || '').replace(/_/g, ' '))}</div></div>
            <div><div class="k">Valid from</div><div class="v">${esc(String(cur.valid_from || '—').slice(0, 10))}</div></div>
            <div><div class="k">Valid until</div><div class="v">${esc(String(cur.valid_until || '—').slice(0, 10))}</div></div>
            <div><div class="k">Source</div><div class="v" style="font-family:var(--sans);font-size:12.5px">${esc(cur.source || '—')}</div></div>
            <div><div class="k">Kind</div><div class="v" style="font-family:var(--sans);font-size:12.5px">${esc(cur.kind || '—')}</div></div>
          </div>
          <div style="margin-top:12px;font-size:11.5px;line-height:1.5;color:var(--faint)">
            The canonical form collapses every confusion class, so a read of 6J01A81234 still matches this entry.
          </div>
        </div>
        <div style="padding:0 18px 18px;display:flex;flex-direction:column;gap:8px">
          <button class="btn" data-trace-plate="${esc(cur.plate_norm || '')}" style="height:36px;justify-content:flex-start">${svg(I.trace, 14, '#B08CF5', 1.9)} Trace this plate</button>
        </div>` : '<div class="empty">No entry selected.</div>'}
      </div>
    </aside>
  </div>`;
}

/* ── view: admin ────────────────────────────────────────────────── */

function viewAdmin() {
  const ad = S.admin;
  const c = counts();
  const unplaced = S.cameras.filter((x) => !placed(x)).length;
  const drivers = {};
  S.cameras.forEach((x) => { const d = x.driver || 'unknown'; drivers[d] = (drivers[d] || 0) + 1; });

  const tab = (k, label) =>
    `<button data-tab="${k}" style="display:flex;align-items:center;height:48px;padding:0 4px;margin-right:22px;border-bottom:2px solid ${ad.tab === k ? 'var(--amber)' : 'transparent'};color:${ad.tab === k ? 'var(--ink)' : 'var(--faint)'};font-size:13.5px;font-weight:500;cursor:pointer">${label}</button>`;

  let panel = '';
  if (ad.tab === 'health') {
    const rows = S.cameras.slice().sort((a, b) => {
      const rank = { DOWN: 0, DEGRADED: 1, CONNECTING: 1, LIVE: 2, READY: 3 };
      return (rank[health(a)] ?? 4) - (rank[health(b)] ?? 4) || Number(a.camera_id) - Number(b.camera_id);
    });
    const gc = '64px 1fr 140px 110px 120px 110px';
    panel = `
      <div style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px">
        ${[['Live or ready', c.LIVE, 'of ' + c.all, 'var(--jade)'],
           ['Degraded', c.DEGRADED, 'stale or connecting', 'var(--amber)'],
           ['Down', c.DOWN, 'unreachable at the grid', 'var(--coral)'],
           ['Unplaced', unplaced, 'no coordinate', 'var(--violet)']].map(([l, v, s, col]) =>
          `<div class="card" style="padding:18px 20px">
            <div class="lbl">${l}</div>
            <div style="display:flex;align-items:baseline;gap:8px;margin-top:8px">
              <span style="font-family:var(--display);font-weight:700;font-size:30px;color:${col};line-height:1">${v}</span>
              <span style="font-size:12.5px;color:var(--faint)">${s}</span>
            </div>
          </div>`).join('')}
      </div>
      <div style="display:flex;align-items:center;justify-content:space-between;margin:26px 0 12px">
        <span class="lbl">Camera health — all ${S.cameras.length}</span>
      </div>
      <div class="card" style="overflow:hidden">
        <div style="display:grid;grid-template-columns:${gc};padding:0 16px;height:32px;align-items:center;background:#0E181C;border-bottom:1px solid var(--line)">
          ${['Cam', 'Name', 'District', 'Driver', 'Status', 'Frame age'].map((h) => `<span class="lbl">${h}</span>`).join('')}
        </div>
        ${rows.map((x) => {
          const h = health(x); const w = S.wall[x.camera_id] || {};
          return `<div style="display:grid;grid-template-columns:${gc};padding:0 16px;height:38px;align-items:center;border-bottom:1px solid #182429">
            <span class="mono" style="font-size:11.5px;color:var(--faint)">${esc(x.camera_id)}</span>
            <span style="font-size:12.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(camName(x))}</span>
            <span style="font-size:11.5px;color:var(--faint)">${esc(x.district_code || 'UNKNOWN')}</span>
            <span class="mono" style="font-size:11px;color:var(--dim)">${esc(x.driver || '—')}</span>
            <span style="display:flex;align-items:center;gap:7px"><span class="sq" style="border-radius:50%;background:${hcol(h)}"></span><span class="mono" style="font-size:11px;color:${hcol(h)}">${h}</span></span>
            <span class="mono" style="font-size:11px;color:var(--faint)">${w.age_s == null ? '—' : w.age_s.toFixed(1) + ' s'}</span>
          </div>`;
        }).join('')}
      </div>`;
  } else if (ad.tab === 'drivers') {
    const notes = {
      mediamtx: 'The grid’s own registered driver for these cameras. The console’s wall pulls them over RTSP directly against the grid’s public IP (port 8554, no session needed) with HLS through this driver as the fallback when 8554 is blocked outbound.',
      rtsp: 'PyAV over rtsp_transport=tcp, direct to the grid’s public static IP. This is what the video wall actually uses — all 30 cameras open over it, no key or session required.',
      onvif: 'WS-Discovery and GetStreamUri are implemented. No ONVIF camera is present in this grid to exercise it against.',
      vms: 'STUB. The interface is complete and typed; list_cameras, get_stream_uri and subscribe_events return mock rows while vendor credentials are pending.',
    };
    const all = Object.assign({ mediamtx: 0, rtsp: 0, onvif: 0, vms: 0 }, drivers);
    panel = `<div class="lbl" style="margin-bottom:14px">Transport drivers</div>
      <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px">
        ${Object.keys(all).map((d) => {
          const stub = d === 'vms';
          return `<div class="card" style="padding:20px 22px">
            <div style="display:flex;align-items:center;justify-content:space-between">
              <span style="font-family:var(--display);font-weight:700;font-size:17px">${esc(d)}</span>
              <span style="display:flex;align-items:center;gap:7px;padding:4px 11px;border-radius:999px;background:${stub ? 'var(--amber-soft)' : 'var(--jade-soft)'}">
                <span class="sq" style="border-radius:50%;background:${stub ? 'var(--amber)' : 'var(--jade)'}"></span>
                <span class="mono" style="font-size:11px;color:${stub ? 'var(--amber)' : 'var(--jade)'}">${stub ? 'stub' : 'live'}</span></span>
            </div>
            <div style="display:flex;align-items:baseline;gap:8px;margin-top:14px">
              <span style="font-family:var(--display);font-weight:700;font-size:26px">${all[d]}</span>
              <span style="font-size:12.5px;color:var(--faint)">cameras assigned to this driver</span>
            </div>
            <div style="margin-top:12px;font-size:12.5px;line-height:1.55;color:var(--dim)">${esc(notes[d] || '')}</div>
          </div>`;
        }).join('')}
      </div>`;
  } else {
    const rows = ad.audit || [];
    panel = `
      <div class="card" style="display:flex;align-items:center;gap:16px;padding:18px 20px;margin-bottom:20px;border-color:${ad.verified === false ? '#FF6B5A55' : ad.verified ? '#3FD2A455' : 'var(--line)'};background:${ad.verified === false ? 'var(--coral-soft)' : ad.verified ? 'var(--jade-soft)' : 'var(--surface)'}">
        <span style="display:flex;align-items:center;justify-content:center;width:42px;height:42px;border-radius:50%;background:${ad.verified === false ? '#FF6B5A29' : '#3FD2A429'};flex:none">
          ${svg(ad.verified === false ? I.warn : I.chain, 21, ad.verified === false ? '#FF6B5A' : '#3FD2A4', 1.9)}
        </span>
        <div class="grow">
          <div style="font-size:15px;font-weight:600;color:${ad.verified === false ? 'var(--coral)' : ad.verified ? 'var(--jade)' : 'var(--ink)'}">
            ${ad.verifying ? 'Re-hashing the chain…' : ad.verified === true ? 'Chain verified end to end. No broken link.'
              : ad.verified === false ? 'Chain verification failed.' : 'Audit chain'}
          </div>
          <div style="font-size:12.5px;color:var(--dim);margin-top:3px">
            ${ad.verifyNote ? esc(ad.verifyNote) : 'Every read, transition, grant and export appends to one hash chain. Ask the API to recompute it.'}
          </div>
        </div>
        <button class="btn primary tall" id="verifyChain" ${ad.verifying ? 'disabled' : ''}>${svg(I.reset, 14, '#0B1316', 2.2)} Verify chain</button>
      </div>
      <div class="lbl" style="margin-bottom:12px">Recent audit entries</div>
      <div class="card" style="overflow:hidden">
        ${ad.error ? `<div class="empty" style="color:var(--coral)">${esc(ad.error)}</div>` : ''}
        ${!ad.error && ad.audit === null ? '<div class="empty">Loading…</div>' : ''}
        ${!ad.error && rows.length === 0 && ad.audit !== null ? '<div class="empty">No audit entry yet.</div>' : ''}
        ${rows.map((e) => `<div style="display:flex;gap:14px;padding:12px 16px;border-bottom:1px solid #182429;align-items:center">
          <span class="mono" style="font-size:11px;color:var(--ghost);width:150px;flex:none">${esc(String(e.at || e.created_at || '').replace('T', ' ').slice(0, 19))}</span>
          <span class="mono" style="font-size:11px;color:var(--amber);width:170px;flex:none">${esc(e.action || '—')}</span>
          <span class="grow" style="font-size:12.5px;color:#C6D5D5">${esc(e.object_type || '')} ${esc(e.object_id ?? '')} ${esc(e.reason || '')}</span>
          <span class="mono" style="font-size:10.5px;color:var(--ghost);flex:none">${esc(String(e.hash || e.row_hash || '').slice(0, 7))}</span>
        </div>`).join('')}
      </div>`;
  }

  return `
  <div class="filters" style="height:48px;gap:0">
    ${tab('health', 'Camera health')}${tab('drivers', 'Transport drivers')}${tab('audit', 'Audit log')}
    <div class="grow"></div>
    <span class="mono" style="font-size:11.5px;color:var(--faint)">grid polled every 2 s</span>
  </div>
  <div class="body"><div class="scroll grow" style="padding:20px 24px">${panel}</div></div>`;
}

/* ── render + wiring ────────────────────────────────────────────── */

// Video is the first thing anyone checks, so when it cannot work the reason is
// stated at the top of every view instead of being left to thirty idle tiles.
// RTSP is the wall's primary transport and needs no session at all -- only
// the HLS fallback needs GRID_KEY. So a missing key is no longer "video is
// unavailable": it only means the network's own port 8554 is the one thing
// standing between the operator and a picture. Judge that from what the wall
// is actually doing, not from grid sign-in state alone.
function gridBanner() {
  const g = S.grid;
  const wallVals = Object.values(S.wall);
  const anyLive = wallVals.some((w) => w.has_frame);
  const anyTried = wallVals.some((w) => w.status && w.status !== 'idle' && w.status !== 'stopped');
  if (anyLive) return '';               // real video is flowing -- nothing to say

  if (anyTried) {
    // The wall has been started and nothing is coming through on either
    // transport -- that is a real, specific problem, most likely port 8554
    // blocked outbound on this network with HLS also gated.
    return `<div class="banner bad">
      ${svg(I.warn, 16, '#FF6B5A', 1.9)}
      <div class="grow" style="font-size:13px;color:#FFB4A8">
        <b style="font-weight:600">No feed is delivering a frame.</b> RTSP (port 8554 to the grid's public IP) needs no key
        and is the primary transport, but every attempt is retrying. If this network blocks outbound 8554, the HLS
        fallback still needs a signed-in session${g && g.state !== 'signed in' ? ' — currently ' + esc(g.state) + '.' : '.'}
      </div>
    </div>`;
  }

  if (!g || g.state === 'signed in') return '';
  // Nothing has been tried yet: say what the wall will use, without implying
  // it is blocked -- RTSP works before any key exists.
  const bad = g.state === 'rejected' || g.state === 'unreachable';
  return `<div class="banner warn">
    ${svg(I.warn, 16, '#F2A93B', 1.9)}
    <div class="grow" style="font-size:13px;color:#F4D6A2">
      <b style="font-weight:600">HLS fallback not signed in.</b> The primary transport is RTSP, which needs no key —
      press Start wall to pull real frames. ${bad ? 'The HLS fallback specifically: ' + esc(g.detail || g.state) + '.' : ''}
    </div>
  </div>`;
}

const TITLES = {
  map: ['Live map', 'grid overview'], wall: ['Video wall', 'feeds'],
  trace: ['Route trace', 'vehicle history'], alerts: ['Alerts', 'triage queue'],
  watchlist: ['Watchlist', 'plates of interest'], admin: ['Grid admin', 'health, drivers, audit'],
};

function render(opts) {
  const root = $('#views');
  const [t, sub] = TITLES[S.view] || TITLES.map;
  $('#viewTitle').textContent = t;
  $('#viewSub').textContent = sub;
  document.querySelectorAll('.rail a').forEach((a) => a.classList.toggle('on', a.dataset.nav === S.view));

  const c = counts();
  $('#healthPill').textContent = `${c.LIVE}/${c.all} live`;
  paintBadge();

  const html = { map: viewMap, wall: viewWall, trace: viewTrace, alerts: viewAlerts, watchlist: viewWatchlist, admin: viewAdmin }[S.view]();
  root.innerHTML = gridBanner() + html;
  root.style.cssText = 'flex:1 1 auto;display:flex;flex-direction:column;min-height:0';
  wire(root);

  if (opts && opts.keepFocus) {
    const el = $(opts.keepFocus, root);
    if (el) { el.focus(); if (opts.caret != null) el.setSelectionRange(opts.caret, opts.caret); }
  }
}

function wire(root) {
  wireFilters(root);

  // Re-parent the persistent Leaflet container into the freshly rendered
  // wrapper, then let it re-measure. Creating it here rather than in the
  // markup is what keeps tiles from refetching on every keystroke.
  const wrap = $('#mapWrap', root);
  const twrap = $('#traceMapWrap', root);
  if ((wrap || twrap) && !HAVE_LEAFLET) {
    (wrap || twrap).insertAdjacentHTML('afterbegin',
      `<div class="empty" style="position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px">
        ${svg(I.warn, 26, '#FF6B5A', 1.6)}
        <div style="color:var(--coral);font-size:14px">The map library did not load.</div>
        <div class="mono" style="font-size:11.5px">web/vendor/leaflet.js is missing or failed to parse</div>
      </div>`);
  }
  if (wrap && HAVE_LEAFLET) {
    const m = mapHost('grid');
    wrap.insertBefore(m.host, wrap.firstChild);
    ensureMap('grid', (mm) => paintMap(mm));
  }
  if (twrap && HAVE_LEAFLET) {
    const m = mapHost('trace');
    twrap.insertBefore(m.host, twrap.firstChild);
    ensureMap('trace', (mm) => paintTrace(mm));
  }
  root.querySelectorAll('[data-base]').forEach((el) =>
    el.addEventListener('click', () => { setBasemap(el.dataset.base); render(); }));
  const fit = $('#fitBtn', root);
  if (fit) fit.addEventListener('click', () => { S.fitPending = true; ensureMap('grid', (mm) => paintMap(mm)); });

  root.querySelectorAll('[data-cam]').forEach((el) =>
    el.addEventListener('click', () => selectCamera(el.dataset.cam)));

  root.querySelectorAll('[data-layer]').forEach((el) =>
    el.addEventListener('click', () => { S.layers[el.dataset.layer] = !S.layers[el.dataset.layer]; render(); }));

  root.querySelectorAll('[data-cols]').forEach((el) =>
    el.addEventListener('click', () => { S.cols = Number(el.dataset.cols); render(); }));

  const ft = $('#focusToggle', root);
  if (ft) ft.addEventListener('click', () => { S.focus = !S.focus; render(); });

  root.querySelectorAll('[data-goto-map]').forEach((el) =>
    el.addEventListener('click', (e) => { e.stopPropagation(); S.sel = el.dataset.gotoMap; go('map'); }));
  root.querySelectorAll('[data-goto-wall]').forEach((el) =>
    el.addEventListener('click', (e) => { e.stopPropagation(); S.sel = el.dataset.gotoWall; go('wall'); }));
  root.querySelectorAll('[data-trace-plate]').forEach((el) =>
    el.addEventListener('click', (e) => {
      e.stopPropagation();
      const p = el.dataset.tracePlate;
      if (!p) return toast('That alert carries no plate to trace.', 'var(--amber)');
      S.trace.plate = p; go('trace'); runTrace();
    }));

  root.querySelectorAll('[data-pull]').forEach((el) =>
    el.addEventListener('click', async (e) => {
      e.stopPropagation();
      const id = el.dataset.pull;
      const running = (S.wall[id] || {}).status === 'running';
      try {
        await postJSON(`/api/wall/${running ? 'stop' : 'start'}`, { ids: [id] });
        toast(running ? `Stopped camera ${id}` : `Pulling camera ${id}`);
        pollWall();
      } catch (err) { toast(String(err.message || err), 'var(--coral)'); }
    }));

  const ws = $('#wallStart', root), wx = $('#wallStop', root);
  if (ws) ws.addEventListener('click', async () => {
    try { await postJSON('/api/wall/start', {}); toast('Wall starting — frames appear as each camera connects'); pollWall(); }
    catch (e) { toast(String(e.message || e), 'var(--coral)'); }
  });
  if (wx) wx.addEventListener('click', async () => {
    try { await postJSON('/api/wall/stop', {}); toast('Wall stopped'); pollWall(); }
    catch (e) { toast(String(e.message || e), 'var(--coral)'); }
  });

  // trace
  const tp = $('#tracePlate', root);
  if (tp) {
    tp.addEventListener('input', (e) => {
      S.trace.plate = e.target.value.toUpperCase();
      e.target.value = S.trace.plate;
      // Toggle the button directly rather than calling render(): a full
      // re-render here would rebuild the input mid-keystroke and drop focus.
      const go = $('#traceGo', root);
      if (go) go.disabled = !S.trace.plate.trim();
    });
    tp.addEventListener('keydown', (e) => { if (e.key === 'Enter' && S.trace.plate.trim()) runTrace(); });
  }
  const tg = $('#traceGo', root);
  if (tg) tg.addEventListener('click', runTrace);
  const pt = $('#probToggle', root);
  if (pt) pt.addEventListener('click', () => { S.trace.probable = !S.trace.probable; render(); });
  root.querySelectorAll('[data-hop]').forEach((el) =>
    el.addEventListener('click', () => { S.trace.sel = Number(el.dataset.hop); render(); }));
  const tc = $('#traceCsv', root);
  if (tc) tc.addEventListener('click', downloadTraceCsv);

  // alerts
  root.querySelectorAll('[data-sev]').forEach((el) =>
    el.addEventListener('click', () => { S.alerts.severity = el.dataset.sev; render(); }));
  root.querySelectorAll('[data-astate]').forEach((el) =>
    el.addEventListener('click', () => { S.alerts.state = el.dataset.astate; render(); }));
  root.querySelectorAll('[data-alert]').forEach((el) =>
    el.addEventListener('click', () => { S.alerts.sel = Number(el.dataset.alert); render(); }));
  root.querySelectorAll('[data-act]').forEach((el) =>
    el.addEventListener('click', () => transition(Number(el.dataset.id), el.dataset.act)));
  const ar = $('#alertsReload', root);
  if (ar) ar.addEventListener('click', loadAlerts);

  // watchlist
  root.querySelectorAll('[data-wsev]').forEach((el) =>
    el.addEventListener('click', () => { S.watch.severity = el.dataset.wsev; render(); }));
  root.querySelectorAll('[data-watch]').forEach((el) =>
    el.addEventListener('click', () => { S.watch.sel = Number(el.dataset.watch); render(); }));
  const wr = $('#watchReload', root);
  if (wr) wr.addEventListener('click', loadWatchlist);

  // admin
  root.querySelectorAll('[data-tab]').forEach((el) =>
    el.addEventListener('click', () => {
      S.admin.tab = el.dataset.tab; render();
      if (S.admin.tab === 'audit' && S.admin.audit === null) loadAudit();
    }));
  const vc = $('#verifyChain', root);
  if (vc) vc.addEventListener('click', verifyChain);
}

/* ── data ───────────────────────────────────────────────────────── */

async function loadCameras() {
  try {
    const out = await getJSON('/api/cameras');
    // An error object here instead of a list used to take the whole console
    // down inside counts(); the camera list is the one thing every view reads.
    if (!Array.isArray(out)) throw new Error('camera list was not a list');
    S.cameras = out;
    if (!S.sel && S.cameras.length) S.sel = S.cameras[0].camera_id;
  } catch (e) {
    S.cameras = [];
    toast('Could not load cameras: ' + e.message, 'var(--coral)');
  }
}

async function pollWall() {
  try {
    const w = await getJSON('/api/wall');
    S.wall = {};
    (w.cameras || []).forEach((c) => { S.wall[c.camera_id] = c; });
    S.wallRunning = w.running || 0;
    S.frameStamp = Date.now();
    refreshLive();
  } catch (e) { /* the wall is optional; the rest of the console still works */ }
}

/* A poll must never rebuild the map view. render() replaces the whole of
 * #views, which rips the Leaflet container out of the document and re-parents
 * it — doing that every two seconds is what left the map dead on screen. So
 * the map view is refreshed surgically: the camera list is its own node, and
 * the markers are redrawn on the existing map. Views with no map can take the
 * cheap path and re-render wholesale. */
// Picking a camera from the list (map view) or a tile (wall view) sets the
// selection; on the map, it also flies the view there when the camera isn't
// already on screen, so scrolling the list actually shows you where you are.
function selectCamera(id) {
  S.sel = id;
  if (S.view === 'map') {
    const m = MAPS.grid;
    const cam = S.cameras.find((c) => c.camera_id === id);
    if (m && m.map && cam && placed(cam)) {
      const target = [cam.geo.lat, cam.geo.lon];
      if (!m.map.getBounds().pad(-0.1).contains(target)) {
        m.map.flyTo(target, Math.max(m.map.getZoom(), 12), { duration: 0.6 });
      }
    }
  }
  render();
}

function refreshLive() {
  const c = counts();
  const pill = $('#healthPill');
  if (pill) pill.textContent = `${c.LIVE}/${c.all} live`;

  if (S.view === 'map') {
    const list = $('#camList');
    if (list) {
      const scrolled = list.scrollTop;
      list.innerHTML = cameraListHTML();
      list.scrollTop = scrolled;              // keep the operator's place
      list.querySelectorAll('[data-cam]').forEach((el) =>
        el.addEventListener('click', () => selectCamera(el.dataset.cam)));
    }
    const m = MAPS.grid;
    if (m && m.map) paintMap(m);
    return;
  }
  if (S.view === 'wall' || (S.view === 'admin' && S.admin.tab === 'health')) render();
}

function paintBadge() {
  const badge = $('#alertBadge');
  if (!badge) return;
  const open = (S.alerts.rows || []).filter((r) => (r.state || '').toUpperCase() === 'NEW').length;
  badge.style.display = open ? 'flex' : 'none';
  badge.textContent = open;
}

/* Alerts were loaded once, at boot. A console left open through a shift then
 * showed the alerts that existed when the page loaded and nothing since -- the
 * one thing an operator is watching for is the one thing that never arrived.
 * Poll, but re-render only when the answer actually changed, and never pull the
 * cursor out of a field someone is typing in: a plate half-entered in Trace and
 * silently reset is its own kind of wrong answer. */
async function pollAlerts() {
  let rows;
  try {
    rows = await getJSON('/api/v1/alerts');
  } catch (e) {
    return;                       // keep the last good list rather than blanking it
  }
  if (!Array.isArray(rows)) return;
  const stamp = (list) => (list || []).map((r) => `${r.id}:${r.state}`).join(',');
  if (stamp(rows) === stamp(S.alerts.rows)) return;
  S.alerts.rows = rows;
  S.alerts.error = null;
  const typing = document.activeElement && /^(INPUT|TEXTAREA)$/.test(document.activeElement.tagName);
  if (typing && S.view !== 'alerts') { paintBadge(); return; }
  render();
}

async function loadAlerts() {
  S.alerts.error = null;
  try {
    const rows = await getJSON('/api/v1/alerts');
    S.alerts.rows = Array.isArray(rows) ? rows : [];
  } catch (e) {
    S.alerts.rows = [];
    S.alerts.error = 'Alerts unavailable: ' + e.message;
  }
  // Always render, not only on the alerts view: the sidebar's open-alert
  // badge is visible everywhere and must not go stale while the operator is
  // on another screen.
  render();
}

async function loadWatchlist() {
  S.watch.error = null;
  try {
    const rows = await getJSON('/api/v1/watchlist');
    S.watch.rows = Array.isArray(rows) ? rows : [];
    // Seed the trace box from a plate that is actually being watched, rather
    // than shipping a example plate baked into the page.
    if (!S.trace.plate && S.watch.rows.length) S.trace.plate = S.watch.rows[0].plate_norm || '';
  } catch (e) {
    S.watch.rows = [];
    S.watch.error = 'Watchlist unavailable: ' + e.message;
  }
  // Always render: this call now runs once at boot regardless of which view
  // is open, and the seeded trace plate must reach the Trace screen even
  // when the operator opened it directly rather than via Watchlist.
  render();
}

async function loadAudit() {
  S.admin.error = null;
  try {
    const out = await getJSON('/api/v1/admin/audit?limit=40');
    S.admin.audit = Array.isArray(out) ? out : (out.rows || []);
  } catch (e) {
    S.admin.audit = [];
    S.admin.error = 'Audit log unavailable: ' + e.message;
  }
  if (S.view === 'admin') render();
}

async function verifyChain() {
  S.admin.verifying = true; S.admin.verifyNote = null; render();
  try {
    const out = await getJSON('/api/v1/admin/audit/verify');
    const ok = out.ok === true || out.valid === true;
    S.admin.verified = ok;
    S.admin.verifyNote = ok
      ? `${out.checked ?? out.count ?? 'all'} entries re-hashed clean.`
      : `First broken link at entry ${out.broken_at ?? out.first_bad ?? 'unknown'}.`;
  } catch (e) {
    S.admin.verified = null;
    S.admin.verifyNote = 'Could not run verification: ' + e.message;
  }
  S.admin.verifying = false;
  render();
}

async function runTrace() {
  const plate = (S.trace.plate || '').trim().toUpperCase();
  if (!plate) return toast('Enter a plate first.', 'var(--amber)');
  S.trace.loading = true; S.trace.error = null; render();
  try {
    S.trace.data = await getJSON(`/api/v1/route?plate=${encodeURIComponent(plate)}`);
    S.trace.sel = (S.trace.data.hops && S.trace.data.hops[0]) ? S.trace.data.hops[0].n : null;
    S.traceFit = true;   // frame the route once, then leave the view alone
    if (!S.trace.data.hops || !S.trace.data.hops.length) toast('No sighting of that plate in the window.', 'var(--amber)');
  } catch (e) {
    S.trace.data = null;
    S.trace.error = 'Trace failed: ' + e.message;
  }
  S.trace.loading = false;
  render();
}

function downloadTraceCsv() {
  const hops = (S.trace.data && S.trace.data.hops) || [];
  if (!hops.length) return;
  const head = ['n', 'camera_id', 'name', 'lat', 'lon', 'pts', 'kind', 'band', 'implied_speed_kmh', 'flag'];
  const lines = [head.join(',')].concat(hops.map((h) =>
    head.map((k) => {
      const v = h[k];
      return v == null ? '' : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v);
    }).join(',')));
  const blob = new Blob([lines.join('\n')], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `prahari-trace-${S.trace.plate}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
  toast('Trace exported. The export itself is on the audit chain.');
}

async function transition(id, to) {
  try {
    await postJSON(`/api/v1/alerts/${id}/state`, { to_state: to, reason: 'from the console' });
    toast(`Alert #${id} → ${to}`);
    await loadAlerts();
  } catch (e) { toast('Transition refused: ' + e.message, 'var(--coral)'); }
}

/* ── routing ────────────────────────────────────────────────────── */

const VIEWS = ['map', 'wall', 'trace', 'alerts', 'watchlist', 'admin'];

function go(v) {
  if (!VIEWS.includes(v)) v = 'map';
  S.view = v;
  if (location.hash.slice(1) !== v) location.hash = v;
  render();
  if (v === 'alerts' && S.alerts.rows === null) loadAlerts();
  if (v === 'watchlist' && S.watch.rows === null) loadWatchlist();
  if (v === 'admin' && S.admin.tab === 'audit' && S.admin.audit === null) loadAudit();
}

window.addEventListener('hashchange', () => go(location.hash.slice(1) || 'map'));

// Keyboard: g/w/t/a/k/d jump between views, / focuses search, Escape clears it.
const KEYNAV = { g: 'map', w: 'wall', t: 'trace', a: 'alerts', k: 'watchlist', d: 'admin' };
document.addEventListener('keydown', (e) => {
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
  if (e.key === '/' && !typing) { e.preventDefault(); $('#globalSearch').focus(); return; }
  if (e.key === 'Escape') {
    if (S.q) { S.q = ''; render(); }
    document.activeElement.blur();
    return;
  }
  if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
  const v = KEYNAV[e.key.toLowerCase()];
  if (v) { e.preventDefault(); go(v); }
});
$('#globalSearch').addEventListener('input', (e) => {
  S.q = e.target.value;
  render();
  const g = $('#globalSearch'); g.focus();
  g.setSelectionRange(g.value.length, g.value.length);
});

async function loadGrid() {
  try { S.grid = await getJSON('/api/grid'); } catch (e) { S.grid = null; }
}

(async function start() {
  await Promise.all([loadCameras(), loadGrid()]);
  go(location.hash.slice(1) || 'map');
  loadAlerts();
  // Loading this only when the user opened Watchlist first left Trace's plate
  // field permanently empty for anyone who opened Trace directly — the box
  // showed its placeholder text, which reads exactly like a real value at a
  // glance, so "Trace" appeared to do nothing. Load it at boot instead.
  loadWatchlist();
  pollWall();
  setInterval(pollWall, 2000);
  setInterval(pollAlerts, 5000);
})();
