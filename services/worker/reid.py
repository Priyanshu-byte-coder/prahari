"""[I10] Vehicle re-identification. 512-d appearance vector on the sighting row.

**Corroboration only, never identity.** Plate identity is the only identity (AGENTS.md). This
vector may raise a route hop to PROBABLE when the plate agrees or is missing; it may never
create a CONFIRMED hop, and it never shares a field with a plate. Two silver hatchbacks of the
same model are the same vector and a different vehicle, and no threshold fixes that.

Backbone: the ticket asks for OSNet/fast-reid on VeRi-776. Neither ships a permissively
licensed, downloadable checkpoint we could verify in this window, and the contest rule is open
source only - so the default is a torchvision ResNet-18 trunk, whose pooled feature is exactly
512-d, with `PRAHARI_REID_WEIGHTS` pointing at an OSNet TorchScript module the moment one is
vetted. Same call site, better vectors, no code change - the I2 rule applied to a second model.

When torch cannot be used at all there is a deterministic colour/texture descriptor instead. It
is weaker and it is honest about being weaker: `Embedder.kind` says which one produced a vector,
and the model card reports them separately.
"""

from __future__ import annotations

import logging
import os

import cv2
import numpy as np

logger = logging.getLogger("prahari.worker.reid")

DIM = 512                      # [C3]: vector(512), and ResNet-18's pooled width. Not a coincidence.
REID_WEIGHTS = os.getenv("PRAHARI_REID_WEIGHTS", "")
INPUT = (128, 256)             # w, h - the standard re-id aspect, taller than wide
SIMILARITY_PROBABLE = 0.82     # cosine; tuned to be conservative, see `corroborates`


class Embedder:
    """crops -> (n, 512) L2-normalised float32. Cosine similarity is then a dot product."""

    def __init__(self, device=None, weights=REID_WEIGHTS):
        self.weights = weights
        self.device = device or "cpu"
        self.kind = None
        self._model = None
        self._torch = None

    def _load(self):
        import torch
        self._torch = torch
        if self.weights:
            model = torch.jit.load(self.weights, map_location=self.device)
            self.kind = f"torchscript:{os.path.basename(self.weights)}"
        else:
            from torchvision.models import ResNet18_Weights, resnet18
            net = resnet18(weights=ResNet18_Weights.IMAGENET1K_V1)
            net.fc = torch.nn.Identity()               # pooled 512-d trunk feature
            model = net
            self.kind = "resnet18/imagenet"
        model.eval().to(self.device)
        return model

    def embed(self, crops):
        if not len(crops):
            return np.zeros((0, DIM), dtype=np.float32)
        if self._model is None:
            try:
                self._model = self._load()
            except Exception as exc:
                logger.warning("no torch re-id backbone (%s) - using the colour/texture "
                               "descriptor; vectors are not comparable across the two", exc)
                self.kind = "histogram"
                self._model = False
        if self._model is False:
            return _normalise(np.stack([descriptor(c) for c in crops]))

        torch = self._torch
        batch = np.stack([cv2.resize(c, INPUT, interpolation=cv2.INTER_AREA)[:, :, ::-1]
                          for c in crops]).astype(np.float32) / 255.0
        mean = np.array([0.485, 0.456, 0.406], np.float32)
        std = np.array([0.229, 0.224, 0.225], np.float32)
        batch = ((batch - mean) / std).transpose(0, 3, 1, 2)
        with torch.no_grad():
            out = self._model(torch.from_numpy(np.ascontiguousarray(batch)).to(self.device))
        return _normalise(out.detach().cpu().numpy().astype(np.float32))


def descriptor(crop):
    """A 512-d colour/texture histogram: 8x8x8 HSV joint histogram, no model, no download.

    Deliberately crude. It separates a red truck from a white hatchback, which is the only
    thing corroboration is allowed to claim, and it costs 0.2 ms on a CPU.
    """
    if crop is None or crop.size == 0:
        return np.zeros(DIM, np.float32)
    hsv = cv2.cvtColor(cv2.resize(crop, INPUT, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1, 2], None, [8, 8, 8], [0, 180, 0, 256, 0, 256])
    return hist.flatten().astype(np.float32)          # 8*8*8 = 512


def _normalise(vectors):
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return (vectors / np.maximum(norms, 1e-9)).astype(np.float32)


