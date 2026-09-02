/**
 * [G10] route.js — Route view (the graded test case).
 *
 * Plate + time window in → numbered pins 1..N out, animated polyline,
 * table below the map, CSV and PDF export.
 *
 * Special rendering:
 *   - PROBABLE hops: dashed line + dashed pin border
 *   - IMPLAUSIBLE hops: warning icon + implied speed shown
 *   - Fuzzy result sets: "verify plate" banner
 *
 * Works entirely from fixtures/api/route.json when the API is down.
 * Legend is fixed: "sighting order, road-snapped between sightings; not a GPS track."
 */

const RouteView = (() => {
  const PIN_CONFIRMED = '#34d399';
  const PIN_PROBABLE  = '#fbbf24';
  const LINE_CONFIRMED = '#3b82f6';
  const LINE_PROBABLE  = '#a78bfa';
  /** Escape text before inserting into innerHTML. */
  const esc = s => { const d = document.createElement('div'); d.textContent = String(s ?? ''); return d.innerHTML; };
  const PIN_IMPLAUSIBLE = '#f87171';

  let routeMap = null, routeData = null;
  let lineLayers = [], pinLayers = [];

  function init() {
    buildPanel();
  }

  function buildPanel() {
    const panel = document.getElementById('routePanel');
    if (!panel) return;
    panel.innerHTML = `
      <div class="section-title">Route Search</div>
      <div style="display:grid;gap:8px">
        <label style="color:var(--dim);font-size:11px">Plate number</label>
        <input id="routePlate" placeholder="GJ01AB1234" style="font-family:ui-monospace,monospace" autocomplete="off">
        <label style="color:var(--dim);font-size:11px">From</label>
        <input id="routeFrom" type="datetime-local" autocomplete="off">
        <label style="color:var(--dim);font-size:11px">To</label>
        <input id="routeTo"   type="datetime-local" autocomplete="off">
        <button class="btn go" id="routeSearch">Search route</button>
      </div>
      <div id="routeStatus" class="hint"></div>
      <div id="routeResult" style="flex:1;overflow-y:auto"></div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:auto;padding-top:10px">
        <button class="btn sm" id="routeExportCsv" style="display:none">⬇ CSV</button>
        <button class="btn sm" id="routeExportPdf" style="display:none">⬇ PDF</button>
      </div>`;

    // Default time window: last 2 h
    const now  = new Date();
    const twoH = new Date(now - 2 * 3600_000);
    document.getElementById('routeTo').value   = toLocal(now);
    document.getElementById('routeFrom').value = toLocal(twoH);

    document.getElementById('routeSearch').addEventListener('click', doSearch);
    document.getElementById('routeExportCsv').addEventListener('click', exportCsv);
    document.getElementById('routeExportPdf').addEventListener('click', exportPdf);
  }

  function activate() {
    if (!routeMap) {
      routeMap = L.map('routeMap', { fadeAnimation: false }).setView([22.6, 71.6], 8);
      L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',
        { maxZoom: 19, attribution: '© OpenStreetMap contributors' }).addTo(routeMap);
      setTimeout(() => routeMap.invalidateSize(), 60);
    }
    if (routeData) render(routeData);
  }

  /** Called from camera detail "Route" button */
  function openSearch(cameraId) {
    // Pre-fill plate from last sighting on that camera if available
    const events = window.prahari && window.prahari.lastEvents;
    const ev = events && events.find(e => String(e.camera_id) === String(cameraId));
    if (ev && ev.plate_norm) {
      document.getElementById('routePlate').value = ev.plate_norm;
    }
  }

  async function doSearch() {
    const plate = document.getElementById('routePlate').value.trim().toUpperCase();
    const from  = toUtcIso(document.getElementById('routeFrom').value);
    const to    = toUtcIso(document.getElementById('routeTo').value);
    if (!plate) {
      document.getElementById('routeStatus').textContent = 'Enter a plate number.';
      return;
    }
    document.getElementById('routeStatus').textContent = 'Searching…';
    clearMap();

    const params = new URLSearchParams({ plate, from, to });
    const data = await window.apiFetch(`/api/route?${params}`, null)
      || await window.apiFetch('/api/route', null); // fixture fallback

    if (!data || !data.hops || data.hops.length === 0) {
      document.getElementById('routeStatus').textContent = 'No sightings found for this plate in the selected window.';
      return;
    }

    routeData = data;
    document.getElementById('routeStatus').textContent = '';
    render(data);
    document.getElementById('routeExportCsv').style.display = '';
    document.getElementById('routeExportPdf').style.display = '';
  }

  function render(data) {
    if (!routeMap) return;
    clearMap();

    // Fuzzy banner
    const result = document.getElementById('routeResult');
    result.innerHTML = data.fuzzy
      ? `<div style="background:#3b3000;border:1px solid #7a6000;border-radius:6px;padding:8px 10px;margin-bottom:10px;font-size:12px;color:#fbbf24">
           ⚠ Fuzzy match — verify plate before acting on this route
         </div>`
      : '';

    // ── Snapped geometry ──
    if (data.snapped_geometry && data.snapped_geometry.coordinates) {
      const coords = data.snapped_geometry.coordinates.map(([lon, lat]) => [lat, lon]);
      const line = L.polyline(coords, {
        color: '#3b82f680', weight: 3, dashArray: null,
      }).addTo(routeMap);
      lineLayers.push(line);
    }

    // ── Hop-by-hop lines + pins ──
    const bounds = [];
    data.hops.forEach((hop, i) => {
      bounds.push([hop.lat, hop.lon]);

      // Line to next hop
      if (i < data.hops.length - 1) {
        const next = data.hops[i + 1];
        const isProbable   = hop.kind === 'PROBABLE' || next.kind === 'PROBABLE';
        const isImplausible = next.flag === 'IMPLAUSIBLE';
        const color = isProbable ? LINE_PROBABLE : LINE_CONFIRMED;
        const dash  = isProbable ? '8 5' : null;
        const line  = L.polyline([[hop.lat, hop.lon], [next.lat, next.lon]], {
          color, weight: isProbable ? 2 : 3, dashArray: dash, opacity: 0.85,
        }).addTo(routeMap);
        lineLayers.push(line);

        if (isImplausible) {
          // Mid-point warning marker
          const mid = [
            (hop.lat + next.lat) / 2,
            (hop.lon + next.lon) / 2,
          ];
          const warn = L.marker(mid, {
            icon: L.divIcon({
              className: '',
              html: `<div style="background:#f87171;color:#fff;border-radius:50%;width:20px;height:20px;
                            display:grid;place-items:center;font-size:12px;border:2px solid #0d1014;
                            box-shadow:0 0 0 2px #f8717144">⚡</div>`,
              iconSize: [20, 20], iconAnchor: [10, 10],
            }),
          }).addTo(routeMap);
          warn.bindTooltip(
            `IMPLAUSIBLE: ${next.implied_speed_kmh ? next.implied_speed_kmh.toFixed(0) + ' km/h implied' : 'speed check failed'}`,
            { direction: 'top' }
          );
          pinLayers.push(warn);
        }
      }

      // Numbered pin
      const isProbable    = hop.kind === 'PROBABLE';
      const isImplausible = hop.flag === 'IMPLAUSIBLE';
      const bg = isImplausible ? PIN_IMPLAUSIBLE : isProbable ? PIN_PROBABLE : PIN_CONFIRMED;
      const border = isProbable ? 'border-style:dashed' : '';
      const pin = L.marker([hop.lat, hop.lon], {
        icon: L.divIcon({
          className: '',
          iconSize:  [26, 26], iconAnchor: [13, 13],
          html: `<div style="background:${bg};color:#0d1014;border-radius:50%;
                              width:26px;height:26px;display:grid;place-items:center;
                              font-weight:700;font-size:12px;border:2px solid #0d1014;${border}
                              box-shadow:0 0 0 2px ${bg}44">${hop.n}</div>`,
        }),
        _hop: hop,
      }).addTo(routeMap);

      const cropHtml = hop.crop_url
        ? `<img src="${hop.crop_url}" style="max-width:120px;border-radius:4px;margin-top:4px" onerror="this.style.display='none'">`
        : '';
      pin.bindPopup(`
        <b>${esc(hop.n)}. ${esc(hop.name)}</b><br>
        ${esc(new Date(hop.pts).toLocaleString())}<br>
        Band: <b>${esc(hop.band)}</b>${hop.kind === 'PROBABLE' ? ' (Re-ID hop, dashed)' : ''}<br>
        ${hop.implied_speed_kmh ? `Speed: ${esc(hop.implied_speed_kmh.toFixed(0))} km/h` : ''}
        ${hop.flag ? `<br><span style="color:#f87171">⚡ ${esc(hop.flag)}</span>` : ''}
        ${cropHtml}`, { maxWidth: 200 });
      pinLayers.push(pin);
    });

    if (bounds.length) routeMap.fitBounds(bounds, { padding: [40, 40] });

    // ── Legend ──
    if (!routeMap._legendAdded) {
      routeMap._legendAdded = true;
      const legend = L.control({ position: 'bottomleft' });
      legend.onAdd = () => {
        const d = L.DomUtil.create('div');
        d.style.cssText = `background:#151a21cc;padding:8px 10px;border-radius:6px;
                           font-size:11px;color:#8b97a8;line-height:1.8;
                           border:1px solid #262e3a;max-width:260px`;
        d.innerHTML = `
          <b style="color:#e8ecf2">Legend</b><br>
          <span style="color:#34d399">●</span> Confirmed sighting<br>
          <span style="color:#fbbf24">○</span> Probable (Re-ID corroboration, dashed hop)<br>
          <span style="color:#f87171">⚡</span> Implausible speed — one of these sightings is likely wrong<br>
          <span style="color:#5c6675;font-style:italic">Sighting order, road-snapped between sightings; not a GPS track.</span>`;
        return d;
      };
      legend.addTo(routeMap);
    }

    // ── Table ──
    result.innerHTML += `
      <div class="section-title">Sightings</div>
      <table class="data-table">
        <thead><tr>
          <th>#</th><th>Camera</th><th>Time</th><th>Band</th><th>Speed</th><th>Flag</th>
        </tr></thead>
        <tbody>
          ${data.hops.map(h => `
          <tr>
            <td>${esc(h.n)}</td>
            <td>${esc(h.name)}<br><span style="color:var(--faint)">${esc(h.camera_id)}</span></td>
            <td>${esc(new Date(h.pts).toLocaleTimeString())}</td>
            <td><span class="chip" style="${h.kind==='PROBABLE'?'color:var(--deg)':'color:var(--live)'}">${esc(h.kind)}</span></td>
            <td>${h.implied_speed_kmh ? esc(h.implied_speed_kmh.toFixed(0)) + ' km/h' : '—'}</td>
            <td>${h.flag ? `<span style="color:var(--down)">⚡ ${esc(h.flag)}</span>` : '—'}</td>
          </tr>`).join('')}
        </tbody>
      </table>`;
  }

  function clearMap() {
    lineLayers.forEach(l => routeMap && routeMap.removeLayer(l));
    pinLayers.forEach(l => routeMap && routeMap.removeLayer(l));
    lineLayers = []; pinLayers = [];
    const r = document.getElementById('routeResult');
    if (r) r.innerHTML = '';
  }

  // ── Export ──
  function exportCsv() {
    if (!routeData) return;
    const rows = [
      ['n', 'camera_id', 'name', 'pts', 'kind', 'band', 'implied_speed_kmh', 'flag', 'crop_url'],
      ...routeData.hops.map(h => [
        h.n, h.camera_id, h.name, h.pts, h.kind, h.band,
        h.implied_speed_kmh ?? '', h.flag ?? '', h.crop_url ?? '',
      ]),
    ];
    const csv = rows.map(r => r.map(v => `"${String(v).replace(/"/g, '""')}"`).join(',')).join('\n');
    download(`route_${routeData.plate}.csv`, 'text/csv', csv);
    logAuditExport('csv');
  }

  function exportPdf() {
    // WeasyPrint lives server-side; hit the API export endpoint.
    // When offline, show a message.
    if (!routeData) return;
    const plate = routeData.plate;
    const from  = toUtcIso(document.getElementById('routeFrom').value);
    const to    = toUtcIso(document.getElementById('routeTo').value);
    const url   = `${window.API_BASE || ''}/api/route/export?plate=${encodeURIComponent(plate)}&from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}&fmt=pdf`;
    // Open in new tab — the server will return the PDF and write an audit row.
    window.open(url, '_blank');
    logAuditExport('pdf');
  }

  function logAuditExport(fmt) {
    // Fire-and-forget audit log; server enforces on /api/route/export
    fetch(`${window.API_BASE || ''}/api/route/export`, {
      method: 'GET',
      headers: { 'X-Audit-Format': fmt },
    }).catch(() => {});
  }

  function download(name, mime, content) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([content], { type: mime }));
    a.download = name; a.click();
  }

  function toLocal(d) {
    const pad = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  /** A `datetime-local` input's .value has no timezone - the browser means it in local time,
   *  but the API's `datetime.fromisoformat` treats a bare string as UTC. Converting here once,
   *  at read time, is what keeps a route search in IST from silently querying the wrong 2 hours. */
  function toUtcIso(localValue) {
    return localValue ? new Date(localValue).toISOString() : localValue;
  }

  return { init, activate, openSearch };
})();
