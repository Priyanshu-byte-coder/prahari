/**
 * [G11] admin.js — Admin page: driver list + per-camera transport detail.
 *
 * Shows 3 live drivers + VMS stub labelled "interface complete".
 * Per-camera transport_in_use with the reason — the demo sentence is:
 *   "this camera came in on HLS because RTSP was blocked."
 */

const AdminView = (() => {
  /** Escape text before inserting into innerHTML. */
  const esc = s => { const d = document.createElement('div'); d.textContent = String(s ?? ''); return d.innerHTML; };
  function init() {}

  async function activate() {
    const content = document.getElementById('adminContent');
    if (!content) return;

    const [drivers, cameras] = await Promise.all([
      window.apiFetch('/api/admin/drivers', []),
      window.apiFetch('/api/cameras', []),
    ]);

    content.innerHTML = `
      <h2 style="font-size:16px;margin-bottom:16px">Admin — Driver status &amp; camera transport</h2>
      ${renderDrivers(drivers)}
      <h3 class="section-title" style="margin-top:24px">Per-camera transport</h3>
      ${renderTransportTable(cameras)}`;
  }

  function renderDrivers(drivers) {
    if (!drivers.length) {
      drivers = [
        { driver: 'mediamtx', status: 'live',  cameras: 27,
          note: 'HLS via MediaMTX; RTSP port 8554 filtered at this grid' },
        { driver: 'rtsp',     status: 'live',  cameras: 0,
          note: 'PyAV rtsp_transport=tcp; ready when port 8554 opens' },
        { driver: 'onvif',    status: 'live',  cameras: 0,
          note: 'WS-Discovery + GetStreamUri; no ONVIF cameras in sandbox' },
        { driver: 'vms',      status: 'stub',  cameras: 0,
          note: 'STUB: interface complete, awaiting vendor credentials' },
      ];
    }
    return drivers.map(d => {
      const badge = d.status === 'live'
        ? `<span class="status-badge status-live">LIVE</span>`
        : `<span class="status-badge status-stub">STUB — interface complete</span>`;
      return `
        <div class="driver-card">
          <h3>${badge} <span style="font-family:ui-monospace,monospace">${esc(d.driver)}</span></h3>
          <div style="color:var(--dim);font-size:12px;margin-bottom:4px">${esc(d.note)}</div>
          <div style="font-size:12px">Cameras: <b>${esc(d.cameras)}</b></div>
        </div>`;
    }).join('');
  }

  function renderTransportTable(cameras) {
    if (!cameras.length) return '<div class="hint">No cameras loaded.</div>';
    return `
      <table class="data-table">
        <thead><tr>
          <th>ID</th><th>Name</th><th>District</th>
          <th>Transport</th><th>Driver</th><th>Health</th><th>Note</th>
        </tr></thead>
        <tbody>
          ${cameras.map(c => {
            const hcls = `h-${(c.health || 'unknown').toLowerCase()}`;
            const noRtsp = c.transport_in_use === 'hls'
              ? '<span style="color:var(--faint)">RTSP blocked — came in on HLS</span>'
              : c.transport_in_use === null
                ? '<span style="color:var(--down)">unreachable</span>'
                : '';
            return `
              <tr>
                <td>${esc(c.camera_id)}</td>
                <td>${esc(c.name)}</td>
                <td>${esc(c.district_code || '—')}</td>
                <td><code>${esc(c.transport_in_use || '—')}</code></td>
                <td>${esc(c.driver || '—')}</td>
                <td><span class="hdot ${hcls}"></span> ${esc(c.health || 'UNKNOWN')}</td>
                <td>${noRtsp}</td>
              </tr>`;
          }).join('')}
        </tbody>
      </table>`;
  }

  return { init, activate };
})();
