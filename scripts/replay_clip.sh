#!/usr/bin/env bash
# [I8] Publish a clip with a known plate to MediaMTX as an RTSP camera, on demand.
#
# This is how the judge scenario gets replayed at will, and it is what J1's integration test
# drives. The worker sees an RTSP URL and cannot tell it from a grid camera - which is the
# point: the demo path and the test path are the same path.
#
#   scripts/replay_clip.sh                                  # generated clip, known plate
#   scripts/replay_clip.sh fixtures/clips/mine.mp4 test      # your clip, stream name `test`
#   GRID_HOST=10.0.0.5 scripts/replay_clip.sh                # publish to the sandbox
#
# Then, in another shell:
#   python -m services.worker.selftest --source rtsp://$GRID_HOST:8554/test --seconds 30
#
# -re paces the file to real time (without it ffmpeg pushes an hour of video in seconds and the
# worker's motion gate and tracker see nonsense), -stream_loop -1 loops forever, and -c copy
# avoids re-encoding so the codec the worker decodes is the codec in the clip.
set -euo pipefail

CLIP="${1:-fixtures/clips/selftest.mp4}"
NAME="${2:-test}"
HOST="${GRID_HOST:-localhost}"
PORT="${RTSP_PORT:-8554}"
URL="rtsp://${HOST}:${PORT}/${NAME}"

if [ ! -f "$CLIP" ]; then
  echo "no clip at $CLIP - generating one with a known plate"
  python -m services.worker.selftest --make-clip "$CLIP"
fi

# Port 8554 is blocked on our own network (AGENTS.md); the gateway degrades to HLS per camera,
# but a *publisher* has no fallback, so say so plainly instead of hanging for 30 s.
if ! timeout 3 bash -c "cat < /dev/null > /dev/tcp/${HOST}/${PORT}" 2>/dev/null; then
  echo "cannot reach ${HOST}:${PORT} - is MediaMTX up? (make up), and is 8554 open here?" >&2
  exit 2
fi

echo "publishing $CLIP -> $URL  (ctrl-c to stop)"
exec ffmpeg -hide_banner -loglevel warning \
  -re -stream_loop -1 -i "$CLIP" -c copy -f rtsp -rtsp_transport tcp "$URL"
