# fixtures/clips/ — replay material. No video is committed.

`.gitignore` excludes every clip and image in here. Video is large, the grid's footage is not
ours to redistribute, and AGENTS.md says nothing over 10 MB goes in the repo. Everything below
is produced by a command.

## The generated clip with a known plate

```bash
python -m services.worker.selftest --make-clip fixtures/clips/selftest.mp4
# -> fixtures/clips/selftest.mp4  plate=GJ 25 BJ 8377
```

A rendered Indian plate (`services/worker/synth.py`, salvaged from
`4d0c945:simgrid/plate_render.py`) composited onto a real vehicle photograph, driven across the
frame so it grows and sharpens as it approaches. Real photograph because the detector must
still detect: a drawn rectangle is not a vehicle to YOLO, and a pipeline test that skips the
detector tests nothing. `vehicle.jpg` is fetched once and cropped to the vehicle the detector
finds - that crop is what the plate gets stamped on.

## Replaying it as a camera

```bash
scripts/replay_clip.sh                                   # -> rtsp://localhost:8554/test
python -m services.worker.selftest --source rtsp://localhost:8554/test --seconds 30
```

## Grid clips

Recordings pulled from the sandbox go here too, named `<camera_id>-<yyyymmdd>-<hhmm>.mp4`, and
they stay out of git for the same reasons. If a clip carries a plate we have confirmed by eye,
record it in `fixtures/golden/labels.jsonl` (see that directory's README) so the accuracy report
can use it - a clip whose plate lives only in somebody's head is not ground truth.

## What the pipeline expects

- H.264 or H.265, any resolution; the decoder scales to 960 px wide and gates to 5 fps.
- Real PTS. A clip re-wrapped without timestamps makes `ts_source` a lie (`decode.py`).
- One vehicle pass per clip keeps the selftest's assertion unambiguous.
