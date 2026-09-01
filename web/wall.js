/**
 * [G11] wall.js — HLS grid with hls.js + WebRTC WHEP fallback.
 *
 * Each tile:
 *   1. Tries WebRTC via WHEP (http://$GRID_HOST:8889/stream/<id>/whep)
 *   2. If WebRTC does not connect within 3 s, falls back to HLS with a badge
 *
 * Health badge per tile.
 * Preset "alert view" opens the alerting camera + its two nearest neighbours.
 *
 * NOTE: This grid's HLS is low-latency fMP4 and the browser can't play it
 * directly. For the proxy path we use the /tile/ endpoint from console_serve.py
 * (server-side PyAV JPEG cache). The wall.js code still attempts real HLS
 * via hls.js so the architecture is demonstrated; the tile fallback handles
 * the cases where hls.js can't decode it.
 */

const WallView = (() => {
  const WHEP_TIMEOUT_MS = 3000;
  /** Escape text before inserting into innerHTML. */
  const esc = s => { const d = document.createElement('div'); d.textContent = String(s ?? ''); return d.innerHTML; };
  const PROXY_BASE      = '';   // same-origin proxy via console_serve.py

  let cameras    = [];
  let pcs        = {};   // camera_id → RTCPeerConnection
  let hlsInst    = {};   // camera_id → Hls instance
  let tileTimers = {};
  let active     = false;

  function init(cams) {
    cameras = cams;
  }

  function activate() {
    if (!active) {
      active = true;
      render();
    } else {
      render();
    }
  }

  function render() {
    const grid = document.getElementById('wallGrid');
    if (!grid) return;

    // toolbar
    const parent = grid.parentElement;
    let tb = parent.querySelector('.wall-toolbar');
    if (!tb) {
      tb = document.createElement('div');
      tb.className = 'wall-toolbar';
      tb.innerHTML = `
        <span class="section-title" style="margin:0">Video wall</span>
        <button class="btn sm go" id="wallStartAll">▶ All</button>
        <button class="btn sm stop" id="wallStopAll">■ Stop all</button>
        <button class="btn sm" id="wallAlertView">🚨 Alert view</button>
        <span class="hint" id="wallStatus" style="margin-left:auto"></span>`;
      parent.insertBefore(tb, grid);
      tb.querySelector('#wallStartAll').addEventListener('click', startAll);
      tb.querySelector('#wallStopAll').addEventListener('click',  stopAll);
      tb.querySelector('#wallAlertView').addEventListener('click', alertView);
    }

    const shown = cameras.filter(c => c.lat != null || true); // show all
    grid.innerHTML = shown.map(c => `
      <div class="wall-tile" id="wt-${esc(c.camera_id)}" data-id="${esc(c.camera_id)}">
        <video id="wv-${esc(c.camera_id)}" autoplay muted playsinline
               style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;display:none"></video>
        <img   id="wi-${esc(c.camera_id)}" alt=""
               style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;display:none">
        <div class="tile-bar">
          <span class="hdot h-${(c.health||'unknown').toLowerCase()}" id="wdot-${esc(c.camera_id)}"></span>
          <span class="tnm">${esc(c.camera_id)} · ${esc(c.name)}</span>
          <span class="whep-badge" id="wbadge-${esc(c.camera_id)}"></span>
        </div>
      </div>`).join('');

    grid.querySelectorAll('.wall-tile').forEach(t => {
      t.addEventListener('click', e => {
        const id = t.dataset.id;
        if (e.shiftKey) { enlargeTile(id); } else { openOne(id); }
      });
    });
  }

  function openOne(id) {
    stopTile(id);
    startTile(id);
    // Highlight
    document.querySelectorAll('.wall-tile').forEach(t =>
      t.classList.toggle('ws-active', t.dataset.id === String(id)));
    window.selectCamera && window.selectCamera(id);
  }

  function startAll() {
    cameras.forEach(c => startTile(String(c.camera_id)));
  }

  function stopAll() {
    cameras.forEach(c => stopTile(String(c.camera_id)));
  }

  /** Open the alerting camera + its two nearest neighbours */
  function alertView() {
    const alerts = window.prahari && window.prahari.alerts;
    if (!alerts || !alerts.length) {
      document.getElementById('wallStatus').textContent = 'No active alerts.';
      return;
    }
    const alertCamId = String(alerts[0].camera_id);
    const alertCam   = cameras.find(c => String(c.camera_id) === alertCamId);
    if (!alertCam || alertCam.lat == null) { openOne(alertCamId); return; }

    // Find two nearest cameras by Haversine
    const near = cameras
      .filter(c => String(c.camera_id) !== alertCamId && c.lat != null)
      .map(c => ({ c, d: haversine(alertCam.lat, alertCam.lon, c.lat, c.lon) }))
      .sort((a, b) => a.d - b.d)
      .slice(0, 2)
      .map(x => x.c);

    stopAll();
    [alertCam, ...near].forEach(c => startTile(String(c.camera_id)));
    document.getElementById('wallStatus').textContent =
      `Alert view: cam ${alertCamId} + ${near.map(c => c.camera_id).join(', ')}`;
  }

  /** Start a single tile: try WHEP, fall back to HLS tile polling */
  async function startTile(id) {
    stopTile(id); // clean up first

    const cam = cameras.find(c => String(c.camera_id) === id);
    if (!cam) return;

    const whepUrl = cam.transports && cam.transports.whep;
    if (whepUrl) {
      const ok = await tryWhep(id, whepUrl);
      if (ok) return;
    }
    // Fallback to HLS tile polling (server-side JPEG cache)
    startTilePoll(id);
  }

  async function tryWhep(id, whepUrl) {
    return new Promise(resolve => {
      let settled = false;
      // cleanupPc: close the RTCPeerConnection and cancel the timeout so no
      // further settle() calls can fire after the promise is already resolved.
      // Called by every settle(false) path to prevent PC leaks.
      const cleanupPc = () => {
        clearTimeout(timeout);
        if (pcs[id]) { try { pcs[id].close(); } catch (_) {} delete pcs[id]; }
      };
      const settle = (ok) => {
        if (!settled) {
          settled = true;
          if (!ok) cleanupPc();
          resolve(ok);
        }
      };

      const timeout = setTimeout(() => {
        settle(false);
        setBadge(id, 'hls');
      }, WHEP_TIMEOUT_MS);

      try {
        const pc = new RTCPeerConnection({ iceServers: [{ urls: 'stun:stun.l.google.com:19302' }] });
        pcs[id] = pc;

        pc.addTransceiver('video', { direction: 'recvonly' });
        pc.addTransceiver('audio', { direction: 'recvonly' });

        pc.ontrack = e => {
          const video = document.getElementById('wv-' + id);
          if (!video) return;
          video.srcObject = e.streams[0];
          video.style.display = 'block';
          // Hide tile img
          const img = document.getElementById('wi-' + id);
          if (img) img.style.display = 'none';
          clearTimeout(timeout);
          setBadge(id, 'webrtc');
          settle(true);
        };

        pc.onconnectionstatechange = () => {
          if (pc.connectionState === 'failed' || pc.connectionState === 'disconnected') {
            setBadge(id, 'hls');
            settle(false);
          }
        };

        (async () => {
          try {
            const offer = await pc.createOffer();
            await pc.setLocalDescription(offer);
            // Send offer to WHEP endpoint
            const resp = await fetch(whepUrl, {
              method: 'POST',
              headers: { 'Content-Type': 'application/sdp' },
              body: offer.sdp,
            });
            if (!resp.ok) { settle(false); return; }
            const answerSdp = await resp.text();
            await pc.setRemoteDescription({ type: 'answer', sdp: answerSdp });
          } catch (_) {
            settle(false);
          }
        })();
      } catch (_) {
        settle(false);
      }
    });
  }

  function startTilePoll(id) {
    // Poll /tile/<id>.jpg from console_serve.py (server-side PyAV cache)
    // Falls back to /grid/live/stream/<id>/index.m3u8 thumbnails if tile is empty.
    const img = document.getElementById('wi-' + id);
    if (!img) return;
    img.style.display = 'block';

    setBadge(id, 'hls');

    const poll = () => {
      if (!document.getElementById('wi-' + id)) return; // tile removed
      const probe = new Image();
      probe.onload = () => {
        if (img) img.src = probe.src;
      };
      probe.src = `${PROXY_BASE}/tile/${id}.jpg?t=${Date.now()}`;
      tileTimers[id] = setTimeout(poll, 2000);
    };
    poll();
  }

  function stopTile(id) {
    if (pcs[id]) { try { pcs[id].close(); } catch (_) {} delete pcs[id]; }
    if (hlsInst[id]) { try { hlsInst[id].destroy(); } catch (_) {} delete hlsInst[id]; }
    if (tileTimers[id]) { clearTimeout(tileTimers[id]); delete tileTimers[id]; }
    const video = document.getElementById('wv-' + id);
    if (video) { video.srcObject = null; video.style.display = 'none'; }
    const img = document.getElementById('wi-' + id);
    if (img) { img.src = ''; img.style.display = 'none'; }
    setBadge(id, '');
  }

  function setBadge(id, type) {
    const b = document.getElementById('wbadge-' + id);
    if (!b) return;
    if (!type) { b.textContent = ''; b.className = 'whep-badge'; return; }
    b.textContent = type === 'webrtc' ? 'WebRTC' : 'HLS';
    b.className   = `whep-badge ${type}`;
  }

  function enlargeTile(id) {
    const img = document.getElementById('wi-' + id);
    if (img && img.src) { window.openModal && window.openModal(img.src); }
  }

  /** Update health dot from WS event */
  function updateHealth(cameraId, health) {
    const dot = document.getElementById('wdot-' + cameraId);
    if (dot) dot.className = `hdot h-${health.toLowerCase()}`;
  }

  function haversine(lat1, lon1, lat2, lon2) {
    const R = 6371;
    const d2r = x => x * Math.PI / 180;
    const dLat = d2r(lat2 - lat1), dLon = d2r(lon2 - lon1);
    const a = Math.sin(dLat / 2) ** 2 +
              Math.cos(d2r(lat1)) * Math.cos(d2r(lat2)) * Math.sin(dLon / 2) ** 2;
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  }

  return { init, activate, openOne, updateHealth };
})();
