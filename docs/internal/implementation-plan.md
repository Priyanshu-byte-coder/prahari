# SENTINEL Gujarat: End-to-End Implementation Plan

Gujarat Police Innovation Challenge 2026 (portal: sentinel.gujarat.gov.in)
Prepared: Friday, 28 August 2026

## 0. How to read this plan

- New terms are explained in brackets the first time they appear. A full glossary is in Section 19.
- "D1, D12, D17 ..." point to decision records in our CONTEXT.md.
- P0 = must work live in the demo. P1 = build if time remains. P2 = show on a slide with numbers, no code needed.
- Every section ends with a Decision line. We follow the decision unless a real blocker appears. A blocker becomes a new D-record, not a chat.
- Owner codes: STREAM (gateway and video), MODEL (training and inference), DATA (database, API, security), UI (map, wall, console). One person can hold two codes on a small team.

## 1. What the judges score

Facts we build against:

- ANPR is mandatory (ANPR = Automatic Number Plate Reading: the camera output becomes a text row "this plate passed this camera at this time"). Face, crowd and anomaly detection are bonus.
- Watchlist correlation: the portal asks for continuous cross-referencing of live CCTV feeds with a representative watchlist and automated real-time alerts on a match. Categories: stolen vehicles, wanted persons, missing persons, blacklisted vehicles, suspect watchlists.
- Architecture: four reference models. Model 1 = camera registry plus GIS map. Model 2 = direct connection to each camera or VMS (VMS = Video Management System, the software a department already uses to record and view its cameras). Model 3 = federation middleware (one common platform that talks to many VMS platforms through adapters). Model 4 = one central VMS. A well-argued hybrid earns the innovation bonus.
- Bonus marks for auditability and role-based access control (RBAC = each user role sees and does only what its job needs).
- Format: two stages. Stage 1 is an open innovation challenge with two categories (students and small startups; larger companies). The six best teams go to a finale and demonstrate on live camera feeds in a real policing scenario. Prize pool Rs 37 lakh. Expected start: September 2026. Partners: i-Hub Gujarat (technology), DA-IICT and NFSU (knowledge). The police describe it as the first Indian initiative where teams must demonstrate on live feeds.
- The stated test case: a judge types a plate number and the system shows where that vehicle was seen, in order, across cameras.
- Expect a technically literate jury: police leadership plus forensic and academic partners. Unsupported numbers will be challenged.

Conclusion: the finale is judged on live streams. Everything below is built to run on live streams first and to look good on slides second.

## 2. Where we stand today

| Capability | Today | Gap | Workstream |
|---|---|---|---|
| Stream ingest | Gateway pulls HLS from the MediaMTX sandbox (30 cameras) | Direct pull is Model 2 mechanically; no driver abstraction; RTSP port 8554 blocked on our network | A |
| Vehicle detection and tracking | YOLOv8s + ByteTrack, working | Not fine-tuned on our data; not TensorRT | B1, B4, C |
| Plate localisation | Fine-tuned detector (D20) | Re-validate on a golden set | B2 |
| Plate reading | Awiros OCR (D14); 73% legible, 13% illegible (D17); 2/3 majority fusion rule (D18) | Single reader, single frame; no plate grammar | B3 |
| Persistence | JSON on disk | No time-ordered index, no fuzzy index | D |
| Detections to console | 800 ms polling | WebSocket push | E5 |
| Map | Leaflet vendored, drag-to-move pins | Coordinates are district centroids; no layers, wedges, slider, route | F |
| Watchlist | Levenshtein matcher (D12), boolean | Confidence bands, alert state machine, feeds | E |
| RBAC and audit | None | Everything | H |
| Cross-camera route | None | Everything | G |

Conclusion: three of the four ANPR capabilities exist (detect, locate, read). The fourth (persist and index) is missing, and watchlist, route and GIS all depend on it. So the database and event bus are the first build items, not the last.

## 3. Target architecture: the hybrid

### 3.1 What we take from each model

| Model | We take | We reject | How the judge sees it |
|---|---|---|---|
| 1 Registry + GIS | All of it. System of record for 80,000 assets: health, bearing, ownership | Nothing | Map with layers, cluster bubbles, coverage wedges |
| 2 Unified viewing | The direct-attach stream path and the video wall | Treating direct pull as the whole architecture | Wall on HLS, expanded tile on WebRTC |
| 3 Federation middleware | The structure: pluggable drivers, event bus, one API | Nothing | Driver list in the admin page: MediaMTX, RTSP, ONVIF live; VMS stub marked "interface complete" |
| 4 Central VMS | Analytics and cross-department correlation | Central recording of 80k streams (bandwidth and storage arithmetic, Section 12) | Watchlist alerts and route across departments |

### 3.2 Component diagram

```
 Cameras / VMS (30 sandbox cams; 80,000 statewide)
   | RTSP/TCP (preferred)  | HLS (fallback)  | ONVIF  | VMS API (stub)
   v
 +---------------- FEDERATION GATEWAY (Model 3 structure) -----------------+
 |  CameraSource drivers: MediaMTXSource | RTSPSource | ONVIFSource | VMSSource |
 |  transport probe . health monitor . PTS timestamps . registry sync         |
 +---------------+--------------------------------------------+-------------+
                 | decoded frames (5 fps, 960 px)              | stream URLs
                 v                                             v
 +-------- INFERENCE WORKER (per GPU) --------+       +---- VIDEO WALL ----+
 | NVDEC decode -> batch -> YOLOv8s (TRT FP16) |       | HLS grid (hls.js)  |
 | -> ByteTrack -> plate det -> OCR x3 vote    |       | WHEP expanded tile |
 | -> ReID -> sighting rows (~200 B)           |       +--------------------+
 +--------------+------------------------------+
                | Redis Streams (demo) / Kafka (scale)
                v
 +------------ CORE API (FastAPI) --------------------------------------+
 | persister -> Postgres + TimescaleDB + pgvector + pg_trgm; MinIO crops |
 | matcher   -> watchlist bands -> alerts (state machine)                |
 | ws-fanout -> WebSocket to consoles (scoped by RBAC)                   |
 | route     -> plate route + ReID corroboration + OSRM snap             |
 | auth/RBAC -> JWT, scope filters, RLS, grants, hash-chained audit      |
 +----------------------------+-----------------------------------------+
                              v
              GIS CONSOLE (Leaflet): basemap . assets . events . route
```

### 3.3 Protocol map (one protocol per job)

