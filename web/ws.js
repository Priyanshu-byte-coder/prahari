/**
 * [G9] ws.js — WebSocket client per [C5].
 *
 * Protocol:
 *   connect → send JWT as first message
 *   on reconnect → send {"type":"resume","since":<seq>}
 *   server sends {"type":..., "seq":<int>, "data":{...}}
 *   server pings every 15 s
 *
 * Features:
 *   - Exponential backoff reconnect (1 → 2 → 4 → … → 30 s)
 *   - Resume with last seq so no events are missed
 *   - Heartbeat watchdog: if no message for 20 s, treat as stale and reconnect
 *   - All messages routed to EventsLayer.handleWsMessage
 *
 * Falls back to replaying fixtures/api/ws-stream.jsonl when
 * the API is absent (dev mode with no WebSocket server).
 */

const WsClient = (() => {
  const PING_TIMEOUT_MS  = 20_000;
  const BACKOFF_START_MS = 1_000;
  const BACKOFF_MAX_MS   = 30_000;

  let ws       = null;
  let lastSeq  = 0;
  let backoff  = BACKOFF_START_MS;
  let pingTimer = null;
  let devMode  = false;

  function init() {
    const base = window.API_BASE || '';
    if (!base && !window.location.host) {
      // No API — replay fixture in dev
      devMode = true;
      replayFixture();
      return;
    }
    connect();
  }

  function connect() {
    const base  = window.API_BASE || `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}`;
    const wsUrl = base.replace(/^http/, 'ws') + '/ws';
    try {
      ws = new WebSocket(wsUrl);
    } catch (_) {
      schedule();
      return;
    }

    ws.addEventListener('open', () => {
      backoff = BACKOFF_START_MS;
      // First message must be the JWT
      const token = window._jwt || localStorage.getItem('prahari_token') || 'dev';
      ws.send(JSON.stringify({ token }));
      if (lastSeq > 0) {
        ws.send(JSON.stringify({ type: 'resume', since: lastSeq }));
      }
      resetPingTimer();
    });

    ws.addEventListener('message', e => {
      resetPingTimer();
      let msg;
      try { msg = JSON.parse(e.data); } catch (_) { return; }
      if (msg.type === 'ping') return;
      if (msg.seq != null && msg.seq > lastSeq) lastSeq = msg.seq;
      dispatch(msg);
    });

    ws.addEventListener('close',  () => { clearPingTimer(); schedule(); });
    // On error, mark the socket dead so the close handler's schedule() runs instead
    // of a second connect() call racing with it.
    ws.addEventListener('error',  () => { clearPingTimer(); });
  }

  function dispatch(msg) {
    if (typeof EventsLayer !== 'undefined') {
      EventsLayer.handleWsMessage(msg);
    }
  }

  function resetPingTimer() {
    clearPingTimer();
    pingTimer = setTimeout(() => {
      // Server went quiet — close the socket and let the 'close' handler
      // call schedule().  Do NOT call connect() here: the 'close' event fires
      // immediately after ws.close() and would create a second connect().
      ws && ws.close();
    }, PING_TIMEOUT_MS);
  }

  function clearPingTimer() {
    if (pingTimer) { clearTimeout(pingTimer); pingTimer = null; }
  }

  function schedule() {
    const delay = backoff + Math.random() * backoff * 0.3;
    backoff = Math.min(backoff * 2, BACKOFF_MAX_MS);
    setTimeout(connect, delay);
  }

  /** Dev mode: replay fixtures/api/ws-stream.jsonl line by line */
  async function replayFixture() {
    try {
      const resp = await fetch('../fixtures/api/ws-stream.jsonl');
      if (!resp.ok) return;
      const text = await resp.text();
      const lines = text.split('\n').filter(l => l.trim());
      let i = 0;
      const tick = () => {
        if (i >= lines.length) { i = 0; } // loop
        try {
          const msg = JSON.parse(lines[i]);
          if (msg.type !== 'ping') dispatch(msg);
        } catch (_) {}
        i++;
        setTimeout(tick, 1500);
      };
      setTimeout(tick, 2000); // 2 s delay so map is ready
    } catch (_) {}
  }

  return { init };
})();
