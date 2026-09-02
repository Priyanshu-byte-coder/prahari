"""I1's unit check. The ticket's Verify line is the bench; this covers the logic the bench
cannot fail on cleanly - a bench that is 3% slow looks the same as a bench whose motion gate is
inverted, and only one of those is a bug.

Everything here is pure numpy/cv2 or an in-process queue. No ffmpeg, no clip, no network.
"""

import sys
import threading
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.worker.decode import (DRIFT_BUDGET, MOTION_DELTA,  # noqa: E402
                                    _floor_band, moved, scale, thumbnail)
from services.worker.queues import FrameQueue  # noqa: E402


def frame(value, size=(720, 1280)):
    return np.full((*size, 3), value, dtype=np.uint8)


# --- bounded queues: drop frames, never sightings -------------------------------------------

def test_queue_drops_oldest_and_counts_it():
    """Depth 2 means the third frame displaces the first, and the drop is visible."""
    q = FrameQueue("CAM", depth=2)
    assert q.put("a") is False
    assert q.put("b") is False
    assert q.put("c") is True          # displaced "a"
    assert q.dropped == 1
    assert q.get() == "b"              # the oldest survivor, not "a"
    assert q.get() == "c"


def test_queue_never_grows_past_depth():
    """The property that keeps a slow GPU from becoming an OOM an hour in."""
    q = FrameQueue("CAM", depth=2)
    for i in range(1000):
        q.put(i)
    assert q.depth == 2
    assert q.dropped == 998
    assert q.stats()["drop_rate"] == pytest.approx(998 / 1000)


def test_queue_get_returns_none_when_empty():
    """None is 'nothing yet', not 'stream ended' - the consumer loops, it does not exit."""
    assert FrameQueue("CAM").get(timeout=0.01) is None


def test_queue_put_never_blocks_with_no_consumer():
    """put() must be safe on the decode thread; a block there stalls the decoder."""
    q = FrameQueue("CAM", depth=2)
    done = threading.Event()

    def fill():
        for i in range(50):
            q.put(i)
        done.set()

    threading.Thread(target=fill, daemon=True).start()
    assert done.wait(timeout=2.0), "put() blocked with a full queue and no consumer"
    assert q.dropped == 48


# --- motion gate ----------------------------------------------------------------------------

def test_first_frame_always_passes():
    """Nothing to compare against, so it cannot be judged still."""
    assert moved(None, thumbnail(frame(0))) is True


def test_identical_frames_are_not_motion():
    """The empty road at 03:00 - this is the whole saving."""
    still = thumbnail(frame(120))
    assert moved(still, thumbnail(frame(120))) is False


def test_uniform_shift_below_delta_is_not_motion():
    """A brightness drift smaller than MOTION_DELTA is the sensor, not a vehicle."""
    a = thumbnail(frame(120))
    b = thumbnail(frame(120 + MOTION_DELTA - 2))
    assert moved(a, b) is False


def test_small_moving_object_is_motion():
    """A vehicle crossing a corner of the scene must survive the gate.

    The patch is 12x12 of a 96x96 thumbnail = 1.6%, comfortably over the 0.5% threshold and
    representative of a car at the far end of a wide junction view.
    """
    before = frame(60)
    after = frame(60)
    after[:90, :160] = 220                       # ~12x12 once thumbnailed
    assert moved(thumbnail(before), thumbnail(after)) is True


def test_gate_threshold_is_a_fraction_not_a_count():
    """0.5% of a 96x96 thumbnail is ~46 pixels; 20 changed pixels must not trip it."""
    before = thumbnail(frame(60))
    after = before.copy()
    after.flat[:20] = 255
    assert moved(before, after) is False


# --- scaling --------------------------------------------------------------------------------

def test_scale_fixes_width_and_keeps_aspect():
    assert scale(frame(0, size=(720, 1280))).shape[:2] == (540, 960)


def test_scale_forces_even_height():
    """`scale=960:-2` - odd heights break yuv420p round-tripping downstream."""
    assert scale(frame(0, size=(721, 1280))).shape[0] % 2 == 0


def test_scale_never_upscales():
    """Inventing pixels costs inference time and adds no detail."""
    small = frame(0, size=(240, 320))
    assert scale(small).shape == small.shape


# --- the memory verdict ----------------------------------------------------------------------

def test_band_ignores_transient_spikes_and_working_set_trims():
    """A flat process sampled mid-decode swings ~100MB either way. That is not a leak.

    This is the series shape that made a raw least-squares fit report +112MB/min on a 60s run
    and +7.8MB/min on a 600s run of the same code.
    """
    floor = 900.0
    samples = [floor + s for _ in range(10)
               for s in (0, 8, 90, 4, -500, 12, 3, 60, 6, 1, 30, 5)]
    band, floors = _floor_band(samples)
    assert floors == [floor - 500] * 5
    assert band == pytest.approx(0.0)


def test_band_catches_a_real_leak():
    """6MB/min retained, buried under the same transient noise, must still be caught."""
    samples = [900.0 + 6.0 * (i * 5 / 60) + (70 if i % 4 else 0) for i in range(120)]
    band, _ = _floor_band(samples)
    assert band > DRIFT_BUDGET


@pytest.mark.parametrize("rate", [6, 8, 10, 15, 30, 100])
def test_band_catches_every_leak_above_the_stated_floor(rate):
    """No leak rate may hide behind the warm-up filter by being steep enough to look like one.

    The filter eats leading windows, so a fast leak reads *smaller* than a slow one - 30MB/min
    bands narrower than 15. It must still trip the budget, which is what the `len(floors) > 3`
    floor on the strip guarantees. This is the property; monotonicity is not.
    """
    samples = [900.0 + rate * (i * 5 / 60) for i in range(120)]
    assert _floor_band(samples)[0] > DRIFT_BUDGET


def test_band_drops_a_steep_warmup_ramp_but_not_a_leak():
    """Ten decoders take minutes to allocate their pools; that ramp is steep, a leak is not."""
    _, warm = _floor_band([800.0] * 24 + [880.0] * 24 + [900.0] * 72)
    assert warm == [880.0, 900.0, 900.0, 900.0]     # the 800MB window was warm-up

    _, leak = _floor_band([900.0 + 10.0 * (i * 5 / 60) for i in range(120)])
    assert len(leak) == 5                           # 1.1%/min survives the 3%/min filter


def test_band_refuses_to_judge_a_short_run():
    """Two windows cannot say anything about ten minutes - None, never a guess."""
    assert _floor_band([900.0] * 24)[0] is None