| Path | Protocol | Why this one | Owner |
|---|---|---|---|
| Camera to inference worker | RTSP over TCP; fallback HLS; optional WHEP | Lowest delay and full frames. Our network blocks 8554, so the gateway probes per camera and degrades to HLS. This is the heterogeneity tolerance the brief tests | STREAM |
| Gateway to video wall | HLS | Works through restricted networks, buffers over jitter; 3 to 6 s delay is fine for a monitoring wall (D5) | UI |
| Gateway to one expanded tile | WebRTC via WHEP (WHEP = the standard HTTP handshake a browser uses to receive a WebRTC stream) | Under one second. When a judge clicks a camera after an alert, delay matters. MediaMTX already serves WHEP | UI |
| Server to console (alerts, boxes, health, route updates) | WebSocket | Push, not poll. Replaces the 800 ms loop. Alerts feel instant | DATA |
| Worker to core (sightings) | Redis Streams (demo), Kafka (scale story) | Decouples ingest rate from database write rate. The brief names Kafka/RabbitMQ under Models 3 and 4 | DATA |
| Worker to model server | In-process TensorRT (phase 1); gRPC to Triton (phase 2) | Batching across cameras; one interface, two backends | MODEL |
| Console to API | REST (JSON) with JWT | Standard CRUD, easy to test, easy to demo with curl | DATA |
| Gateway to ONVIF camera | ONVIF (SOAP over HTTP) | Discovery, stream URI, PTZ control | STREAM |

MediaMTX reads and serves RTSP, WebRTC (WHEP), HLS, SRT and RTMP and converts between them, so the sandbox supports every path above without extra software.

### 3.4 The atom: the sighting record

Everything else reads this row. About 200 bytes.

```json
{
  "sighting_id": "01J6...",
  "camera_id": "GJ-AHD-0123",
  "track_id": 4821,
  "pts_first": "2026-09-14T10:41:03.120+05:30",
  "pts_last":  "2026-09-14T10:41:05.960+05:30",
  "ts_source": "rtsp_pts",
  "plate_text": "GJ01AB1234",
  "plate_norm": "GJ01AB1234",
  "plate_canon": "GJ01A81234",
  "plate_conf": 0.91,
  "plate_band": "CONFIRMED",
  "vehicle_class": "car",
  "colour": "white",
  "bbox": [412, 220, 688, 410],
  "reid_vec_id": "vec:...",
  "crop_uri": "s3://crops/GJ-AHD-0123/2026/09/14/01J6....jpg"
}
```

Field notes: `sighting_id` is a ULID (a unique id that sorts by creation time). `ts_source` is one of `rtsp_pts`, `hls_pdt`, `server_receive` (Section A6). `plate_text` is null when the vote fails (Section B3). `plate_canon` is the confusion-class form (Section G2). `plate_band` is CONFIRMED, PROBABLE, POSSIBLE or NONE. The Re-ID vector itself lives in pgvector; the row holds a pointer.

### 3.5 Interface-first rule

Four interfaces, each with live implementations and clearly labelled stubs:

- CameraSource: MediaMTX, RTSP, ONVIF live; VMS stub.
- InferenceBackend: LocalTRT live; Triton in phase 2.
- WatchlistFeed: Manual and CSV live; VAHAN and eGujCop stubs (VAHAN = the national vehicle registry; eGujCop = the Gujarat Police case and persons system).
- AlertSink: WebSocket live; SMS and email stub.

Decision: we present the system as "federation middleware with pluggable drivers; three drivers are live today and the departmental-VMS driver is interface-complete pending vendor credentials." The sentence is true, demonstrable, and earns the hybrid bonus.

## 4. Workstream A: Federation gateway (STREAM, P0, about 2 days)

### A1 The CameraSource interface

```python
class CameraSource(Protocol):
    async def open(self) -> None: ...
    async def frames(self) -> AsyncIterator[Frame]: ...   # Frame = ndarray + pts + wall_ts + ts_source
    async def close(self) -> None: ...
    def health(self) -> Health: ...                        # LIVE | DEGRADED | DOWN | UNKNOWN
    def capabilities(self) -> set[str]: ...                # {"ptz", "events", "snapshot"}
```

### A2 The four drivers

- MediaMTXSource: what runs today. Keep it, rename it, put it behind the interface.
- RTSPSource: generic. PyAV (Python bindings for FFmpeg) with `rtsp_transport=tcp`, reconnect with exponential backoff (1 s, 2 s, 4 s, max 30 s), and a watchdog that kills a stalled connection after 10 s without frames.
- ONVIFSource: python-onvif-zeep. WS-Discovery on the LAN, GetProfiles, GetStreamUri, then hand the RTSP URL to RTSPSource. Exposes PTZ ContinuousMove and Stop. Test against any ONVIF camera or an ONVIF simulator.
- VMSSource: a stub with the method shapes of Milestone, Genetec and CP Plus APIs: `list_cameras()`, `get_stream_uri(cam_id)`, `subscribe_events()`. Returns mock data. The admin page labels it "STUB: interface complete, awaiting vendor credentials."

### A3 Transport probe

- Order: RTSP/TCP, then HLS, then (optional, P1) WHEP ingest via aiortc.
- Probe = open a socket to the RTSP port with a 2 s timeout, then send DESCRIBE. On failure, fetch the HLS playlist URL.
- Cache the result per camera in the registry (`transport_in_use`). Re-probe every 10 minutes so a fixed network upgrades itself back to RTSP.
- Say this out loud in the demo: "this camera came in on HLS because RTSP was blocked; that one came in on RTSP."

### A4 Health monitor

- Signals: connected, frames per second in the last 10 s, age of last frame, decode errors.
- Rule: LIVE if fps is at least 60% of expected and the last frame is under 3 s old; DEGRADED if fps is below that or the last frame is 3 to 15 s old; DOWN if no frame for 15 s or connect keeps failing; UNKNOWN before the first probe.
- Publish a `camera.health` event on every change; the console pin recolours within one second.

### A5 Camera registry (Model 1) schema

```sql
CREATE TABLE cameras (
  camera_id        text PRIMARY KEY,
  name             text NOT NULL,
  owner_dept_id    int  NOT NULL REFERENCES departments(id),
  district_code    text NOT NULL,
  install_type     text NOT NULL,          -- FIX | PTZ | RLVD
  lat              double precision,
  lon              double precision,
  coord_source     text,                   -- gps | manual | district_centroid
  coord_conf       text,                   -- HIGH | MEDIUM | LOW
  bearing_deg      real,                   -- 0 = north, clockwise
  fov_deg          real DEFAULT 70,
  range_m          real DEFAULT 60,
  lane_bearing_deg real,                   -- for wrong-way rule (B6)
  transports       jsonb,                  -- {"rtsp": "...", "hls": "...", "whep": "..."}
  transport_in_use text,
  driver           text NOT NULL,          -- mediamtx | rtsp | onvif | vms
  health           text DEFAULT 'UNKNOWN',
  health_at        timestamptz,
  updated_at       timestamptz DEFAULT now()
);
```

### A6 Timestamps

- RTSP: PyAV gives `frame.pts * stream.time_base`; RTCP sender reports map that to NTP wall time. Store `ts_source = rtsp_pts`.
- HLS: use `EXT-X-PROGRAM-DATE-TIME` from the playlist when present (`hls_pdt`); otherwise the gateway receive time (`server_receive`, shown as approximate in the UI).
- All hosts run chrony (an NTP client that keeps clocks in agreement) so clocks agree within milliseconds. Route ordering across cameras depends on this.

Task list:
1. Extract the interface; wrap the existing HLS code as MediaMTXSource.
2. Write RTSPSource with reconnect and watchdog.
3. Write the probe and registry fields; migrate the camera JSON into the table.
4. Write ONVIFSource; test discovery and PTZ with a simulator.
5. Write the VMSSource stub with typed method signatures and mock data.
6. Health monitor to Redis event to WebSocket.

