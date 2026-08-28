# Runbook — determine whether RTSP is usable, or only HLS

**Owner:** Priyanshu · **Status:** open · **Blocks:** the ingestion-path decision

## Why this matters

The organisers' integration guide assigns the two transports different jobs:

| Transport | Endpoint | Intended for |
|---|---|---|
| RTSP | `rtsp://<host>:8554/stream/<id>` | AI inference (OpenCV, GStreamer, FFmpeg, DeepStream) |
| WebRTC (WHEP) | `http://<host>:8889/stream/<id>/whep` | Low-latency browser preview |
| HLS | `http://<host>/live/stream/<id>/index.m3u8` | Dashboards, mobile, restricted networks |

RTSP is the path they expect analytics to use. Every measurement so far was taken
on one network, where ports 8554, 8888 and 8889 are all filtered and only 80/443
answer. Prahari therefore ingests over HLS today.

Two very different worlds produce that same observation:

1. **The block is local** — a college or ISP firewall. Then RTSP will work at the
   venue, the intended low-latency path is available, and the HLS route becomes a
   documented fallback rather than the only option.
2. **The block is at the server** — the grid only exposes 80/443 publicly. Then
   every team is in the same position, HLS is the correct and only answer, and
   that is worth stating confidently in the HLD instead of apologising for it.

Guessing wrong in either direction is expensive. Finding out costs ten minutes.

## Procedure

Run this on a network that is **not** the one used for development — a phone
hotspot on mobile data is ideal, because it shares no infrastructure with a
campus or home connection.

### 1. Switch networks

Disconnect from the usual Wi-Fi and tether to a phone on mobile data. Confirm the
change took effect — a VPN or a lingering Wi-Fi association will invalidate the
result:

```
curl -s https://ifconfig.me
```

Record the address. If it matches the development network's public address,
nothing has changed and the test will produce a false negative.

### 2. Run the probe

```
.venv\Scripts\python.exe scripts\probe_grid.py --host https://live.corp8.cloud --cameras 2
```

The port table at the top of the output is the answer:

```
[+] port 80    (http) open
[-] port 8554  (rtsp) closed/filtered      <- the line that matters
```

### 3. Confirm with a direct RTSP open

A port scan can be misled by a middlebox that accepts the TCP handshake and then
drops the session. Only a real RTSP negotiation settles it:

```
ffprobe -rtsp_transport tcp -hide_banner -loglevel error ^
  -show_entries stream=codec_name,width,height ^
  -of default=nw=1 rtsp://live.corp8.cloud:8554/stream/13
```

- Codec and resolution printed within a few seconds → **RTSP works.**
- Hangs until timeout, or `Connection timed out` → **RTSP is blocked.**

Note the `-rtsp_transport tcp`. UDP must never be used against this grid: it
fails across NAT and produces partial delivery that looks like model bugs.

### 4. Record the result

Whatever the answer, write it into CONTEXT.md §3 with the date and the network
type used. A measurement nobody recorded has to be taken again.

If RTSP works on the second network, also run:

```
.venv\Scripts\python.exe scripts\survey_grid.py --transport both --workers 6
```

`grid_survey.json` stores a `use` field per camera, and the worker already
prefers RTSP wherever the survey found it reachable. No code change is needed to
switch — the transport decision is data, not a constant.

## Interpreting the outcome

| Result | What it means | What changes |
|---|---|---|
| RTSP open on hotspot, blocked on dev network | Local firewall | Re-survey at the venue on arrival. Keep HLS as the documented fallback; it is also what makes the platform work on restricted departmental networks, which is a genuine selling point. |
| RTSP blocked on both | Server-side, or blocked by both carriers | HLS is the only path. State it plainly in the HLD as an operating constraint of the sandbox, not a limitation of the design. |
| RTSP open on both | Earlier measurement was wrong or transient | Re-run the survey, switch the analytics path to RTSP, and correct CONTEXT.md §3. |

## Venue note

Whatever the answer, re-run step 2 on arrival at i-Hub before the judges appear.
Venue networks are their own category of firewall, and the first stream opening
must never happen in front of a panel.
