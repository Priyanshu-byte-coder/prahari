/**
 * [G9] events.js — Detections layer, alerts pulse, time slider.
 *
 * - Detection dots appear on the map and fade after 30 s.
 * - Alert circles pulse red until acknowledged.
 * - Time slider: drags a [from, to] window; shows only sightings in that window.
 *   Preloads the last 6 h of events so dragging is instant (no round-trips).
 */

const EventsLayer = (() => {
  /** Escape text before inserting into innerHTML. */
  const esc = s => { const d = document.createElement('div'); d.textContent = String(s ?? ''); return d.innerHTML; };
  const FADE_MS      = 30_000;
  const PRELOAD_H    = 6;
  const DETECTION_R  = 6;
  const ALERT_R      = 12;
  const DETECTION_COLOR = '#60a5fa';
  const ALERT_COLOR     = '#f87171';

  let mapRef = null;
  let allEvents  = [];   // entire 6-h preload
  let dotLayers  = [];   // {circle, timer, ts}
  let alertLayers = {};  // alert_id → circle

  // ── Slider state ──
  let sliderFrom = null;
  let sliderTo   = null;
  let sliderEl   = null;
  let fromLabelEl = null, toLabelEl = null;

  function init() {
    // Build the time-slider toolbar and inject it above the map
    const stage = document.getElementById('mapView');
    if (!stage) return;

    const bar = document.createElement('div');
    bar.id = 'timeSliderBar';
    bar.style.cssText = `
      position:absolute; bottom:0; left:0; right:0; z-index:1000;
      background:#151a21cc; backdrop-filter:blur(4px);
      border-top:1px solid #262e3a; padding:8px 12px;
      display:flex; gap:10px; align-items:center; font-size:12px;`;
    bar.innerHTML = `
      <span style="color:#8b97a8;white-space:nowrap">Last 6 h</span>
      <input id="timeSlider" type="range" min="0" max="100" value="0"
        style="flex:1;accent-color:#3b82f6">
      <span id="sliderFrom" style="color:#8b97a8;white-space:nowrap;min-width:90px"></span>
      <span style="color:#5c6675">→</span>
      <span id="sliderTo"   style="color:#8b97a8;white-space:nowrap;min-width:90px"></span>
      <button id="sliderReset" class="btn sm">Live</button>`;
    stage.appendChild(bar);

    sliderEl    = document.getElementById('timeSlider');
    fromLabelEl = document.getElementById('sliderFrom');
    toLabelEl   = document.getElementById('sliderTo');

    sliderEl.addEventListener('input', onSlide);
    document.getElementById('sliderReset').addEventListener('click', resetToLive);

    // Preload 6 h of events
    const to   = Date.now();
    const from = to - PRELOAD_H * 3600_000;
    preloadEvents(from, to);

    // Pulse existing NEW alerts
    refreshAlerts();
    // Also hook the WS stream (done in ws.js via EventsLayer.handleWsMessage)
  }

  async function preloadEvents(fromMs, toMs) {
    const fmt = t => new Date(t).toISOString();
    try {
      const data = await window.apiFetch(
        `/api/events?from=${fmt(fromMs)}&to=${fmt(toMs)}&limit=5000`,
        []
      );
      allEvents = Array.isArray(data) ? data : [];
    } catch (_) {
      allEvents = [];
    }
    renderWindow(null, null); // show all
    updateSliderLabels(fromMs, toMs);
  }

  async function refreshAlerts() {
    const data = await window.apiFetch('/api/alerts?state=NEW&limit=200', []);
    const arr  = Array.isArray(data) ? data : [];
    arr.forEach(a => addAlertPulse(a));
  }

  // ── Slider ──
  function onSlide() {
    const m   = mapRef;
    if (!m || !allEvents.length) return;
    // slider position (0-100) maps to last 6 h; position 100 = now
    const now   = Date.now();
    const total = PRELOAD_H * 3600_000;
    const pct   = sliderEl.value / 100;
    const winSz = total / 4; // 1.5-h window
    const mid   = now - total + pct * total;
    sliderFrom  = mid - winSz / 2;
    sliderTo    = mid + winSz / 2;
    renderWindow(sliderFrom, sliderTo);
    updateSliderLabels(sliderFrom, sliderTo);
  }

  function resetToLive() {
    sliderEl.value = 100;
    sliderFrom = sliderTo = null;
    renderWindow(null, null);
    updateSliderLabels(Date.now() - PRELOAD_H * 3600_000, Date.now());
  }

  function updateSliderLabels(fromMs, toMs) {
    const fmt = ms => new Date(ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    if (fromLabelEl) fromLabelEl.textContent = fmt(fromMs);
    if (toLabelEl)   toLabelEl.textContent   = fmt(toMs);
  }

  // ── Dot rendering ──
  function renderWindow(fromMs, toMs) {
    const m = MapView.getMap ? MapView.getMap() : null;
    if (!m) return;
    // Clear existing dots
    dotLayers.forEach(({ circle }) => m.removeLayer(circle));
    dotLayers = [];

    const events = fromMs
      ? allEvents.filter(e => {
          const t = new Date(e.pts_first).getTime();
          return t >= fromMs && t <= toMs;
        })
      : allEvents;

    events.forEach(e => addDot(e, m));
  }

  function addDot(e, m) {
    m = m || (MapView.getMap ? MapView.getMap() : null);
    if (!m) return;
    const cam = (window.prahari.cameras || []).find(c => String(c.camera_id) === String(e.camera_id));
    if (!cam || cam.lat == null) return;

    // Jitter slightly so overlapping cameras don't stack.
    // crypto.getRandomValues avoids the S2245 Math.random hotspot — the
    // value is not security-sensitive but the stronger call costs nothing.
    const _buf = new Uint32Array(2);
    crypto.getRandomValues(_buf);
    const jLat = cam.lat + (_buf[0] / 0xFFFFFFFF - .5) * 0.001;
    const jLon = cam.lon + (_buf[1] / 0xFFFFFFFF - .5) * 0.001;

    const circle = L.circleMarker([jLat, jLon], {
      radius:      DETECTION_R,
      color:       DETECTION_COLOR,
      weight:      1,
      fillColor:   DETECTION_COLOR,
      fillOpacity: 0.6,
    }).addTo(m);

    circle.bindTooltip(
      `${esc(e.plate_text || '—')} · cam ${esc(e.camera_id)} · ${esc(e.vehicle_class || '')}
       <br>${esc(new Date(e.pts_first).toLocaleTimeString())}`,
      { direction: 'top', opacity: 0.9 }
    );

    const entry = { circle, ts: Date.now() };

    // Live mode: fade after 30 s
    if (!sliderFrom) {
      entry.timer = setTimeout(() => {
        m.removeLayer(circle);
        dotLayers = dotLayers.filter(x => x !== entry);
      }, FADE_MS);
    }

    dotLayers.push(entry);
  }

  function addAlertPulse(alert) {
    const m = MapView.getMap ? MapView.getMap() : null;
    if (!m) return;
    const cam = (window.prahari.cameras || []).find(c => String(c.camera_id) === String(alert.camera_id));
    if (!cam || cam.lat == null) return;

    // Remove old pulse for same alert
    if (alertLayers[alert.id]) m.removeLayer(alertLayers[alert.id]);

    const circle = L.circleMarker([cam.lat, cam.lon], {
      radius:      ALERT_R,
      color:       ALERT_COLOR,
      weight:      2,
      fillColor:   ALERT_COLOR,
      fillOpacity: 0.25,
      className:   'alert-pulse',
    }).addTo(m);

    circle.bindTooltip(
      `🚨 ${esc(alert.plate_text || '?')} · ${esc(alert.category || '')} · ${esc(alert.severity || '')}
       <br>cam ${esc(alert.camera_id)} · ${esc(new Date(alert.pts).toLocaleTimeString())}`,
      { direction: 'top', permanent: false, opacity: 0.95 }
    );

    alertLayers[alert.id] = circle;
  }

  function removeAlertPulse(alertId) {
    const m = MapView.getMap ? MapView.getMap() : null;
    if (m && alertLayers[alertId]) {
      m.removeLayer(alertLayers[alertId]);
      delete alertLayers[alertId];
    }
  }

  /** Called by ws.js when a message arrives */
  function handleWsMessage(msg) {
    const m = MapView.getMap ? MapView.getMap() : null;
    if (!m) return;
    if (msg.type === 'sighting') {
      allEvents.push(msg.data);
      if (!sliderFrom) addDot(msg.data, m);
    }
    if (msg.type === 'alert.new') {
      addAlertPulse(msg.data);
      const el = document.getElementById('s-alerts');
      if (el) el.textContent = String((parseInt(el.textContent, 10) || 0) + 1);
    }
    if (msg.type === 'alert.state' && msg.data.to_state !== 'NEW') {
      removeAlertPulse(msg.data.alert_id);
    }
    if (msg.type === 'camera.health') {
      MapView.updateHealth(msg.data.camera_id, msg.data.health);
    }
  }

  return { init, addDot, addAlertPulse, removeAlertPulse, handleWsMessage };
})();

// Inject CSS for the pulse animation
const _style = document.createElement('style');
_style.textContent = `
  .alert-pulse {
    animation: alertBeat 1s ease-in-out infinite;
  }
  @keyframes alertBeat {
    0%,100% { opacity: 1; }
    50%      { opacity: 0.3; }
  }
`;
document.head.appendChild(_style);