Decision: RTSP/TCP is the default ingest; HLS is the automatic fallback; every camera row records which transport it uses and why.

## 5. Workstream B: Models (MODEL, P0 for B0 to B4, P1 for B5, P2 for B6)

Rule for the whole workstream: start from a pretrained checkpoint, fine-tune on the given dataset plus sandbox frames, measure on a hand-verified golden set, export to TensorRT, and verify the exported model gives the same numbers as the PyTorch model.

### B0 Dataset pipeline (day 1 to 2)

- Sources: the dataset supplied by the organisers, plus frames sampled from the 30 sandbox cameras (one frame every 10 s for 48 hours is about 500k frames; keep the 20k with the most vehicles).
- Labelling: run the pretrained models to pseudo-label (pseudo-label = a machine guess that a human corrects), then correct in Label Studio or CVAT. Humans correct boxes and type plate text; nobody draws from zero.
- Golden set: 300 plate crops and 300 full frames, labelled twice by two people, disagreements resolved together. This set is never trained on. Every accuracy number in the deck comes from this set.
- Splits: by camera and by day, never by frame. Frames from the same clip in train and val leak (temporal leakage) and inflate scores.
- Checks before any training run: RGB order (OpenCV gives BGR), box format (YOLO uses normalised centre-x, centre-y, width, height), no duplicate images across splits, smallest plate at least 16 px wide (below about 8 px nothing trains), at least 200 examples of the rarest vehicle class, EXIF rotation stripped.
- Versioning: DVC tracks the dataset; every MLflow run logs the dataset hash. A data card (one page: where the frames came from, camera mix, day and night mix, class counts) goes in the deck appendix.

### B1 Vehicle detector (fine-tune YOLOv8s)

- Start: `yolov8s.pt` (COCO pretrained). COCO already knows car, bus, truck and motorcycle; we fine-tune to Indian classes: two_wheeler, three_wheeler, car, lcv (light commercial vehicle), bus, truck, tractor.
- Config: imgsz 640 (960 for cameras that see vehicles far away), epochs 100 to 150, batch 16, lr0 0.01, cosine schedule, mosaic on, close_mosaic 10, mixup 0.1, box loss weight 7.5, cls loss weight 0.5. Augment for night, rain, headlight glare and motion blur with Albumentations, always with BboxParams so boxes move with the image.
- Target: mAP50 at least 0.85 on val and at least 0.80 on the golden set (mAP50 = detection accuracy averaged over classes at 50% box overlap); per-class breakdown reported, not just the average.
- NMS: IoU 0.45 default; 0.30 on dense junction cameras where two-wheelers overlap.
- Export: ONNX opset 17, simplified, FP32; then `trtexec --fp16`. Assert PyTorch and ONNX outputs agree (rtol 1e-3) and that the mAP drop after TensorRT is under 0.5 point.
- Speed reference: YOLOv8s runs about 11 ms per image in PyTorch on an RTX 4090 and about 25 ms with TensorRT on a Jetson Orin; batched TensorRT FP16 on a desktop GPU lands at 2 to 3 ms per image. Re-measure on our GPU before the slide.

### B2 Plate detector (keep D20, re-validate)

- Run it on vehicle crops, not full frames (two-stage). A plate that is 20 px wide in a 1920 px frame becomes about 60 px in a 640 px vehicle crop; small-object recall goes up for free.
- Input 320 px, batched across vehicles.
- Golden-set target: recall at least 0.95 at IoU 0.5, precision at least 0.95.
- Extra augmentation if retraining: motion blur, low light, rain streaks, JPEG compression.

### B3 Plate OCR (three readers, one vote, one grammar)

- Reader 1: Awiros (D14), as today.
- Reader 2: PaddleOCR recognition model (SVTR or CRNN head) fine-tuned on Indian plate crops. Character set A to Z and 0 to 9. 2,000 to 5,000 labelled crops gives a large gain because the pretrained model already reads Latin text; we teach it plate fonts, two-line plates and Indian spacing.
- Reader 3 (P1): PARSeq (a transformer text recogniser) trained on the same crops. Three independent readers make the 2/3 vote (D18) meaningful.
- Grammar (structure prior): Indian plates follow `^[A-Z]{2}[0-9]{2}[A-Z]{1,3}[0-9]{4}$` (state code, district number, series, number) or the BH series `^[0-9]{2}BH[0-9]{4}[A-Z]{1,2}$`. Positions that must be letters convert 0 to O, 1 to I, 8 to B, 5 to S; positions that must be digits convert the other way. This single rule removes most confusion-class errors before any voting.
- Multi-frame voting: for every track, pick up to 8 frames with the sharpest plate crop (variance of the Laplacian, a cheap blur score). Read each, align by position, vote per character with reader confidence as the weight. Emit `plate_text` only when a 2/3 majority holds across readers and frames; otherwise emit null, keep the best crop, and let the Re-ID vector carry the sighting.
- Metrics on the golden set: exact-match rate, character error rate (CER = share of wrong characters), and precision at each band (CONFIRMED, PROBABLE, POSSIBLE). The deck shows precision per band and states recall honestly: 13% of real plates are unreadable (D17); we report nothing rather than a wrong plate.

### B4 Tracker (ByteTrack, no training)

- One tracker instance per camera, kept alive across frames (a new instance per frame resets IDs).
- track_thresh 0.25, track_buffer 30 frames (about 6 s at our 5 fps sampling), match_thresh 0.8.
- One sighting per track: created at the first frame, closed 6 s after the last frame, carrying the best plate read and the best crop.

### B5 Vehicle Re-ID (P1, pretrained plus self-supervised fine-tune)

- Start: OSNet from torchreid or a fast-reid model trained on VeRi-776 (a public vehicle Re-ID dataset). Output: a 512-dimension vector; the same vehicle gives similar vectors across cameras.
- Fine-tune without manual labels: same track = same vehicle (positive pair); different tracks on the same camera at the same time = different vehicles (negative pair). Triplet loss, 10 epochs. This adapts the model to our cameras' viewpoints and lighting.
- Storage: pgvector column with an HNSW index, cosine distance.
- Use: corroboration only (Section 10). Never as identity.

### B6 Bonus models (P2, pretrained only, after P0 passes end-to-end)

- Face: InsightFace (RetinaFace detection + ArcFace embedding). Watchlist persons are stored as embeddings, never as raw photos in the matcher. Bands by cosine similarity: CONFIRMED at 0.60 and above, PROBABLE 0.45 to 0.60, tuned on a small validation set. Only the Police Investigator role can add or view face entries.
- Crowd: person count per camera zone from the detector; alert when the count exceeds a per-zone threshold for 30 s.
- Anomaly: rules on tracks, no training: vehicle stopped over 60 s in a no-stop zone; wrong-way (track heading opposite to `lane_bearing_deg` in the registry); loitering (person track in a zone over 5 minutes).

### B7 Experiment discipline

- MLflow for every run: params, dataset hash, metrics, best.pt as artifact.
- Model registry names: vehicle-det, plate-det, plate-ocr, vehicle-reid, each with a version and a one-page model card (data, metrics, limits).

