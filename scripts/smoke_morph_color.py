"""
Offline smoke test for the NEW Morph Color action (hue rotation).

No LedFX needed — the client calls are stubbed and every write is recorded.
Verifies:
  1. 180° rotation hits FG gradient, BG color, and accent on power effects.
  2. morph_bg=False keeps every background_color (FG/accent still rotate);
     legacy preserve_melt_bg=True payloads load as morph_bg=False.
  3. direction="backward" rotates the other way (90° back == 270° forward).
  4. intensity_scale modulates the sweep via the beat-intensity factor.
  5. Empty leaf scope adopts the inherited group Target (parent/override).
  6. Group revert snapshots the color params a rotation will touch.

USAGE
  .venv/bin/python scripts/smoke_morph_color.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import effect_params
effect_params.load()

from api import ledfx_client                                # noqa: E402
from models.state import state                              # noqa: E402
from models.music_event import MorphColorAction, MorphScope  # noqa: E402
from services.gradient_interpolation import rotate_color_string  # noqa: E402
import services.trigger_engine as te                        # noqa: E402


PASS = 0

def ok(msg: str) -> None:
    global PASS
    PASS += 1
    print(f"✓ {msg}")


def seed_cache() -> None:
    state.ledfx_virtual_cache.clear()
    state.ledfx_virtual_cache.update({
        "single-color-effect": {"effect": {"type": "power", "config": {
            "gradient": "#ff0000",
            "background_color": "#000080",
            "sparks_color": "#ffffff",
        }}},
        "hues": {"effect": {"type": "melt", "config": {
            "gradient": "linear-gradient(90deg, #ff0000 0%, #00ff00 100%)",
            "background_color": "#000080",
        }}},
    })


class Recorder:
    """Stub the LedFX write/read surface; record every write per (vid, param)."""
    def __init__(self):
        self.writes: dict[tuple[str, str], object] = {}

    def install(self):
        async def set_virtual_effect(vid, etype, cfg):
            for k, v in cfg.items():
                self.writes[(vid, k)] = v
        async def ramp_gradient_params(vid, etype, params, ramp_ms):
            for k, v in params.items():
                self.writes[(vid, k)] = v
        async def ramp_effect_params(vid, etype, params, ramp_ms):
            for k, v in params.items():
                self.writes[(vid, k)] = v
        async def get_virtual(vid):
            return None  # force fallback to the seeded cache
        self._saved = {n: getattr(ledfx_client, n) for n in (
            "set_virtual_effect", "ramp_gradient_params", "ramp_effect_params", "get_virtual")}
        ledfx_client.set_virtual_effect = set_virtual_effect
        ledfx_client.ramp_gradient_params = ramp_gradient_params
        ledfx_client.ramp_effect_params = ramp_effect_params
        ledfx_client.get_virtual = get_virtual

    def restore(self):
        for n, f in self._saved.items():
            setattr(ledfx_client, n, f)


async def main() -> None:
    rec = Recorder()
    rec.install()
    # Don't persist morph_effect_state from a smoke run.
    from services import morph_effect_state
    morph_effect_state.save_many = lambda updates: None

    engine = te.TriggerEngine()
    singles = MorphScope(categories=["Singles"])

    try:
        # ── 1. 180° rotation: FG + BG + accent on power, gradient stops on melt ──
        seed_cache()
        rec.writes.clear()
        await engine._execute_morph_color(
            MorphColorAction(scope=singles, degrees=180), await_ramps=True)
        assert rec.writes[("single-color-effect", "gradient")] == "#00ffff", rec.writes
        assert rec.writes[("single-color-effect", "background_color")] == "#808000"
        assert ("single-color-effect", "sparks_color") not in rec.writes, \
            "white has no hue — rotation must be a no-op"
        grad = rec.writes[("hues", "gradient")]
        assert "#00ffff" in grad and "#ff00ff" in grad, grad
        assert rec.writes[("hues", "background_color")] == "#808000"
        ok("180°: power FG/BG rotate, hueless accent skipped, melt gradient stops rotate")

        # ── 2. morph_bg off: every BG kept, FG/accent still rotate ─────────────
        seed_cache()
        rec.writes.clear()
        await engine._execute_morph_color(
            MorphColorAction(scope=singles, degrees=180, morph_bg=False),
            await_ramps=True)
        assert ("hues", "background_color") not in rec.writes, "melt BG must be preserved"
        assert rec.writes[("hues", "gradient")], "melt FG still rotates"
        assert ("single-color-effect", "background_color") not in rec.writes, \
            "morph_bg off skips power BG too"
        assert rec.writes[("single-color-effect", "gradient")] == "#00ffff", \
            "power FG still rotates"
        ok("morph_bg off: all BGs untouched, FGs still rotate")

        # ── 2b. legacy preserve_melt_bg payload loads as morph_bg=False ────────
        legacy = MorphColorAction(**{"scope": singles.model_dump(), "degrees": 180,
                                     "preserve_melt_bg": True})
        assert legacy.morph_bg is False
        assert MorphColorAction(degrees=180).morph_bg is True
        ok("legacy preserve_melt_bg=true → morph_bg=False (default stays True)")

        # ── 3. backward = negative rotation ────────────────────────────────────
        seed_cache()
        rec.writes.clear()
        await engine._execute_morph_color(
            MorphColorAction(scope=singles, degrees=90, direction="backward"),
            await_ramps=True)
        expect = rotate_color_string("#ff0000", -90)
        assert rec.writes[("single-color-effect", "gradient")] == expect, \
            (rec.writes[("single-color-effect", "gradient")], expect)
        ok(f"backward 90°: #ff0000 → {expect}")

        # ── 4. intensity_scale modulates the sweep ─────────────────────────────
        seed_cache()
        rec.writes.clear()
        engine._beat_intensity_now = lambda src: 1.0  # loud beat
        await engine._execute_morph_color(
            MorphColorAction(scope=singles, degrees=120, intensity_scale=1.0),
            await_ramps=True)
        # factor = 1 + (1.0 - 0.5) * 1.0 = 1.5 → 180°
        assert rec.writes[("single-color-effect", "gradient")] == "#00ffff"
        ok("intensity 1.0 @ scale 1.0: 120° → 180° (factor 1.5)")

        # ── 5. empty scope adopts inherited group Target ───────────────────────
        bare = MorphColorAction(degrees=180)
        adopted = engine._apply_inherited_scope(bare, singles)
        assert adopted is not bare and adopted.scope.categories == ["Singles"]
        own = MorphColorAction(degrees=180, scope=MorphScope(virtual_ids=["hues"]))
        assert engine._apply_inherited_scope(own, singles) is own, "own scope wins"
        ok("scope: empty leaf adopts parent Target; explicit override wins")

        # ── 6. revert snapshot captures the params the rotation touches ────────
        seed_cache()
        snap = await engine._snapshot_for_revert(
            actions=[MorphColorAction(scope=singles, degrees=180)])
        ve = snap["virtual_effects"]
        assert ve["single-color-effect"]["params"] == {
            "gradient": "#ff0000", "background_color": "#000080", "sparks_color": "#ffffff"}
        assert ve["hues"]["params"]["background_color"] == "#000080"
        ok("snapshot: FG/BG/accent captured for group revert")

    finally:
        rec.restore()
        state.ledfx_virtual_cache.clear()

    print(f"\nALL PASS ({PASS} checks)")


if __name__ == "__main__":
    asyncio.run(main())
