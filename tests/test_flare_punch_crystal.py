"""A FLARE IN THE LULL'S DARK PUNCHES THROUGH — on the crystal and the Singles
too (the strip phase plan's phase 5, /home/javi/fleet-spotfx/data/
strip-phase-plan/report.md; his approval: give the crystal's Black Hole and
Squiggles and the Pulse singles the same punch as the strips, "so a flare in
a dark room lights everything together").

What is proven here, each on the real code it names:

- ONE DEFINITION: fx/effects/lull_dark.py's FlarePunch is the runtime every
  member uses (the strip layer included); its edge, its lull-only opening,
  its self-closing; the creation baseline never fires a stale poke.
- MEMBERSHIP: fx.device_model.FLARE_PUNCH_EFFECTS is exactly the registered
  effects whose schema carries the poke, and every member's three "Flare
  punch" settings are registered as lull_dark says (Sonic reaches them).
- THE ROOM (fx.headless + the PRODUCTION ResponseEngine on the
  FacadeExecutor, one fake clock): a completed charge, an 8 s lull whose
  dark point is 5 s in, and a real flare (a momentary gain, the band's own
  path) at 6 s. The crystal's Black Hole (its REAL crystal cells),
  Squiggles and the Pulse single all light within the flare's first
  instants, and all three are dark again once the punch has released —
  before the drop. RED CONTROLS: the same flare with "Flare punch" at 0,
  and the same flare under phase 1's strips-only SpotFX, leave all three
  dark (the dark wins — exactly what this phase changes).
- THE LULL'S TIMING DOES NOT MOVE: a flare while the lull is still
  darkening leaves every dark point where it was.
- TODAY'S LULLS ARE UNTOUCHED WITHOUT A PUNCH: each of the three, driven
  through a charge, a lull (with an ordinary flare write in it) and a drop,
  renders byte for byte what the pinned pre-change module renders.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fx import device_model, facade, headless  # noqa: E402
from fx.effects import lull_dark  # noqa: E402
from strip_phase_harness import FPS, DT, Room, run, scene_for  # noqa: E402

# the commit this phase was built on: the "before" of every byte-identity
# claim below (pinned, never a moving ref — see AGENTS.md's fish camera
# note on why an instrument's reference must not move out from under it)
BASELINE_REF = "0b4bdd683aa58353c47a4fc4dfd92f08a9585d1c"

CRYSTAL = ("blackhole", "squiggles", "pulse")
COLS, ROWS = 72, 37
BH_V, SQ_V, PULSE_V = "bh-v", "sq-v", "pulse-v"
BH_CFG = {
    "horizon_scale": 0.2, "blob_size": 1.75, "swirl": 0.0, "reverse": False,
    "horizon_audio": 0.3, "base_speed": 2.0, "accel": 5.0, "spawn_rate": 30.0,
    "beat_burst": 0, "spawn_audio": 1.5, "speed_audio": 2.0,
    "max_blobs": 50, "edge_speed": 0.2, "horizon_hold": 2.8,
}
SQ_CFG = {"spawn_rate": 6.0, "max_blobs": 24, "gradient": "#ffffff"}
PULSE_CFG = {"gradient": "#ff0000", "beat_ms": 500.0, "energy": 0.5}


# ── the one runtime ─────────────────────────────────────────────────────────

def test_a_poke_opens_only_in_a_lull_and_closes_itself():
    p = lull_dark.FlarePunch(0)
    p.note(1)
    assert p.consume(False) is False and p.spent and not p.open
    p.note(0)                         # the effect writes the key back to 0
    assert not p.pending
    p.note(1)                         # ... so an identical later poke edges
    assert p.pending
    assert p.consume(True, 0.6) and p.open
    cfg = {"flare_punch_strength": 1.0, "flare_punch_min_hold_s": 0.5,
           "flare_punch_release_s": 0.8}
    p.advance(0.02)
    assert 0.0 < p.level(True, cfg) < 1.0           # rising
    p.advance(0.3)
    assert p.level(True, cfg) == 1.0                # held (0.6 s hold)
    p.advance(0.04 + 0.6 + 0.8)
    assert p.level(True, cfg) == 0.0 and not p.open  # released and closed
    # a lull ending under an open punch closes it
    p.note(0)
    p.note(1)
    p.consume(True)
    p.advance(0.1)
    assert p.level(False, cfg) == 0.0 and not p.open


def test_strength_zero_is_the_dark_winning():
    p = lull_dark.FlarePunch(0)
    p.note(1)
    p.consume(True, 1.0)
    p.advance(0.2)
    assert p.level(True, {"flare_punch_strength": 0.0}) == 0.0
    assert not p.open


def test_the_envelope_is_the_one_the_strips_read():
    # the strip layer's punch is the same object, not a copy of its rules
    from fx.effects import strip_phase as sp
    assert sp.PUNCH_KEY == lull_dark.PUNCH_KEY
    assert sp.PUNCH_HOLD_KEY == lull_dark.PUNCH_HOLD_KEY
    for t in lull_dark.PUNCH_TUNABLES:
        assert t in sp.TUNABLES


# ── membership and the registry ────────────────────────────────────────────

def _registered_with_the_poke():
    out = set()
    for name in json.loads(
            (ROOT / "config/effect_params.json").read_text())["effects"]:
        try:
            cls = device_model._effect_class(name)
        except Exception:                                # noqa: BLE001
            continue
        if cls is None:
            continue
        keys = {str(k) for k in cls.schema().schema}
        if lull_dark.PUNCH_KEY in keys:
            out.add(name)
    return out


def test_members_are_exactly_the_effects_that_take_the_poke():
    m = device_model.FLARE_PUNCH_EFFECTS
    assert m == set(CRYSTAL) | device_model.STRIP_PHASE_EFFECTS
    assert m <= device_model.LULL_DARK_EFFECTS
    assert m == _registered_with_the_poke()


def test_the_crystal_and_the_singles_register_the_punch_settings():
    registry = json.loads((ROOT / "config/effect_params.json").read_text())
    want = lull_dark.punch_registry_params()
    for name in CRYSTAL:
        cls = device_model._effect_class(name)
        params = registry["effects"][name]["params"]
        for key, meta in want.items():
            assert params[key] == meta, (name, key)
            assert device_model.schema_default(name, key) == meta["default"]
        # the pushed keys never enter the registry, and stay advanced
        for key in lull_dark.PUNCH_KEYS:
            assert key not in params, (name, key)
            assert key in cls.ADVANCED_KEYS, (name, key)


# ── the room ────────────────────────────────────────────────────────────────

def _real_mask():
    prof = json.loads((ROOT / "storage/device_profiles/crystal-mapper.json")
                      .read_text(encoding="utf-8"))
    mask, v = [], False
    for r in prof["mask_rle"]:
        mask.extend([v] * r)
        v = not v
    return np.array(mask, dtype=bool).reshape(prof["rows"], prof["cols"])


def _lum(px) -> float:
    f = np.clip(np.asarray(px, dtype=float).reshape(-1, 3), 0, 255) / 255.0
    return float((0.2126 * f[:, 0] + 0.7152 * f[:, 1]
                  + 0.0722 * f[:, 2]).mean())


def _flare_kind():
    from spectra.models.scene import FlareKind
    return FlareKind(name="Flare gain", type="momentary", gain=1.4,
                     hold_ms=600)


def _room(tmp, vids, strength=1.0):
    bh_v, sq_v, pulse_v = vids
    extra = {"flare_punch_strength": strength}
    effects = {
        bh_v: ("blackhole", COLS * ROWS, ROWS, {**BH_CFG, **extra}),
        sq_v: ("squiggles", COLS * ROWS, ROWS, {**SQ_CFG, **extra}),
        pulse_v: ("pulse", 1, 1, {**PULSE_CFG, **extra}),
    }
    scene = scene_for({vid: et for vid, (et, *_r) in effects.items()},
                      [_flare_kind()])
    return Room(str(tmp), effects, scene=scene)


def _run_lull(tmp, flare_at, strength=1.0, lull_s=8.0):
    """A completed charge, then a lull of `lull_s` (dark point 3 s before
    its end), with one flare `flare_at` seconds in (None = no flare).
    Per frame: seconds into the lull, Black Hole real cells lit, Squiggles
    lit rows, Pulse's light, and each one's mean luminance; frames from the
    second before the charge carry `t` < 0 and `normal` True."""
    mask = _real_mask()
    # virtual ids of their own per run: a deactivated particle effect leaves
    # a hand-off snapshot keyed by virtual id (fx/effects/particle_handoff)
    # that the next run's effect would otherwise adopt
    tag = Path(tmp).name
    vids = (f"{BH_V}-{tag}", f"{SQ_V}-{tag}", f"{PULSE_V}-{tag}")
    bh_v, sq_v, pulse_v = vids

    def sample(room, t, normal=False):
        bh = room.frames[bh_v][-1].reshape(ROWS, COLS, -1)[mask]
        sq = room.frames[sq_v][-1].reshape(ROWS, COLS, -1)
        return {
            "t": t, "normal": normal,
            "bh": float(bh.max()),
            "sq": int(np.count_nonzero(sq.max(axis=(1, 2)) > 0.0)),
            "pulse": float(room.frames[pulse_v][-1].max()),
            # mean luminance 0..1 (Black Hole over its REAL cells)
            "bh_lum": _lum(bh),
            "sq_lum": _lum(sq.reshape(-1, 3)),
            "pulse_lum": _lum(room.frames[pulse_v][-1]),
        }

    async def main():
        rows = []
        async with _room(tmp, vids, strength) as room:
            room.step(3 * FPS)
            for i in range(FPS):
                room.step()
                rows.append(sample(room, -1.0 + i * DT, normal=True))
            await room.phase("charge", gap_ms=3_000)
            room.step(3 * FPS)
            rec = await room.phase("lull", gap_ms=int(lull_s * 1000))
            assert set(rec["phase"]["targets"]) == set(vids)
            fired = None
            for i in range(1, int(lull_s * FPS) + 1):
                t = i * DT
                if flare_at is not None and fired is None and t >= flare_at:
                    fired = await room.flare(0.8)
                room.step()
                rows.append(sample(room, t))
        return rows, fired, vids

    rows, fired, vids = run(main())
    return [r for r in rows if not r["normal"]], fired, vids, [
        r for r in rows if r["normal"]]


def _window(rows, a, b):
    return [r for r in rows if a <= r["t"] < b]


def _dark(r):
    return r["bh"] == 0.0 and r["sq"] == 0 and r["pulse"] == 0.0


@pytest.fixture(scope="module")
def punched(tmp_path_factory):
    return _run_lull(tmp_path_factory.mktemp("punch"), flare_at=6.0)


def test_the_flare_punches_all_three_and_the_dark_comes_back(punched):
    rows, fired, vids, _normal = punched
    # SpotFX poked all three: the flare wrote to each, the lull reached each
    assert set(fired["flare_punch"]["virtuals"]) == set(vids)
    # dark before the flare (the dark point is 5 s in)
    before = _window(rows, 5.2, 6.0)
    assert before and all(_dark(r) for r in before)
    # the flare shows on every one of them
    during = _window(rows, 6.05, 6.7)
    assert max(r["bh"] for r in during) > 0.0       # real crystal cells
    assert max(r["sq"] for r in during) > 0
    assert max(r["pulse"] for r in during) > 0.0
    # attack 0.04 + hold 0.6 + release 0.8: dark again, before the drop
    after = _window(rows, 6.0 + 0.04 + 0.6 + 0.8 + 0.15, 8.0)
    assert after and all(_dark(r) for r in after)


def test_flare_punch_at_zero_is_the_dark_winning(tmp_path):
    rows, _fired, _v, _n = _run_lull(tmp_path, flare_at=6.0, strength=0.0)
    assert all(_dark(r) for r in _window(rows, 5.2, 8.0))


def test_strips_only_spotfx_leaves_the_crystal_dark(tmp_path, monkeypatch):
    # phase 1's rule, re-created: SpotFX pokes only the strips
    monkeypatch.setattr(device_model, "FLARE_PUNCH_EFFECTS",
                        device_model.STRIP_PHASE_EFFECTS)
    rows, fired, _v, _n = _run_lull(tmp_path, flare_at=6.0)
    assert "flare_punch" not in fired
    assert all(_dark(r) for r in _window(rows, 5.2, 8.0))


def test_a_flare_while_darkening_does_not_move_the_dark_point(tmp_path):
    rows, _fired, _v, _n = _run_lull(tmp_path, flare_at=2.0)
    assert any(r["sq"] > 0 for r in _window(rows, 2.05, 2.6))
    # every one of them is dark from the dark point (5 s) on, as without
    # the flare
    late = _window(rows, 5.0 + 2 * DT, 8.0)
    assert late and all(_dark(r) for r in late)
    assert not _dark(min(rows, key=lambda r: abs(r["t"] - 4.5)))


# ── today's lulls, untouched without a punch ───────────────────────────────

_PINNED: dict = {}


def _pinned_type(effect: str):
    """The pre-change module, registered as a SECOND effect beside today's
    (an Effect subclass registers under its module's last name segment)."""
    if effect in _PINNED:
        return _PINNED[effect]
    name = f"{effect}_pre_punch"
    try:
        src = subprocess.run(
            ["git", "show", f"{BASELINE_REF}:fx/effects/{effect}.py"],
            cwd=ROOT, capture_output=True, text=True, check=True).stdout
    except Exception as exc:                             # noqa: BLE001
        pytest.skip(f"cannot read {BASELINE_REF}:fx/effects/{effect}.py "
                    f"({exc}) — the byte-identity claim is NOT checked")
    path = Path(tempfile.mkdtemp()) / f"{name}.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    _PINNED[effect] = name
    return name


def _cycle_frames(tmp, effect_type, cfg, n, rows):
    """Drive one effect through a charge, a told lull (with an ordinary
    flare's brightness write in its dark) and a drop by direct writes — the
    keys SpotFX sends — and return every rendered frame."""
    from fx.consts import CONFIGURATION_VERSION
    from fx.host import FxHost

    # a virtual id of its own per run: a deactivated particle effect leaves
    # a hand-off snapshot keyed by virtual id (fx/effects/particle_handoff),
    # which the next run's effect would otherwise adopt
    vid = f"v-{Path(tmp).name}-{effect_type}"

    async def main():
        np.random.seed(7)
        config_dir = Path(tmp) / f"room-{effect_type}"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "config.json").write_text(json.dumps({
            "configuration_version": CONFIGURATION_VERSION,
            "devices": [{"id": "dev", "type": "dummy",
                         "config": {"name": "dev", "pixel_count": n}}],
            "virtuals": [{"id": vid, "is_device": False,
                          "auto_generated": False,
                          "config": {"name": vid, "mapping": "span",
                                     "rows": rows},
                          "segments": [["dev", 0, n - 1, False]]}]}))
        headless.silence_audio()
        host = FxHost(str(config_dir))
        await host.start()
        host.audio = headless.SyntheticAudioSource()
        facade.set_host(host)
        frames = []
        try:
            with headless.fake_clock() as clock:
                v = host.virtuals.get(vid)
                eff = headless.attach_effect(host, v, effect_type, dict(cfg))
                if hasattr(eff, "_rng"):
                    eff._rng = np.random.default_rng(11)

                def write(c):
                    with eff.lock:
                        eff._apply_config(c, validate=False)

                def frames_for(seconds, ramp=None):
                    k = int(seconds * FPS)
                    for i in range(1, k + 1):
                        if ramp is not None:
                            write({"phase_progress": min(1.0, i * DT / ramp)})
                        clock.advance(DT)
                        f = v.assemble_frame()
                        if f is not None:
                            v.flush(f)
                            frames.append(np.array(f, dtype=np.float32))

                frames_for(3.0)
                write({"phase": "charge", "phase_progress": 0.0})
                frames_for(2.5, ramp=2.25)
                write({"phase": "lull", "phase_progress": 0.0,
                       **lull_dark.keys_for(6.0, 5.4, 3.0)})
                frames_for(4.0, ramp=5.4)
                write({"brightness": 0.7})       # a flare, no punch
                frames_for(2.0, ramp=5.4)
                write({"brightness": 1.0, "phase": "drop",
                       "phase_progress": 0.0})
                frames_for(2.0, ramp=0.4)
        finally:
            facade.set_host(None)
            await host.shutdown()
        return np.array(frames)

    return asyncio.run(main())


@pytest.mark.parametrize("effect,cfg,n,rows", [
    ("blackhole", BH_CFG, COLS * ROWS, ROWS),
    ("squiggles", {**SQ_CFG, "gradient": "#20ff60"}, COLS * ROWS, ROWS),
    ("pulse", PULSE_CFG, 1, 1),
])
def test_without_a_punch_the_lull_renders_exactly_as_before(
        tmp_path, effect, cfg, n, rows):
    pinned = _pinned_type(effect)
    today = _cycle_frames(tmp_path / "today", effect, cfg, n, rows)
    before = _cycle_frames(tmp_path / "before", pinned, cfg, n, rows)
    assert today.shape == before.shape and today.size
    # a cycle that never lit anything would prove nothing
    assert today.max() > 0.0
    assert np.array_equal(today, before), effect