Decision: three fine-tuned models (vehicle detector, plate detector, plate OCR) plus one self-supervised fine-tune (Re-ID), all measured on one golden set, all exported to TensorRT with a numerical check.

## 6. Workstream C: Inference server (MODEL + STREAM, P0)

### C1 Principles

1. Decode on the GPU, once per camera.
2. Sample frames; do not run every frame. Five frames per second is enough: a car at 40 km/h moves 11 m/s and stays in a 30 m field of view for about 3 s, which gives about 13 frames per pass.
3. Batch across cameras; one big batch beats thirty small ones.
4. Heavy models on GPU with TensorRT (TensorRT = NVIDIA's compiler that turns a model into the fastest possible GPU program); tracking and business logic on CPU.
5. Ship rows, not video. The worker output is 200-byte sightings.

### C2 Pipeline per GPU worker

```
[cam 1..N] -> ffmpeg NVDEC decode (5 fps out, 960 px) -> motion gate -> shared frame queue
   -> batcher (max 16 frames or 20 ms) -> vehicle detector TRT FP16
   -> per-camera ByteTrack (CPU) -> vehicle crops -> plate detector TRT (batch)
   -> plate crops -> OCR x2/3 (batch, only tracks that still need a read)
   -> Re-ID embed (batch, once per track every 2 s)
   -> sighting builder -> Redis Streams XADD
```

### C3 Decode

- One ffmpeg subprocess per camera: `-hwaccel cuda -c:v h264_cuvid -rtsp_transport tcp -i <url> -vf fps=5,scale=960:-2 -f rawvideo -pix_fmt bgr24 pipe:1`. Frames arrive as raw bytes; Python reads a fixed size per frame.
- Note: H.264 frames depend on earlier frames, so the decoder still decodes every frame even though we keep only 5 per second. 30 cameras at 25 fps is 750 decoded frames per second, which is near the limit of a single NVDEC engine on a consumer GPU. Watch `nvidia-smi dmon` (dec%); above 90%, move some cameras to CPU decode (a modern core decodes 150 to 250 fps of 1080p H.264) or pull the camera's lower-resolution sub-stream.
- Motion gate: compare a 96 px grey thumbnail to the previous one; if under 0.5% of pixels changed, skip the frame. Empty roads at night cost nothing.

### C4 Batching rules

- Detector: batch up to 16, flush every 20 ms. At 150 frames/s the batch fills about every 100 ms; the flush timer keeps delay low when traffic is low.
- Plate detector: batch all vehicle crops from the current detector batch.
- OCR: only tracks that have no CONFIRMED read yet and whose latest crop is sharper than the best so far. Most tracks stop needing OCR after 2 to 4 reads.
- Re-ID: once per track every 2 s, batched.

### C5 Two backends, one interface

```python
class InferenceBackend(Protocol):
    def detect(self, frames: np.ndarray) -> list[Detections]: ...
    def plates(self, crops: np.ndarray) -> list[Detections]: ...
    def ocr(self, crops: np.ndarray) -> list[Reading]: ...
    def reid(self, crops: np.ndarray) -> np.ndarray: ...
```

- LocalTRT (phase 1, P0): TensorRT engines loaded in the worker process (ultralytics `.engine` export or the TensorRT Python API). Simplest, fastest to ship, no network hop.
- TritonBackend (phase 2, P1): NVIDIA Triton Inference Server holds the same engines; dynamic batching (Triton merges requests from many workers into one GPU batch); gRPC with CUDA shared memory so frames are not copied; an ensemble model chains detector, plate detector and OCR inside Triton. A config flag switches backends. This is the scale story: many CPU-only decode workers feeding a few GPU servers.
- DeepStream (NVIDIA's full video pipeline SDK) is the named upgrade path for edge boxes; we do not build on it now because its learning curve does not fit the timeline.

### C6 Budget arithmetic (put this on a slide)

- Sandbox: 30 cameras x 5 fps = 150 frames/s.
- Vehicle detector at 2 to 3 ms per frame (TensorRT FP16, batched) = 0.30 to 0.45 GPU-seconds per second, so 30 to 45% of one GPU.
- Plate detector, OCR and Re-ID together add about 10%.
- Result: one mid-range GPU runs the sandbox at about half load; one GPU handles 60 to 80 cameras at 5 fps; INT8 (8-bit weights, needs about 500 calibration images) adds another 1.5 to 2x.
- Scale: more workers. Each worker takes a camera list from the registry (consistent hashing on camera_id, so a worker restart moves the fewest cameras).

### C7 Timestamps and order

- The frame PTS from Section A6 travels with the frame through the whole pipeline. `pts_first` and `pts_last` on the sighting come from frames, never from `now()`.

### C8 Back-pressure

- Bounded queues everywhere (frame queue depth 2 per camera). When the GPU falls behind, the worker drops frames, never sightings. Drops are counted per camera and shown in Grafana.

### C9 Edge deployment story (P2 slide)

- The same worker container runs on a Jetson Orin per district. YOLOv8s with TensorRT is about 25 ms on Orin, so one Orin NX handles about 8 cameras at 5 fps. Only sightings (rows) and crops leave the district; video stays local.

### C10 Observability

- Prometheus metrics from the worker: frames decoded, frames dropped, inference p50 and p95 per model, queue depth, sightings/s, OCR vote success rate. MediaMTX exposes its own Prometheus metrics. One Grafana dashboard; a screenshot goes in the deck.

Decision: phase 1 ships LocalTRT in-process with cross-camera batching and NVDEC decode; phase 2 adds Triton behind the same interface. The budget slide shows the numbers.

## 7. Workstream D: Event bus and storage (DATA, P0, about 2 days)

### D1 Bus

- Redis Streams for the demo: stream `sightings` with consumer groups `persister`, `matcher` and `ws-fanout`. Each group reads every message once; a crashed consumer's pending messages are reclaimed with XAUTOCLAIM. Streams `camera.health` and `alerts` feed the console.
- Kafka for the scale slide: topic `sightings` partitioned by camera_id; same consumer groups.

### D2 Database: Postgres 16 + TimescaleDB + pgvector + pg_trgm

- TimescaleDB = a Postgres extension that stores time-ordered rows in time chunks (a hypertable), so "all sightings between 10:00 and 10:30" reads one chunk instead of the whole table.
- pgvector = vector similarity search inside Postgres. pg_trgm = trigram similarity (a trigram is any three consecutive characters; two strings that share many trigrams are similar), which gives cheap fuzzy plate search without OpenSearch.

```sql
CREATE TABLE departments (id serial PRIMARY KEY, code text UNIQUE, name text);
CREATE TABLE users (id serial PRIMARY KEY, username text UNIQUE, pw_hash text,
  dept_id int REFERENCES departments(id), district_code text, role text NOT NULL,
  active bool DEFAULT true);

CREATE TABLE sightings (
  sighting_id text, camera_id text REFERENCES cameras(camera_id),
  track_id bigint, pts_first timestamptz NOT NULL, pts_last timestamptz,
  ts_source text, plate_text text, plate_norm text, plate_canon text,
  plate_conf real, plate_band text, vehicle_class text, colour text,
  bbox int[], reid_vec vector(512), crop_uri text,
  PRIMARY KEY (pts_first, sighting_id));
SELECT create_hypertable('sightings', 'pts_first', chunk_time_interval => INTERVAL '1 day');
CREATE INDEX ON sightings (plate_norm, pts_first DESC);
CREATE INDEX ON sightings (plate_canon, pts_first DESC);
CREATE INDEX ON sightings (camera_id, pts_first DESC);
CREATE INDEX ON sightings USING gin (plate_norm gin_trgm_ops);
CREATE INDEX ON sightings USING hnsw (reid_vec vector_cosine_ops);

CREATE TABLE watchlist (id serial PRIMARY KEY, kind text,       -- plate | face | person
  plate_norm text, plate_canon text, face_vec vector(512), description text,
  category text, reason text, severity text, owner_dept_id int, classification text,
  added_by int REFERENCES users(id), valid_from timestamptz, valid_until timestamptz,
  source text DEFAULT 'manual');                                 -- manual | csv | vahan | egujcop

CREATE TABLE alerts (id serial PRIMARY KEY, watchlist_id int, sighting_id text,
  camera_id text, pts timestamptz, band text, state text DEFAULT 'NEW',
  count int DEFAULT 1, created_at timestamptz DEFAULT now());
CREATE TABLE alert_events (id serial PRIMARY KEY, alert_id int, from_state text,
  to_state text, by_user int, reason text, at timestamptz DEFAULT now());

CREATE TABLE access_grants (id serial PRIMARY KEY, requester int, target_dept_id int,
  case_no text NOT NULL, reason text NOT NULL, approved_by int, starts timestamptz,
  expires timestamptz NOT NULL, state text);

CREATE TABLE audit_log (seq bigserial PRIMARY KEY, at timestamptz DEFAULT now(),
  user_id int, dept_id int, action text, object_type text, object_id text,
  ip inet, reason text, grant_id int, prev_hash bytea, hash bytea NOT NULL);
```

### D3 Policies

- Compression on sightings chunks older than 7 days (Timescale typically compresses this kind of table 5 to 10x, often more).
- Retention: sightings 90 days, crops 30 days, alerts and audit log kept (audit rows are small).

### D4 Redis KV

- `plate:<plate_norm>` holds the last 50 sighting ids (list, TTL 24 h). O(1) recent lookup for the matcher and the console search box.
- `alert:dedup:<watchlist_id>:<camera_id>` with TTL 60 s: a second sighting of the same plate at the same camera within a minute increments the alert count instead of creating a new alert.

### D5 Object store

- MinIO (S3-compatible) for crops and thumbnails. Key: `crops/<camera_id>/<yyyy>/<mm>/<dd>/<sighting_id>.jpg`. The API hands out presigned URLs (temporary signed links) valid for 5 minutes, only after the scope check passes.

### D6 Migration

- One idempotent script reads the existing JSON, writes rows, keeps the JSON as backup, and prints counts before and after.

Decision: Postgres with TimescaleDB is the system of record; Redis Streams is the bus; Redis KV is the cache; MinIO holds pixels. JSON on disk retires the day this section ships.

## 8. Workstream E: Watchlist correlation and alerts (DATA, P0, about 2 days)

### E1 Watchlist

- Fields per entry: kind, plate or face or description, category (stolen vehicle, wanted person, missing person, blacklisted vehicle, suspect), reason, severity (LOW, MEDIUM, HIGH), owner department, classification, validity window, added_by, source.
- Entry paths: form in the console, CSV import (validated: header check, plate grammar check, row-level error report).

### E2 Feeds behind one interface

```python
class WatchlistFeed(Protocol):
    def pull(self, since: datetime) -> list[WatchlistEntry]: ...
```

- ManualFeed and CSVFeed: live.
- VahanFeed and EGujCopFeed: stubs with the request and response shape written down, returning sample rows, labelled "STUB". This is the integration-readiness point.

### E3 Matcher with confidence bands

Levenshtein distance = the number of single-character edits (insert, delete, replace) needed to turn one string into another. GJ01AB1234 to GJ01A81234 is distance 1.

| Band | Rule | Operator sees |
|---|---|---|
| CONFIRMED | exact match on plate_norm, and the sighting's own plate_band is CONFIRMED | solid red pin, sound |
| PROBABLE | distance 1 where the edit is a known confusion pair (0/O, 1/I, 8/B, 5/S, 2/Z, 6/G) | amber pin |
| POSSIBLE | distance 2, or distance 1 outside the confusion pairs | grey pin, list only |

- Algorithm: look up `plate_canon` (Section G2) in Redis and in the watchlist index first (O(1)); then rank candidates by weighted Levenshtein where confusion-pair substitutions cost 0.5. Trigram search is the fallback for distance-2 queries.
- The matcher consumes the `sightings` stream, so every sighting is checked within milliseconds of persistence.

### E4 Alert record and state machine

- One alert per (watchlist entry, camera, 60 s window). States: NEW, then ACKNOWLEDGED, then ACTIONED or DISMISSED. DISMISSED requires a reason. Every transition writes an `alert_events` row and an audit row with who and when.
- The API enforces the machine: an illegal transition returns HTTP 409.

### E5 Push

- FastAPI WebSocket endpoint `/ws`. The client sends its JWT in the first message; the server computes the user's scope once and subscribes the socket to `alerts`, `camera.health` and `sightings` filtered by that scope.
- Message types: `alert.new`, `alert.state`, `camera.health`, `sighting`, `route.progress`. Heartbeat every 15 s; the client reconnects with backoff and asks for anything missed since its last sequence number.
- This endpoint replaces the 800 ms polling loop completely.

### E6 Latency target

- Camera to alert on console: 2 s or less on the RTSP path, 6 s or less on the HLS path (HLS segment delay is the floor, not our code). Measure both and put both numbers on the slide.

Decision: alerts are graded records with an enforced state machine, pushed over WebSocket; we never claim zero false positives, we claim graded and auditable ones.

## 9. Workstream F: GIS console (UI, P0 for F0 to F4, P1 for the F5 extras)

### F0 Coordinate ground-truthing (prerequisite, first weekend)

- Why first: a route drawn on district-centroid coordinates shows a car teleporting. This is a demo killer.
- Procedure per camera: take the sandbox metadata; open the live frame; find a landmark (junction name, shop sign, bridge); place the pin on the basemap at that landmark; set the bearing from what the frame looks at; record `coord_source = manual` and `coord_conf`.
- 30 cameras x 4 minutes is about 2 hours. Cameras we cannot place stay LOW confidence and render with a dotted outline.

### F1 Layer 1: basemap

- Muted grey tiles (OpenStreetMap-based, Positron style) as the default; satellite as a toggle. Never satellite by default, because pins become unreadable.

### F2 Layer 2: assets

- Leaflet.markercluster: numbered bubbles when zoomed out, splitting as you zoom in; 80,000 pins stay usable.
- Pin colour = health (green LIVE, amber DEGRADED, red DOWN, grey UNKNOWN); icon shape = install type (FIX, PTZ, RLVD).
- Coverage wedge per fixed camera: a translucent polygon from the camera position, from bearing minus fov/2 to bearing plus fov/2, out to `range_m`. A small drag handle at the wedge tip rotates the bearing and saves it to the registry (next to the existing drag-to-move).
- Click a pin: side panel with metadata, a live thumbnail (refreshed every 5 s from the gateway snapshot), health history, and "open in wall".

### F3 Layer 3: events

- Detections as small transient dots (fade after 30 s); alerts pulse red until acknowledged.
- Time slider at the bottom: drag to a window and the layer shows only events in that window (`GET /events?from&to&bbox`). The last 6 hours are preloaded so dragging is instant.

### F4 Layer 4: route (the test case)

- Input: plate and time window. Output: numbered pins 1 to N, a line drawn in sequence with a short animation, each pin labelled with camera name and time, plate crop thumbnail on hover.
- Snapping: run osrm-backend in Docker with an India or Gujarat OpenStreetMap extract; call the route service with the hop coordinates as waypoints; draw the snapped path. Legend text: "sighting order, road-snapped between sightings; not a GPS track."
- Probable hops (Section 10) draw dashed in a different colour, labelled "probable (Re-ID)".
- Implausible hops (Section 10) show a warning icon with the implied speed.
- Table below the map with the same rows; export CSV (server-side) and PDF (server-side with WeasyPrint: table plus a static map image). Every export writes an audit row.

### F5 Video wall

- Grid of HLS tiles with hls.js. Click a tile and it expands and switches to WebRTC via WHEP (the `/whep` path on MediaMTX); if WebRTC fails to connect within 3 s, fall back to HLS and show a small badge.
- Health badge on each tile; PTZ arrows appear only on ONVIF cameras (P1).
- A wall preset "alert view" opens the alerting camera plus its two nearest neighbours by road distance.

Decision: four layers with a toggle panel, cluster bubbles, coverage wedges, a time slider and a road-snapped route; coordinates are ground-truthed before any route demo.

## 10. Workstream G: Cross-camera tracking (DATA + MODEL, P0 core, P1 corroboration)

### G1 Identity rule

- Plate is the identity. It is the only key that is legally meaningful and joinable to VAHAN.
- Re-ID is corroboration. A Re-ID match never creates a confirmed hop; it only adds a "probable" hop next to confirmed ones.
- The two never share a field. `plate_band` and `reid_similarity` are separate columns.

### G2 Normalisation and the canonical key

- `plate_norm`: uppercase; remove spaces, hyphens, dots and the "IND" prefix. "GJ 01 AB-1234" and "gj01ab1234" become the same key.
- `plate_canon`: apply the confusion classes to plate_norm: {0,O,D,Q} to 0, {1,I,L} to 1, {8,B} to 8, {5,S} to 5, {2,Z} to 2, {6,G} to 6. A misread lands in the same bucket as the truth; ranking inside the bucket uses weighted Levenshtein. Cheap, and no search engine needed.
- The grammar in B3 runs before both, so most confusions are already fixed by position.

### G3 Route query

1. `SELECT ... FROM sightings WHERE plate_norm = :p AND pts_first BETWEEN :from AND :to ORDER BY pts_first` gives the confirmed hops.
2. Plausibility: for consecutive hops compute haversine distance divided by the time gap = implied speed. Above 150 km/h, flag the lower-confidence hop as IMPLAUSIBLE and still show it; never delete silently. Two sightings 200 km apart 90 s apart means one is wrong, and the judge sees that we caught it.
3. Corroboration (P1): for each gap between confirmed hops, find sightings with `plate_text IS NULL` (or band POSSIBLE) on cameras reachable within the gap at 120 km/h or less, with cosine similarity of 0.75 or more to the Re-ID vector of an adjacent confirmed hop. Return them as PROBABLE hops.
4. Fuzzy fallback: if step 1 returns nothing, retry with `plate_canon` and trigram similarity of 0.7 or more, and label the result set "fuzzy match; verify plate."

### G4 Output contract

```json
{ "plate": "GJ01AB1234", "from": "...", "to": "...",
  "hops": [
    {"n": 1, "camera_id": "...", "name": "...", "lat": 23.02, "lon": 72.57,
     "pts": "...", "kind": "CONFIRMED", "band": "CONFIRMED", "crop_url": "...",
     "implied_speed_kmh": null, "flag": null},
    {"n": 2, "kind": "PROBABLE", "reid_similarity": 0.81},
    {"n": 3, "kind": "CONFIRMED", "implied_speed_kmh": 412, "flag": "IMPLAUSIBLE"}
  ],
  "snapped_geometry": "<GeoJSON LineString>" }
```

Decision: plate-keyed route with time ordering from TimescaleDB, plausibility flags, and Re-ID probable hops drawn dashed. This is honest and stronger than four solid hops.

## 11. Workstream H: RBAC and audit (DATA, P0 for H1 to H3 and H5 logging, P1 for H4 and the hash chain)

### H1 Who you are (auth)

- JWT (a signed token the browser sends with every request) carrying user_id, dept_id, district_code and role. Access token 15 minutes, refresh token 8 hours. Passwords hashed with argon2. One bootstrap System Admin created by a CLI command.

### H2 What you can see (scope at the data layer)

- A FastAPI dependency turns the JWT into a `Scope` object: allowed department ids (own department plus any active grants), district, role.
- Every repository function takes `scope` and adds `WHERE cameras.owner_dept_id = ANY(:depts)`, and the same for watchlist and alerts. Hiding a button is not access control.
- Postgres Row-Level Security (RLS = the database itself refuses rows the session is not allowed to see) as the backstop, keyed on a session variable set per request.
- Automated test that must pass before every demo: log in as a Transport viewer, `GET /api/cameras`, assert only Transport cameras return; repeat for watchlist and alerts.

### H3 What you can do (roles)

| Role | Live view | Detections | Watchlist read | Watchlist write | Route query | Export | Admin |
|---|---|---|---|---|---|---|---|
| Viewer (dept) | own dept | own dept | no | no | no | no | no |
| Operator | own dept | own dept | own dept | no | own dept | no | no |
| Investigator (Police) | all | all | all | own dept | statewide | yes, logged | no |
| Dept Admin | own dept | own dept | own dept | own dept | own dept | yes | users in dept |
| System Admin | no | no | no | no | no | no | config and audit only |

The last row is deliberate: the person who runs the system cannot watch the video. Say this on the slide.

### H4 Cross-department grants (P1)

- An Investigator raises a request: target department, case number, reason, duration (max 72 h). The target Dept Admin approves. The grant auto-expires. Every frame and row viewed under the grant is logged with the grant id and case number.

### H5 Audit log

- Append-only. Log who, what, when, from where, and why when a reason is required. Log every export and every live view.
- Hash chain (P1): each row stores `hash = sha256(prev_hash || row_fields)`. Changing or deleting any old row breaks every hash after it. `GET /admin/audit/verify` walks the chain and reports the first broken link. This is tamper evidence, and it is one slide.

### H6 The privacy answer

- No central video recording; only sighting rows and small crops with retention limits.
- Access is purpose-bound (case number), time-boxed (grant expiry), scoped (department), and provable (hash-chained audit).
- System administrators cannot view video.

Decision: scope is enforced in SQL with RLS as backstop; roles follow the matrix; cross-department access is an explicit, expiring, logged grant; the audit log is hash-chained.

## 12. Scale story (P2, one slide with arithmetic)

- Centralised video (Model 4 storage): bandwidth = cameras x bitrate; storage = bandwidth x seconds x retention days. At 80,000 cameras this is about 160 Gbps and about 26 PB (D1). Print the formula so the jury can check it.
- Metadata instead: about 200 bytes per sighting. At 80,000 cameras and about 1,000 vehicles per camera per day that is 80 million rows per day, about 16 GB per day raw, 2 to 3 GB per day after Timescale compression. A single database server holds a year.
- Tiers: district edge workers (GPU boxes near the cameras), then Kafka (partitioned by camera_id), then central Postgres/Timescale plus an object store for crops. The watchlist is pushed down to the edge so matching happens next to the camera, and only alerts and rows travel up.
- Scaling knobs: workers per GPU, GPUs per district, Kafka partitions, consumer group size, Postgres read replicas for the console.
- What fails and what the operator sees: a district link goes down, so its pins turn red within 15 s, the edge buffers rows locally and replays when the link returns; a GPU dies, so the registry reassigns its cameras to the next worker within 30 s.

Decision: we reject centralised recording with numbers, and we scale by adding edge workers, not by adding bandwidth.

## 13. Security and privacy

- TLS on every HTTP, WebSocket and RTSPS path that leaves a host; secrets in environment files, never in the repo.
- Signed, short-lived URLs for crops; scope check before signing.
- Rate limiting on login and on the route endpoint; plate input validated against the grammar before it reaches SQL; parameterised queries everywhere.
- Least privilege for service accounts: the worker can only XADD to Redis and PUT to the crops bucket.
- Retention enforced by Timescale policies and a MinIO lifecycle rule.

Decision: security is a set of defaults in the code, not a slide.

## 14. Testing plan

- Unit: normaliser, canonical key, grammar correction, matcher bands, plausibility filter, state machine transitions, hash chain verify.
- Integration (the one that matters): `ffmpeg -re -stream_loop -1 -i clip.mp4 -c copy -f rtsp rtsp://mediamtx:8554/test` publishes a recorded clip with a known plate into MediaMTX; the whole pipeline runs; the test asserts a sighting row, a CONFIRMED alert and a WebSocket message within 3 s. This replays the judge scenario on demand.
- Accuracy: the golden-set report (Section B0) regenerated by one command; numbers go to the deck from the report, never typed by hand.
- Load: 200 looped clips as 200 cameras; watch GPU load, queue depth and drop rate; record the camera count where the worker starts dropping.
- Chaos: kill a driver process (pin goes red, restarts); block the RTSP port (camera falls back to HLS); restart Postgres (workers buffer, no lost sightings); disconnect the console (WebSocket reconnects and backfills).
- Scope: the RBAC test in H2 runs in CI.

Decision: no demo without a green integration test and a fresh golden-set report.

## 15. Demo script (8 minutes) and deck map

Judge journey:

1. (0:00) Map opens. Cluster bubbles over Gujarat; zoom to Ahmedabad; pins split; wedges appear. Toggle satellite once.
2. (0:45) Click a red pin: side panel shows DOWN and health history; click "open in wall". Wall shows the HLS grid; expand one tile; the WebRTC badge shows sub-second delay.
3. (1:45) Admin page: driver list, three live, VMS stub labelled. Point at a camera that came in over HLS because RTSP was blocked.
4. (2:30) The judge adds a plate to the watchlist (form or CSV). We replay the clip with that plate into the sandbox. Within 2 s an alert pulses on the map and the console, unattended.
5. (3:30) Acknowledge, then Actioned; try to dismiss without a reason and get blocked. Show the alert_events trail.
6. (4:15) The judge types the plate in Route. Numbered pins, road-snapped line animates, one dashed probable hop, one implausible hop flagged with implied speed. Export PDF; show the audit row the export created.
7. (6:00) Log in as a Transport viewer; the same map shows only Transport cameras; the watchlist tab is absent; `curl` the API to prove the server filters, not the UI.
8. (6:45) Grafana: 30 cameras, GPU near 50%, alert latency p95. One sentence on the scale slide numbers.
9. (7:30) Close with the precision-over-recall statement: "the fusion refuses to guess below a 2/3 majority; we would rather report nothing than report the wrong vehicle to a police officer."

Deck slides, each mapped to a scoring point:
1. Problem and the hybrid (Models 1 to 4 table).
2. Architecture diagram and protocol map.
3. Drivers: three live, one interface-complete.
4. ANPR pipeline and the sighting record.
5. Model cards: fine-tuned vehicle detector, plate detector, OCR; golden-set precision per band; D17 honesty.
6. Watchlist bands, alert state machine, latency numbers.
7. Route with plausibility and Re-ID corroboration.
8. RBAC matrix, grants, hash-chained audit.
9. Scale arithmetic and edge tiers.
10. Roadmap: VAHAN and eGujCop adapters, Triton, DeepStream, face, crowd, anomaly.

## 16. Timeline and team split

Today is 28 August. The portal says the challenge starts in September; align sprint ends to the official dates the moment they are published.

| Sprint | Dates | Goal | Exit test |
|---|---|---|---|
| 0 | 28 to 31 Aug | Freeze scope. Ground-truth 30 cameras (F0). Postgres/Timescale up, migration done (D). Driver interface extracted (A1, A2 MediaMTX). | Sightings persist in Postgres from the live sandbox |
| 1 | 1 to 7 Sep | RTSPSource, probe, health (A). LocalTRT worker with batching and NVDEC (C). WebSocket push (E5). Dataset pipeline and golden set (B0). | Integration test passes on the HLS and RTSP paths |
| 2 | 8 to 14 Sep | Fine-tunes: vehicle detector, plate detector, OCR with grammar and voting (B1 to B4). Watchlist, matcher bands, alert state machine (E). Route API with plausibility (G1 to G3). | Golden-set report generated; alert within 2 s; route returns ordered hops |
| 3 | 15 to 21 Sep | GIS layers 1 to 4, wedges, slider, OSRM snap, exports (F1 to F4). RBAC scope, role matrix, audit logging (H1 to H3, H5). Wall with WHEP (F5). ONVIF driver and VMS stub (A). | RBAC test green; route demo end to end on the map |
| 4 | 22 to 28 Sep | Re-ID corroboration (B5, G3 step 3). Grants and hash chain (H4, H5). Load and chaos tests. Grafana. Deck and two full rehearsals. | Two clean rehearsals timed under 8 minutes |
| Buffer | after | Triton backend (C5 phase 2), bonus models (B6) | Only if every P0 exit test is green |

If the official window is shorter than four weeks, ship in this order and stop when time runs out: Sprint 0, then A + C + E5, then B3 + E, then G + F4, then H1 to H3, then everything else.

Team split: STREAM owns A, C3 and the F5 transport; MODEL owns B and C; DATA owns D, E, G and H; UI owns F. Daily 15-minute sync; every merge runs the unit tests and the RBAC test; the integration test runs nightly against the sandbox.

Decision: four one-week sprints with exit tests; the P0 order above is fixed.

## 17. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| OCR ceiling (D17: 13% illegible) | Route shows missing hops; judges think we missed the car | Grammar and voting raise the legible share; Re-ID probable hops fill gaps honestly; precision-over-recall framing on the slide |
| RTSP blocked at the venue too | Delay 3 to 6 s instead of under 2 s | Probe and fallback are automatic; ask the organisers for port 8554 or SRT in advance; state both delay numbers |
| Wrong coordinates | Teleporting car on the route | F0 done in Sprint 0; LOW-confidence pins drawn dotted; plausibility flags catch the rest |
| Small labelled dataset | Fine-tune overfits | Pseudo-label from pretrained, strong augmentation, split by camera, stop on val plateau, report golden-set numbers only |
| NVDEC saturates on a consumer GPU | Dropped frames on some cameras | Monitor dec%; move cameras to CPU decode or sub-streams (C3) |
| Single GPU dies during the demo | Nothing runs | Second laptop with the same containers and engines; cameras reassign from the registry in 30 s |
| Judges' network blocks WebRTC | Expanded tile blank | 3 s fallback to HLS with a badge; rehearse on a phone hotspot |
| Scope leak found by a technical juror | Loss of the RBAC bonus and of trust | RLS backstop plus the automated scope test in CI |
| Clock drift between hosts | Route order wrong across cameras | chrony on every host; ts_source stored; UI flags approximate timestamps |

## 18. Definition of done (P0)

- [ ] Sightings persist in Postgres/Timescale from live sandbox streams with PTS timestamps.
- [ ] Four drivers behind CameraSource; the probe picks RTSP or HLS per camera; health pins recolour within 1 s.
- [ ] Worker runs NVDEC decode, cross-camera batching, TensorRT FP16 for the detector and plate detector; Grafana shows per-camera fps and p95.
- [ ] Vehicle detector, plate detector and OCR fine-tuned from pretrained checkpoints; golden-set report with per-band precision.
- [ ] Watchlist with manual and CSV feeds; matcher with three bands; alerts with an enforced state machine; WebSocket push in 2 s or less on RTSP.
- [ ] Route API with time ordering and plausibility flags; map layer with numbered pins, road-snapped line, and exports that write audit rows.
- [ ] GIS: four layers, cluster, wedges with drag-to-rotate bearing, time slider, satellite toggle.
- [ ] Wall: HLS grid, WHEP expanded tile with fallback.
- [ ] RBAC: scope enforced in SQL, role matrix, audit logging; automated scope test green.
- [ ] Integration test replays a clip and asserts row, alert and WebSocket message.
- [ ] Deck with the ten slides; two rehearsals under 8 minutes.

## 19. Glossary

- ANPR: reading a vehicle's number plate from video and producing a text record.
- VMS: the software a department uses to record and view its own cameras.
- Federation middleware: one platform that talks to many different camera systems through adapters (drivers).
- Driver: a small piece of code that knows how to talk to one kind of source (an RTSP camera, an ONVIF camera, a VMS API).
- RTSP: the standard protocol cameras use to send live video; low delay.
- HLS: video sent as small files over HTTP; works everywhere, 3 to 6 s delay.
- WebRTC / WHEP: browser video with under one second delay; WHEP is the handshake used to receive it.
- SRT: a low-delay video transport that works over a single UDP port; a fallback if RTSP is blocked.
- WebSocket: a two-way connection between browser and server; the server can push messages without the browser asking.
- ONVIF: a standard for talking to IP cameras (discovery, stream URL, pan-tilt-zoom).
- PTS: presentation timestamp, the time stamped on each video frame by the camera or stream.
- NTP / chrony: keeps computer clocks in agreement.
- TensorRT: NVIDIA's model compiler for fast GPU inference. FP16 and INT8 are lower-precision number formats that run faster.
- NVDEC: the video decoder chip inside NVIDIA GPUs.
- Triton: NVIDIA's model server that batches requests from many clients.
- Dynamic batching: merging requests that arrive close in time into one GPU call.
- ByteTrack: an algorithm that links detections across frames into tracks with stable IDs.
- Re-ID: a model that turns a vehicle image into a vector so the same vehicle looks similar across cameras.
- Fine-tuning: continuing the training of a pretrained model on our own data.
- Pseudo-label: a model's guess used as a starting label that a human corrects.
- Golden set: a small, hand-verified test set never used for training.
- Temporal leakage: frames of the same clip in both training and test data, which inflates scores.
- mAP50: detection accuracy averaged over classes at 50% box overlap.
- CER: character error rate, the share of wrong characters in text reading.
- Levenshtein distance: the number of single-character edits between two strings.
- Trigram (pg_trgm): three-letter chunks used to find similar strings quickly.
- Hypertable (TimescaleDB): a Postgres table split into time chunks for fast time-range queries.
- pgvector / HNSW: vector storage and a fast index for similarity search.
- Redis Streams: an append-only message log with consumer groups.
- Kafka: a distributed message log for very high volume.
- ULID: a sortable unique id that encodes creation time.
- JWT: a signed token that carries a user's identity and role.
- RLS: row-level security, the database enforcing who can see which rows.
- Hash chain: each log row includes the hash of the previous one, so edits are detectable.
- OSRM: an open-source routing engine that snaps points to roads.
- Haversine: the formula for distance between two latitude/longitude points.
- Prometheus / Grafana: metrics collection and dashboards.
- MinIO: an S3-compatible object store for files.

## 20. Sources

- Portal wording on ANPR, watchlist categories, Models 1 to 4 and the auditability/RBAC bonus: our CONTEXT.md notes copied from sentinel.gujarat.gov.in. The portal blocks automated fetch; verify against the live page before the deck is final.
- IANS via Prokerala, 17 Aug 2026: two-stage format, two categories, six finalists, live production environment, Rs 37 lakh, September start, i-Hub, DA-IICT and NFSU partners. https://www.prokerala.com/news/articles/a1801331.html
- Gujarat Samachar, Aug 2026: first initiative in India that tests on live camera feeds; scalable ecosystem across vendors, VMS platforms and networks. https://english.gujaratsamachar.com/news/gujarat/gujarat-police-to-link-80000-cctv-cameras-in-states-largest-ai-based-video-analytics-hackathon-80179505714
- Open Magazine, Aug 2026: finale demo in a live production environment, prize pool. https://openthemagazine.com/india/can-80000-cameras-think-as-one-inside-gujarat-polices-mega-ai-hackathon
- ANI, 17 Aug 2026: September 2026 start. https://www.aninews.in/news/national/general-news/gujarat-police-to-host-countrys-largest-ai-based-cctv-hackathon20260817135250/
- MediaMTX (bluenviron) README: reads and serves RTSP, WebRTC (WHEP), HLS, SRT and RTMP with automatic protocol conversion; Prometheus metrics. https://github.com/bluenviron/mediamtx
- Speed figures for YOLOv8s (PyTorch on RTX 4090, TensorRT on Jetson Orin), training defaults and export checks come from our senior-computer-vision-engineer skill file; re-measure on our GPU before the slide.