def similarity(a, b):
    """Cosine similarity of two vectors, in [-1, 1]. None-safe: an absent vector never matches."""
    if a is None or b is None:
        return 0.0
    a, b = np.asarray(a, np.float32).ravel(), np.asarray(b, np.float32).ravel()
    if a.size != b.size or not a.size:
        return 0.0
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(a @ b / denom) if denom else 0.0


def corroborates(a, b, threshold=SIMILARITY_PROBABLE):
    """True when two sightings look like the same vehicle - a PROBABLE hop and nothing more.

    Returns a bool, not a band, on purpose: the caller (D6's route) decides what to do with it,
    and there is no return value from this function that can produce a CONFIRMED hop.
    """
    return similarity(a, b) >= threshold


# --- self-supervised fine-tune ------------------------------------------------------------

def pairs(sightings):
    """(anchor, positive, negatives) from our own footage - no labels, no dataset licence.

    The supervision is free and it is the ticket's: two crops of one track are the same
    vehicle; two tracks alive on one camera at one instant are, physically, not. The second
    half is what makes it work - random negatives are trivially separable and teach nothing,
    while two vehicles under the same camera at the same second share lighting, weather,
    compression and viewpoint, so the only thing left to tell them apart is the vehicle.
    """
    by_camera = {}
    for s in sightings:
        by_camera.setdefault(s["camera_id"], []).append(s)
    out = []
    for rows in by_camera.values():
        rows.sort(key=lambda r: r["pts_first"])
        for i, anchor in enumerate(rows):
            positives = [c for c in anchor.get("crops", [])]
            if len(positives) < 2:
                continue
            overlapping = [r for r in rows[max(0, i - 8): i + 8]
                           if r is not anchor
                           and r["pts_first"] <= anchor["pts_last"]
                           and r["pts_last"] >= anchor["pts_first"]]
            negatives = [c for r in overlapping for c in r.get("crops", [])[:2]]
            if negatives:
                out.append((positives[0], positives[-1], negatives))
    return out


def fit_projection(embedder, triples, epochs=8, temperature=0.07, lr=1e-3, out=None):
    """Learn a 512x512 projection on top of the frozen trunk with InfoNCE over `pairs()`.

    A projection rather than a fine-tune of the trunk: a few thousand pairs from one grid is
    not enough data to move a backbone without overfitting it to our four cameras, and the
    projection can be dropped without re-exporting anything if it turns out not to help.
    """
    import torch
    proj = torch.nn.Linear(DIM, DIM, bias=False)
    torch.nn.init.eye_(proj.weight)
    optimiser = torch.optim.Adam(proj.parameters(), lr=lr)
    losses = []
    for _ in range(epochs):
        for anchor, positive, negatives in triples:
            vectors = torch.from_numpy(embedder.embed([anchor, positive, *negatives]))
            z = torch.nn.functional.normalize(proj(vectors), dim=1)
            logits = (z[0:1] @ z[1:].T) / temperature
            loss = torch.nn.functional.cross_entropy(logits, torch.zeros(1, dtype=torch.long))
            optimiser.zero_grad()
            loss.backward()
            optimiser.step()
            losses.append(float(loss))
    if out:
        torch.jit.save(torch.jit.script(proj), out)
    return proj, (sum(losses[-50:]) / max(1, len(losses[-50:])))


def demo():
    """Self-check: same vehicle scores above two different ones, and the band rule holds."""
    rng = np.random.default_rng(0)
    car = rng.integers(60, 200, (240, 160, 3), dtype=np.uint8)
    same = np.clip(car.astype(np.int16) + rng.integers(-12, 12, car.shape), 0, 255).astype(np.uint8)
    other = rng.integers(0, 90, (240, 160, 3), dtype=np.uint8)
    e = Embedder()
    vectors = e.embed([car, same, other])
    assert vectors.shape == (3, DIM), vectors.shape
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-4)
    near, far = similarity(vectors[0], vectors[1]), similarity(vectors[0], vectors[2])
    assert near > far, (near, far)
    assert not corroborates(vectors[0], None), "a missing vector must never corroborate"
    print(f"reid demo ok: kind={e.kind} same={near:.3f} different={far:.3f}")


if __name__ == "__main__":
    demo()
