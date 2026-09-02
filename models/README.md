# models/ — weights live here, and none of them are in git

Nothing in this directory is committed (`.gitignore`). Weights are large, they are not ours to
redistribute, and a 22 MB blob in a PR is how a repo stops being cloneable. Everything here is
fetched or produced by a command, and every command is in this file.

## What the worker loads

| env var | default | used by | what it is |
|---|---|---|---|
| `PRAHARI_WEIGHTS_DIR` | `models/` | all | where the files below live |
| `PRAHARI_VEHICLE_WEIGHTS` | `models/yolov8s.pt` | I2 `backend.detect` | vehicle detector |
| `PRAHARI_PLATE_WEIGHTS` | *(unset)* | I4 `backend.plates` | plate detector; unset = classical proposal |
| `PRAHARI_REID_WEIGHTS` | *(unset)* | I10 `reid.Embedder` | TorchScript re-id trunk; unset = ResNet-18 |
| `PRAHARI_OCR_GPU` | `1` | I4 readers | `0` forces EasyOCR onto the CPU |

**This is the whole of I11's swap surface.** Fine-tuned weights are a path, never a code
change: point the variable at a new file and the batcher, the tracker, the vote and the
publisher are untouched. If a model swap ever needs an edit to `backend.py`, that is a bug in
`backend.py`.

## Fetching the defaults

```bash
python -c "from ultralytics import YOLO; YOLO('yolov8s.pt')"   # writes yolov8s.pt into $PWD
mv yolov8s.pt models/
```

The ResNet-18 re-id trunk is fetched by torchvision into `~/.cache/torch` on first use. Nothing
else downloads at runtime except the OCR readers' own model files (EasyOCR into
`~/.EasyOCR`, PaddleOCR into `~/.paddlex`), which happens once, on the first crop.

## Classes

The brief names seven: `two_wheeler three_wheeler car lcv bus truck tractor`.

COCO — which is what a pretrained YOLOv8 gives us — covers four of them:

| ours | COCO | note |
|---|---|---|
| two_wheeler | motorcycle | |
| car | car | |
| bus | bus | |
| truck | truck | LCVs land here until the detector is fine-tuned |
| three_wheeler | — | **not emitted**; no COCO class, and box geometry is not evidence |
| lcv | — | **not emitted** |
| tractor | — | **not emitted** |

`backend.COCO_TO_CLASS` is the whole mapping and it contains identity entries for our own
names, so a fine-tuned model that emits `three_wheeler` directly needs no mapping change.
Anything a model emits that is not in that table is dropped, not guessed.

## Licences (contest rule: open source only)

| model | licence | note |
|---|---|---|
| YOLOv8 (ultralytics) | AGPL-3.0 | flagged in the plan as a question for the organisers; a permissive swap (RT-DETR, YOLOX) fits behind `InferenceBackend` without touching callers |
| EasyOCR | Apache-2.0 | |
| PaddleOCR | Apache-2.0 | |
| torchvision ResNet-18 | BSD-3-Clause | ImageNet weights |

## Benchmarks

```bash
python -m services.worker.backend --bench          # p50/p95 per model, batched throughput
```

Numbers from a run are quoted in `docs/model-card.md`, never typed from memory.
