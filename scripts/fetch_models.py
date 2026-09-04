"""Fetch the optional models the robustness path uses:
  models/plate.pt        trained licence-plate YOLO  (PRAHARI_PLATE_WEIGHTS)
  models/FSRCNN_x4.pb    super-resolution x4         (PRAHARI_SR_MODEL)

Both are optional at runtime; the pipeline falls back to the classical proposal
and Lanczos without them. Not committed (weights).
"""
from __future__ import annotations
import sys
import urllib.request
from pathlib import Path

MODELS = Path(__file__).resolve().parents[1] / "models"
MODELS.mkdir(exist_ok=True)


def fetch_plate():
    dst = MODELS / "plate.pt"
    if dst.exists():
        print(f"[=] {dst} already present"); return
    from huggingface_hub import hf_hub_download
    for repo, name in (("morsetechlab/yolov11-license-plate-detection", "yolov11m-license-plate.pt"),
                       ("keremberke/yolov8m-license-plate", "best.pt"),
                       ("keremberke/yolov8n-license-plate", "best.pt")):
        try:
            p = hf_hub_download(repo_id=repo, filename=name)
            Path(dst).write_bytes(Path(p).read_bytes())
            print(f"[+] plate detector <- {repo}/{name} -> {dst}")
            return
        except Exception as exc:
            print(f"    {repo}: {type(exc).__name__}: {str(exc)[:120]}")
    print("[-] could not fetch a plate detector; classical proposal stays in use")


def fetch_sr():
    dst = MODELS / "FSRCNN_x4.pb"
    if dst.exists():
        print(f"[=] {dst} already present"); return
    urls = [
        "https://raw.githubusercontent.com/Saafke/FSRCNN_Tensorflow/master/models/FSRCNN_x4.pb",
        "https://github.com/Saafke/FSRCNN_Tensorflow/raw/master/models/FSRCNN_x4.pb",
    ]
    for u in urls:
        try:
            urllib.request.urlretrieve(u, dst)
            print(f"[+] SR model <- {u} -> {dst} ({dst.stat().st_size // 1024} KiB)")
            return
        except Exception as exc:
            print(f"    {u}: {type(exc).__name__}: {str(exc)[:120]}")
    print("[-] could not fetch an SR model; Lanczos stays in use")


if __name__ == "__main__":
    which = sys.argv[1:] or ["plate", "sr"]
    if "plate" in which:
        fetch_plate()
    if "sr" in which:
        fetch_sr()
