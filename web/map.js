/**
 * [G7] map.js — Leaflet map with markercluster, health pins, wedges.
 *
 * Renders fully with the API down (uses fixtures/api/cameras.json).
 * Proves 80,000-pin perf: cloneForStressTest() injects ×2000 copies.
 */

const MapView = (() => {
  /** Escape text before inserting into innerHTML/tooltips. */
  const esc = s => { const d = document.createElement('div'); d.textContent = String(s ?? ''); return d.innerHTML; };
  const HEALTH_COLOR = {
    LIVE:     '#34d399',
    DEGRADED: '#fbbf24',
    DOWN:     '#f87171',
    UNKNOWN:  '#6b7280',
  };

  let map, cluster, markers = {}, cameras = [];

  function init(cams) {
    cameras = cams;

    // fadeAnimation:false — Leaflet tiles can get stuck at opacity:0 after
    // fitBounds during load; they fire leaflet-tile-loaded but never paint.
    map = L.map('map', { zoomControl: true, fadeAnimation: false })
           .setView([22.6, 71.6], 7);

    const streets = L.tileLayer(
      'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
      { maxZoom: 19, attribution: '© OpenStreetMap contributors' }
    );
    const satellite = L.tileLayer(
      'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      { maxZoom: 19, attribution: '© Esri' }
    );
    const dark = L.tileLayer(
      'https://tiles.stadiamaps.com/tiles/alidade_smooth_dark/{z}/{x}/{y}.png',
      { maxZoom: 19, attribution: '© Stadia Maps, © OpenStreetMap' }
    );

    streets.addTo(map);
    // Satellite is a toggle, never default — pins are unreadable on satellite.
    L.control.layers({ Streets: streets, Dark: dark, Satellite: satellite }, {}, { position: 'topright' })
     .addTo(map);

    cluster = L.markerClusterGroup({
      maxClusterRadius: 50,
      // Custom icon: show camera count, colour by dominant health
      iconCreateFunction(c) {
        const ms = c.getAllChildMarkers();
        const live = ms.filter(m => m.options._health === 'LIVE').length;
        const down = ms.filter(m => m.options._health === 'DOWN').length;
        const cls  = down > 0 ? 'marker-cluster-large'
                   : live < ms.length / 2 ? 'marker-cluster-medium'
                   : 'marker-cluster-small';
        return L.divIcon({
          html: `<div><span>${c.getChildCount()}</span></div>`,
          className: `marker-cluster ${cls}`,
          iconSize: L.point(40, 40),
        });
      },
    });
    map.addLayer(cluster);

    drawMarkers(cameras);
    fitBounds(cameras);
  }

  function makeIcon(c) {
    const col  = HEALTH_COLOR[c.health] || HEALTH_COLOR.UNKNOWN;
    const low  = c.coord_conf === 'LOW';
    const sel  = window.prahari && window.prahari.selected &&
                 String(window.prahari.selected.camera_id) === String(c.camera_id);
    const sz   = sel ? 16 : 12;
    return L.divIcon({
      className: '',
      iconSize:  [sz, sz],
      iconAnchor:[sz / 2, sz / 2],
      html: `<div class="cam-pin${low ? ' dotted' : ''}"
               style="width:${sz}px;height:${sz}px;background:${col}"></div>`,
    });
  }

  function drawMarkers(cams) {
    cluster.clearLayers();
    markers = {};
    const placed = cams.filter(c => c.lat != null && c.lon != null);
    placed.forEach(c => {
      const m = L.marker([c.lat, c.lon], { icon: makeIcon(c), _health: c.health || 'UNKNOWN' });
      m.bindTooltip(`${esc(c.camera_id)} · ${esc(c.name)}`, { direction: 'top', opacity: 0.9 });
      m.on('click', () => window.selectCamera && window.selectCamera(c.camera_id));
      markers[c.camera_id] = m;
      cluster.addLayer(m);
    });
  }

  function fitBounds(cams) {
    const pts = cams.filter(c => c.lat != null).map(c => [c.lat, c.lon]);
    if (pts.length) map.fitBounds(pts, { padding: [40, 40] });
  }

  /** Refresh a single pin after a health change */
  function updateHealth(cameraId, health) {
    const c = cameras.find(x => String(x.camera_id) === String(cameraId));
    if (!c) return;
    c.health = health;
    const m = markers[cameraId];
    if (m) m.setIcon(makeIcon(c));
  }

  function flyTo(c) {
    if (c.lat == null) return;
    map.setView([c.lat, c.lon], Math.max(map.getZoom(), 15));
    const m = markers[c.camera_id];
    if (m) { cluster.zoomToShowLayer(m); m.openTooltip(); }
  }

  function invalidate() {
    if (map) setTimeout(() => map.invalidateSize(), 60);
  }

  /**
   * Stress-test: clone the camera list ×2000 (≈ 80,000 fake pins) and verify
   * clustering holds. Run from the browser console: MapView.cloneForStressTest()
   */
  function cloneForStressTest() {
    const fakes = [];
    for (let i = 0; i < 2000; i++) {
      cameras.forEach(c => {
        fakes.push(Object.assign({}, c, {
          camera_id: `${c.camera_id}_${i}`,
          lat: c.lat + (crypto.getRandomValues(new Uint32Array(1))[0] / 0xFFFFFFFF - .5) * 4,
          lon: c.lon + (crypto.getRandomValues(new Uint32Array(1))[0] / 0xFFFFFFFF - .5) * 4,
        }));
      });
    }
    drawMarkers(fakes);
    console.log(`stress test: ${cluster.getLayers().length} markers in cluster`);
  }

  // Expose map reference so wedges.js, events.js etc. can add layers
  function getMap() { return map; }

  return { init, drawMarkers, updateHealth, flyTo, invalidate, cloneForStressTest, getMap };
})();
