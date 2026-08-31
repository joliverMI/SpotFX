"""DOES A WAVE TRAVEL THROUGH A COPY-MAPPED CARRIER? Answered on the real
render pipeline, before anything was built on the assumption either way.

THE QUESTION, and why it had to be answered first (the captain's order, from
his second failed run): the room map drives a wave with a PER-PIXEL GAIN MASK
(fx/virtual_gain_mask.py, fx/VENDOR.md deviation #25). His `tv-mapper` is a
COPY-mapped virtual — it renders one segment's worth of pixels and copies
that to every segment. If the mask multiplies BEFORE the copy, then every
segment receives the same masked pattern and a "travelling" wave appears in
all of them at once: it cannot travel along the physical run at all, and any
wave over that carrier is a lie. If it multiplied AFTER, a copy carrier would
be a perfectly good wave surface and the whole question is moot.

WHAT THIS MEASURES: the DEVICE's own pixel buffer — what the driver receives
after `assemble_frame()` and `flush()`, which is downstream of both the mask
multiply and the copy expansion — with a mask that is 1.0 over the first half
of the effect buffer and 0.0 over the second. A span virtual is rendered
beside it as the control, with the identical mask.

  * SPAN: the dark half must be the second half of the PHYSICAL run — one
    dark region, at the top of the strip. A wave travels.
  * COPY: if the dark region REPEATS once per segment, the mask was applied
    before the copy and the answer is NO TRAVEL.

Run from repo root: .venv/bin/python scripts/check_copy_carrier_wave.py
Isolated: temp fx config, one dummy device, audio silenced. No LedFX, no
network, no live storage.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print = __import__("functools").partial(print, flush=True)   # noqa: A001

FAILURES: list[str] = []


def check(cond, label):
    if not cond:
        FAILURES.append(label)
        print(f"FAIL: {label}")
        return False
    print(f"ok: {label}")
    return True


td = Path(tempfile.mkdtemp(prefix="spectra-copywave-"))

from fx import device_model                                   # noqa: E402
device_model.CATEGORIES_FILE = td / "device_categories.json"
device_model.CATEGORIES_FILE.write_text(json.dumps({}))

from fx import headless, virtual_gain_mask                    # noqa: E402
from fx.host import FxHost                                    # noqa: E402

DEVICE = "tv"
PIXELS = 60
RUN = 20                     # three runs of twenty, his wrap's shape


def _write_config(config_dir: str, mapping: str) -> None:
    os.makedirs(config_dir, exist_ok=True)
    from fx.consts import CONFIGURATION_VERSION
    with open(os.path.join(config_dir, "config.json"), "w") as fh:
        json.dump({"configuration_version": CONFIGURATION_VERSION,
                   "devices": [{"id": DEVICE, "type": "dummy",
                                "config": {"name": DEVICE,
                                           "pixel_count": PIXELS}}],
                   "virtuals": [{"id": "carrier", "is_device": DEVICE,
                                 "auto_generated": False,
                                 "config": {"name": "carrier",
                                            "mapping": mapping, "rows": 1},
                                 "segments": [
                                     [DEVICE, 0, RUN - 1, False],
                                     [DEVICE, RUN, 2 * RUN - 1, False],
                                     [DEVICE, 2 * RUN, PIXELS - 1, False]]}]},
                  fh)


async def device_pixels(mapping: str, mask) -> np.ndarray:
    """The DEVICE's own buffer after one rendered, flushed frame."""
    headless.silence_audio()
    _write_config(str(td / f"fx-{mapping}"), mapping)
    host = FxHost(str(td / f"fx-{mapping}"))
    await host.start()
    host.audio = headless.SyntheticAudioSource()
    virtual = host.virtuals.get("carrier")
    headless.attach_effect(host, virtual, "singleColor",
                           {"color": "#ffffff", "brightness": 1.0,
                            "background_brightness": 0.0})
    virtual_gain_mask.clear()
    if mask is not None:
        virtual_gain_mask.apply_masks({"carrier": mask})
    frame = virtual.assemble_frame()
    virtual.flush(frame)
    device = host.devices.get(DEVICE)
    out = np.asarray(device.assemble_frame(), dtype=float).copy()
    virtual_gain_mask.clear()
    return out


def dark_runs(pixels: np.ndarray) -> list[tuple[int, int]]:
    """Contiguous stretches of physical pixel that came out dark."""
    dark = pixels.mean(axis=1) < 8.0
    runs, start = [], None
    for i, d in enumerate(dark):
        if d and start is None:
            start = i
        elif not d and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(dark) - 1))
    return runs


async def main() -> int:
    print("== the question: does the gain mask multiply BEFORE or AFTER a "
          "copy-mapped virtual's copy step? ==")

    # 1.0 over the first half of the EFFECT buffer, 0.0 over the second.
    span_mask = np.concatenate([np.ones(PIXELS // 2), np.zeros(PIXELS // 2)])
    span = await device_pixels("span", span_mask)
    span_dark = dark_runs(span)
    check(span_dark == [(PIXELS // 2, PIXELS - 1)],
          f"SPAN (the control): one dark region, exactly the second half of "
          f"the physical run {span_dark} — a gain at a pixel reaches THAT "
          f"pixel, which is what lets a wave travel along the strip")

    # A copy carrier renders ONE segment's worth of effect pixels.
    copy_mask = np.concatenate([np.ones(RUN // 2), np.zeros(RUN - RUN // 2)])
    copy = await device_pixels("copy", copy_mask)
    copy_dark = dark_runs(copy)
    repeated = copy_dark == [(RUN // 2, RUN - 1), (RUN + RUN // 2, 2 * RUN - 1),
                             (2 * RUN + RUN // 2, PIXELS - 1)]
    check(repeated,
          f"COPY: the dark region REPEATS once per segment {copy_dark} — the "
          f"mask multiplied the effect buffer BEFORE the copy expanded it, so "
          f"every segment receives the same masked pattern")
    check(len(copy_dark) > 1,
          "THE ANSWER: BEFORE. A wave cannot TRAVEL along a copy-mapped "
          "carrier — its phase is identical in every segment at every "
          "instant, so 'a wave from the floor to the ceiling' is not "
          "expressible there however finely it is mapped")

    print("\n== what that means for the build ==")
    print("A copy carrier is not a wave surface. Both the CAPTURE (which "
          "lights one pixel range) and the WAVE (which dims one pixel range) "
          "must drive the device's own splittable SPAN virtual instead — the "
          "same route, for the same reason, at both ends.")

    if FAILURES:
        print(f"\nFAILED {len(FAILURES)} check(s)")
        for f in FAILURES:
            print(f"  {f}")
        return 1
    print("\nCOPY-CARRIER WAVE QUESTION ANSWERED: BEFORE THE COPY (no travel)")
    return 0


if __name__ == "__main__":
    status = 1
    try:
        status = asyncio.run(main())
    except Exception:                                          # noqa: BLE001
        import traceback
        traceback.print_exc()
    # fx's TemporalEffect spawns non-daemon threads this harness never joins
    # and FxHost.stop() refuses; a plain return would hang forever.
    os._exit(status)
