"""DOES A SECOND ACTIVE VIRTUAL ON THE SAME FIXTURE ATTENUATE THE FIRST'S
OUTPUT? Established from the fork's own code, on the real pipeline, so the
answer is on the record whichever way it lands.

WHY IT WAS ASKED: a substituted capture (spectra/services/emitters.py::
substitutes_for) lights the device's own span virtual while the copy
carrier standing in front of it is still active and rendering the hold's
black. If the device blended two active virtuals, the black would dilute
the white and every substituted footprint would be measured too dim — which
was one candidate explanation for his first map's ~10x-dim weights.

THE ANSWER, from fx/devices/__init__.py:

  * `Device.update_pixels` scatters each virtual's segments into the ONE
    shared `self._pixels` buffer. There is no alpha, no blend, no
    per-pixel priority — an overlapping write simply REPLACES what was
    there. LAST WRITE WINS.
  * `Device.assemble_frame` returns `self._pixels` unchanged (its own
    docstring says merging "will eventually" be handled; today it is not).

So the answer is NO ATTENUATION — the fixture does not mix two virtuals, it
overwrites. That rules the merge out as the explanation for a UNIFORMLY dim
map: overwriting produces full brightness or nothing, never a steady tenth.
The established cause of the dim weights is the fixture's own firmware
brightness (spectra/services/fixture_brightness.py), which is what shipped.

WHAT IS STILL WORTH KNOWING, and why this file is kept rather than
deleted with the question: last-write-wins between two independent render
threads (fx/virtuals.py::Virtual.activate starts one per virtual) means an
overlapping write is ORDER-DEPENDENT. That is not the dim-map cause, but it
is a real property of this device layer, and anything that later lights one
virtual while a neighbour covers the same pixels should know it is racing
rather than blending.
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path

import numpy as np
import pytest

DEVICE = "tv-backlight-dev"
PIXELS = 60
CARRIER = "tv-mapper"
SUBSTITUTE = "tv-backlight"
BLOCK = (20, 39)


def _config(config_dir: Path) -> None:
    from fx.consts import CONFIGURATION_VERSION
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.json").write_text(json.dumps({
        "configuration_version": CONFIGURATION_VERSION,
        "devices": [{"id": DEVICE, "type": "dummy",
                     "config": {"name": DEVICE, "pixel_count": PIXELS}}],
        "virtuals": [
            {"id": CARRIER, "is_device": None, "auto_generated": False,
             "config": {"name": CARRIER, "mapping": "span", "rows": 1},
             "segments": [[DEVICE, 0, PIXELS - 1, False]]},
            {"id": SUBSTITUTE, "is_device": None, "auto_generated": False,
             "config": {"name": SUBSTITUTE, "mapping": "span", "rows": 1},
             "segments": [[DEVICE, 0, PIXELS - 1, False]]}]}))


async def _device_buffer(order: list[str]) -> np.ndarray:
    """Render BOTH virtuals and flush them in `order`, then read the
    device's own buffer — the bytes a driver receives."""
    from fx import device_model, headless
    from fx.host import FxHost

    td = Path(tempfile.mkdtemp(prefix="spectra-compose-"))
    device_model.CATEGORIES_FILE = td / "device_categories.json"
    device_model.CATEGORIES_FILE.write_text("{}")
    headless.silence_audio()
    _config(td / "fx")
    host = FxHost(str(td / "fx"))
    await host.start()
    host.audio = headless.SyntheticAudioSource()

    headless.attach_effect(host, host.virtuals.get(SUBSTITUTE), "pixelRange",
                           {"color": "#ffffff", "brightness": 1.0,
                            "background_brightness": 0.0,
                            "start": BLOCK[0], "end": BLOCK[1]})
    # exactly what the hold's dark scene puts on every in-scope virtual
    headless.attach_effect(host, host.virtuals.get(CARRIER), "singleColor",
                           {"color": "#000000", "brightness": 0.0,
                            "background_brightness": 0.0})
    device = host.devices.get(DEVICE)
    if not device.is_active():
        device.activate()
    for vid in order:
        virtual = host.virtuals.get(vid)
        virtual.flush(virtual.assemble_frame())
    out = np.asarray(device.assemble_frame(), dtype=float).copy()
    await host.shutdown()
    return out


def _lit(buffer: np.ndarray) -> float:
    return float(buffer[BLOCK[0]:BLOCK[1] + 1].mean())


@pytest.mark.parametrize("last,expected_lit", [(SUBSTITUTE, True),
                                               (CARRIER, False)])
def test_a_second_active_virtual_overwrites_it_never_blends_it(last, expected_lit):
    first = CARRIER if last == SUBSTITUTE else SUBSTITUTE
    buffer = asyncio.run(_device_buffer([first, last]))
    lit = _lit(buffer)
    if expected_lit:
        # THE ANSWER: no attenuation. The white arrives at FULL, not at some
        # blended fraction, even though a virtual rendering black covers the
        # very same pixels.
        assert lit > 250, (
            f"the substitute's white came out at {lit:.1f}/255 with a black "
            f"virtual over the same pixels — if this is not ~255 the device "
            f"layer IS blending and this file's conclusion is wrong")
    else:
        # and the other order is a total overwrite, not a partial one
        assert lit < 5, f"expected a full overwrite, got {lit:.1f}/255"


def test_the_composition_is_order_dependent_which_is_the_real_property():
    substitute_last = _lit(asyncio.run(_device_buffer([CARRIER, SUBSTITUTE])))
    carrier_last = _lit(asyncio.run(_device_buffer([SUBSTITUTE, CARRIER])))
    # Same two active virtuals, same effects, opposite answers — so the
    # device composes by write ORDER, not by mixing. A steady ~10% dimming
    # is not something this mechanism can produce, which is why the dim-map
    # finding was NOT this.
    assert substitute_last > 250 and carrier_last < 5
    assert abs(substitute_last - carrier_last) > 200
