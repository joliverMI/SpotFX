"""Every effect obeys the colour set's background MODE (overwrite vs
additive), on the real `fx.headless` render pipeline.

The Admiral, 2026-10-07: "the fish effect seems to not obey overwrite feom
colors. it may be same with other effects." He was right, twice over:

  1. `Twod.render()` PRE-FILLED the 2D canvas with the background in
     "overwrite" mode, so an effect that paints its particles ONTO that
     canvas (Fish, Orbits, Fireworks, Black Hole, Dancer ...) composed
     `body + background` — additive by construction — and the base layer
     then blended the background in a second time on every dark pixel.
     Fixed by fm/brightness-fixes (fx/VENDOR.md #60: the canvas now always
     starts black; `get_pixels()` is the ONE place a background lands).
  2. Black Hole's horizon disc and Eye's lids painted `_bg_color` INTO the
     canvas themselves, so those regions still received the background
     twice after #60 (fx/VENDOR.md #61 — they paint black now; #62 is
     Radial's own variant, which keeps its explosion-fade paint but turns
     the base layer's blend off while it does).

The contract this file holds, from `Effect.get_pixels()`: with a pure-red
foreground and a pure-blue background, a lit pixel's blue channel is
`bg_value` in additive mode and `bg_value * (1 - red/255)` in overwrite
mode, and an unlit pixel's blue is `bg_value` in both — never
`bg_value * (2 - bg_value/255)`, the double application.

The measurement is `scripts/check_effect_background_mode.py`'s, imported
here rather than re-derived (it repoints no storage; each render is its own
throwaway headless host). Two red controls at the end are test-only Twod
subclasses that re-create the two defect shapes and prove the probe goes
RED on each — a bar that cannot fail on the defect it guards is decoration.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import voluptuous as vol

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fx.effects.twod import Twod  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "check_effect_background_mode",
    ROOT / "scripts" / "check_effect_background_mode.py")
probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe)

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def _judge(res: dict) -> tuple[list[str], bool]:
    text, bad = probe.verdict(res)
    dark_text, dark_bad = probe.dark_verdict(res)
    return [text, dark_text], bad or dark_bad


@pytest.mark.parametrize("effect_type", probe.registered_effects())
def test_effect_obeys_the_colour_sets_background_mode(effect_type):
    res = probe.probe(effect_type)
    if res["overwrite"]["lit_blue"] is None and res["overwrite"]["dark_blue"] is None:
        pytest.skip(f"{effect_type} renders nothing under the synthetic audio "
                    "this harness feeds; its contract is not judgeable here")
    texts, bad = _judge(res)
    assert not bad, f"{effect_type}: " + "; ".join(texts)
    if res["overwrite"]["lit_blue"] is None:
        # pulse (no background by design) / radial (bg blocked): the dark
        # side still must carry the authored value once, never doubled.
        assert res["overwrite"]["dark_blue"] is not None
        assert abs(res["overwrite"]["dark_blue"] - probe.BG_VALUE) < probe.TOLERANCE


# ── red controls: the probe must catch both defect shapes ───────────────────

class SelfPaintProbe(Twod):
    """The pre-#61 Black Hole disc / Eye lid shape: the effect paints the
    background colour INTO its own canvas, which get_pixels() then lays on
    again."""
    NAME = "Self Paint Probe"
    CONFIG_SCHEMA = vol.Schema({})

    def draw(self):
        import numpy as np
        from PIL import Image
        out = np.zeros((self.r_height, self.r_width, 3), dtype=np.float32)
        out[:, :] = getattr(self, "_bg_color", np.zeros(3))
        self.matrix = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")


class AdditiveLeakProbe(Twod):
    """The pre-#60 pre-fill shape: a lit particle is composed ON TOP of a
    canvas already holding the background, so it carries the background
    under it in overwrite mode too."""
    NAME = "Additive Leak Probe"
    CONFIG_SCHEMA = vol.Schema({})

    def draw(self):
        import numpy as np
        from PIL import Image
        out = np.zeros((self.r_height, self.r_width, 3), dtype=np.float32)
        out[:, :] = getattr(self, "_bg_color", np.zeros(3))
        out[: self.r_height // 2, :, 0] = 255.0     # top half: lit red
        self.matrix = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")


_TEST_EFFECT_ID = Path(__file__).stem   # the registry keys a class by its module


def test_the_probe_goes_red_on_a_self_painted_background(monkeypatch):
    monkeypatch.setattr(probe.device_model, "effect_dimension", lambda _t: "2d")
    monkeypatch.setattr(probe.device_model, "bg_color_blocked", lambda _t: False)
    # the registry holds one class per module; point the id at this one
    monkeypatch.setitem(probe.EFFECT_CLASS_ALIAS, "self-paint", _TEST_EFFECT_ID)
    _select_test_class(SelfPaintProbe)
    res = probe.probe("self-paint")
    text, bad = probe.dark_verdict(res)
    assert bad and "DOUBLED" in text, text


def test_the_probe_goes_red_on_a_background_under_lit_pixels(monkeypatch):
    monkeypatch.setattr(probe.device_model, "effect_dimension", lambda _t: "2d")
    monkeypatch.setattr(probe.device_model, "bg_color_blocked", lambda _t: False)
    monkeypatch.setitem(probe.EFFECT_CLASS_ALIAS, "additive-leak", _TEST_EFFECT_ID)
    _select_test_class(AdditiveLeakProbe)
    res = probe.probe("additive-leak")
    text, bad = probe.verdict(res)
    assert bad and "IGNORES overwrite" in text, text


def _select_test_class(cls):
    """Two test-only effects live in one module; the registry keeps one
    class per module id, so swap which one it resolves to."""
    from fx.effects import Effect
    reg = getattr(Effect, "_registry", None)
    if isinstance(reg, dict) and _TEST_EFFECT_ID in reg:
        reg[_TEST_EFFECT_ID] = cls
        return
    pytest.skip("effect registry shape not as expected; red control not runnable")
