/**
 * [G8] wedges.js — Coverage wedges + bearing drag editor.
 *
 * Draws a translucent polygon per camera that has a bearing_deg:
 *   arc from (bearing - fov/2) to (bearing + fov/2), out to range_m.
 *
 * A drag handle at the wedge tip lets the operator rotate the bearing.
 * On drag-end it calls PATCH /api/cameras/{id} and refreshes the polygon.
 *
 * We deliberately draw nothing when bearing_deg is null — an invented
 * wedge is worse than no wedge (misleads the operator about the FOV).
 */

const WedgeLayer = (() => {
  const FILL   = '#3b82f6';
  const HANDLE_COLOR = '#60a5fa';
  // metres → approximate degrees at Gujarat latitude (~22°N)
  const M_PER_DEG_LAT = 111000;

  let mapRef = null, wedges = {}, handles = {};

  function init(cameras) {
    // Grab the Leaflet map from MapView after it has been initialised
    setTimeout(() => {
      mapRef = MapView.getMap ? MapView.getMap() : null;
      cameras.forEach(c => drawWedge(c));
    }, 250);
  }

  // Called by map.js after the map is ready
  function attachMap(m) {
    mapRef = m;
  }

  function mToDeg(metres) {
    return metres / M_PER_DEG_LAT;
  }

  function buildPoints(c) {
    if (c.bearing_deg == null || c.lat == null) return null;
    const lat  = c.lat, lon = c.lon;
    const fov  = c.fov_deg  || 70;
    const rng  = mToDeg(c.range_m || 60);
    const cosLat = Math.cos(lat * Math.PI / 180);
    const pts  = [[lat, lon]];
    for (let a = c.bearing_deg - fov / 2; a <= c.bearing_deg + fov / 2; a += 5) {
      const r = a * Math.PI / 180;
      pts.push([
        lat + Math.cos(r) * rng,
        lon + Math.sin(r) * rng / cosLat,
      ]);
    }
    pts.push([lat, lon]);
    return pts;
  }

  function tipLatLon(c) {
    if (c.bearing_deg == null || c.lat == null) return null;
    const rng    = mToDeg(c.range_m || 60);
    const cosLat = Math.cos(c.lat * Math.PI / 180);
    const r      = c.bearing_deg * Math.PI / 180;
    return [c.lat + Math.cos(r) * rng, c.lon + Math.sin(r) * rng / cosLat];
  }

  function drawWedge(c) {
    if (!mapRef) return;
    removeWedge(c.camera_id);
    if (c.bearing_deg == null || c.lat == null) return;

    const pts = buildPoints(c);
    if (!pts) return;

    const poly = L.polygon(pts, {
      color:       FILL,
      weight:      1,
      fillOpacity: 0.15,
      interactive: false,
    }).addTo(mapRef);
    wedges[c.camera_id] = poly;

    // Drag handle at tip.
    // L.circleMarker is NOT draggable in core Leaflet (no dragging handler).
    // Use L.marker with a DivIcon styled as a circle — L.marker supports drag
    // natively without any extra plugin.
    const tip = tipLatLon(c);
    if (!tip) return;
    const handle = L.marker(tip, {
      icon: L.divIcon({
        className: '',
        html: `<div style="
          width:12px;height:12px;border-radius:50%;
          background:${HANDLE_COLOR};border:2px solid #2563eb;
          margin:-6px 0 0 -6px;cursor:grab;"></div>`,
        iconSize:   [0, 0],
        iconAnchor: [0, 0],
      }),
      draggable: true,
      autoPan:   false,
    }).addTo(mapRef);

    handle.on('drag', e => {
      const ll   = e.latlng;
      const dlat = ll.lat - c.lat, dlon = ll.lng - c.lon;
      const cosLat = Math.cos(c.lat * Math.PI / 180);
      const newBearing = Math.round((Math.atan2(dlon * cosLat, dlat) * 180 / Math.PI + 360) % 360);
      // Live preview
      const previewC = Object.assign({}, c, { bearing_deg: newBearing });
      const pts2 = buildPoints(previewC);
      if (pts2) poly.setLatLngs(pts2);
    });

    handle.on('dragend', async e => {
      const ll   = e.target.getLatLng();
      const dlat = ll.lat - c.lat, dlon = ll.lng - c.lon;
      const cosLat = Math.cos(c.lat * Math.PI / 180);
      const newBearing = Math.round((Math.atan2(dlon * cosLat, dlat) * 180 / Math.PI + 360) % 360);

      // Persist via PATCH /api/cameras/{id}
      try {
        const resp = await fetch(`${window.API_BASE || ''}/api/cameras/${c.camera_id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ bearing_deg: newBearing }),
        });
        if (resp.ok) {
          const updated = await resp.json();
          c.bearing_deg = updated.bearing_deg ?? newBearing;
        } else {
          c.bearing_deg = newBearing; // optimistic update when API is down
        }
      } catch (_) {
        c.bearing_deg = newBearing;
      }

      // Redraw
      drawWedge(c);
      // Also update the cameras array held by the page
      const arr = window.prahari && window.prahari.cameras;
      if (arr) {
        const idx = arr.findIndex(x => String(x.camera_id) === String(c.camera_id));
        if (idx !== -1) arr[idx].bearing_deg = c.bearing_deg;
      }
    });

    handles[c.camera_id] = handle;
  }

  function removeWedge(id) {
    if (wedges[id])  { mapRef && mapRef.removeLayer(wedges[id]);  delete wedges[id]; }
    if (handles[id]) { mapRef && mapRef.removeLayer(handles[id]); delete handles[id]; }
  }

  function redrawAll(cameras) {
    Object.keys(wedges).forEach(id => removeWedge(id));
    cameras.forEach(c => drawWedge(c));
  }

  return { init, attachMap, drawWedge, removeWedge, redrawAll };
})();
