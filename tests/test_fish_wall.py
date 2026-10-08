"""Frame-level proofs for the FISH WALL and the House Fish SOLO BURST
(fx/effects/fish.py — the WALL and SOLO BURST blocks), on the real vendored
render pipeline with his crystal-mapper's REAL shape (real cells on one
dummy device, the gaps on a `gap-` device, segment for segment from the
device profile — scripts/check_fish_wall.py's rig).

HIS WORDS (2026-10-06): "the fish don't interact with the 'wall' naturally.
Have them 'anticipate' the wall and start turning away. Do this on both fish
scenes. In house fish scene, give individual ones an occasional burst of
speed." And (2026-10-07), on the first build: "The fish now get stuck in the
middle. I still want them to go right up to the edge of the wall, but i want
them to start turning so their bodies sides touch the walls, more than their
heads. [...] It's okay for light to bleed off the fixture, I'm more
interested in a natural look."

scripts/check_fish_wall.py is the measured, printed version (and writes the
before/after evidence); this file pins what has to hold:

  * the wall is the panel's real shape, read off the virtual's own segments
    through the effect's own flips;
  * his House Fish reach the wall, lie along it when they touch, use the
    panel and sweep rather than pivot — and PR 361 (the first build) is the
    control that did not;
  * his music fish glance along their own pond and never leave the panel;
  * a single fish's turn starts further out than the old edge's, never
    jolts, and lands its side on the wall;
  * `wall_lookahead = 0` is the old effect bit for bit (the escape hatch);
  * solo bursts land at about the configured rate, reach their speed and
    ease back, are off by default, and never during a charge;
  * Sonic reaches all five settings with the effect's own bounds.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scripts.check_fish_wall as W  # noqa: E402
from fx.effects import fish as FX  # noqa: E402
from scripts.add_house_fish_solo_burst import SOLO_BURST_PARAMS  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DT = W.DT


def _run(coro):
    return asyncio.run(coro)


# ── the shape ───────────────────────────────────────────────────────────
def test_the_wall_is_the_crystal_read_off_its_own_segments():
    async def main():
        r = await W.rig("shape", W.HOUSE_FISH)
        r.step(1)
        read = FX._real_cell_mask(r.effect)
        await W.close(r)
        p = await W.rig("plain", W.HOUSE_FISH, crystal=False)
        p.step(1)
        plain = FX._real_cell_mask(p.effect)
        await W.close(p)
        return read, plain

    read, plain = _run(main())
    real = W.crystal_real_mask().reshape(W.ROWS, W.COLS)
    assert np.array_equal(read, real), (
        "the wall must be exactly the cells the virtual's own segments "
        "land on a real device"
    )
    sil = FX._silhouette(read)
    assert sil[real].all(), "every real cell is inside the lit silhouette"
    assert np.array_equal(sil, W.lit_area(W.crystal_real_mask())), (
        "on the crystal the silhouette is the hexagon itself"
    )
    assert plain.all(), "a virtual with no gap device is the whole rectangle"


def test_the_wall_follows_the_effects_own_flip():
    """A flipped effect draws its matrix mirrored onto the same LEDs, so the
    cells that are dark FROM THE EFFECT'S SIDE mirror too."""
    async def main():
        r = await W.rig("flip", dict(W.HOUSE_FISH, flip_horizontal=True))
        r.step(1)
        read = FX._real_cell_mask(r.effect)
        await W.close(r)
        return read

    read = _run(main())
    real = W.crystal_real_mask().reshape(W.ROWS, W.COLS)
    assert np.array_equal(read, real[:, ::-1])


# ── his scenes: right up to the wall, side-on, not crowded in the middle ─
def test_house_fish_reach_the_wall_side_on_and_use_the_panel():
    """His 2026-10-07 words, measured on the House Fish scene's live params
    (one seed, 20 s — scripts/check_fish_wall.py runs three for 30 s): its
    fish reach the wall (the flank's light on the lit edge), lie along it
    when they touch, use the panel instead of crowding its middle, sweep
    rather than pivot, and never leave the panel. PR 361 — the first wall
    build, loaded out of git at its merge — is run alongside as the control:
    the regression he reported, which this bar must be able to see."""
    pr = W.load_pr361()
    assert pr is not None, f"git could not produce {W.PR361_REF}"
    new = W.scene_metrics(_run(W.scene_run(W.HOUSE_FISH_LIVE, 0, 20.0)))
    old = W.scene_metrics(_run(W.scene_run(
        dict(W.HOUSE_FISH_LIVE, **W.OLD), 0, 20.0)))
    first = W.scene_metrics(_run(W.scene_run(W.HOUSE_FISH_LIVE, 0, 20.0, pr)))
    assert first["wall"] < 1.0 and first["cover"] < 35.0, (
        f"control: PR 361 kept them off the wall, in the middle: {first}"
    )
    assert new["wall"] >= 35.0, f"right up to the wall: {new}"
    assert new["cover"] >= 1.8 * first["cover"], (
        f"uses the panel: {new['cover']:.1f}% against PR 361's "
        f"{first['cover']:.1f}%"
    )
    assert new["alongside"] >= 65.0, f"side-on when touching: {new}"
    assert new["pointing"] <= 8.0, f"rarely nose-on: {new}"
    assert new["tightest"] <= old["tightest"] / 2.0, (
        f"sweeps, not pivots: new {new['tightest']:.1f}% at its tightest "
        f"turn, old edge {old['tightest']:.1f}%"
    )
    assert new["off"] <= 0.5, f"no middle off the panel: {new}"


def test_the_music_fish_glide_their_own_pond_without_leaving_the_panel():
    """His music Fish scene keeps its own pond (roam_scale 0.75): its fish
    glance along that pond's rim the same way, use more of it than PR 361
    did, and never leave the panel."""
    pr = W.load_pr361()
    new = W.scene_metrics(_run(W.scene_run(W.MUSIC_FISH, 0, 20.0)))
    assert new["off"] == 0.0, new
    if pr is not None:
        m = W.scene_metrics(_run(W.scene_run(W.MUSIC_FISH, 0, 20.0, pr)))
        assert new["cover"] > m["cover"], (new, m)


# ── one fish at the wall ────────────────────────────────────────────────
@pytest.mark.parametrize("heading,x0,y0", W.APPROACHES[1:3])
def test_the_turn_is_anticipated_smooth_and_lands_the_side(heading, x0, y0):
    old = _run(W.approach(dict(W.HOUSE_FISH, **W.OLD), heading, x0, y0))
    new = _run(W.approach(W.HOUSE_FISH, heading, x0, y0))
    assert new[0] > old[0] + 1.0, (
        f"the turn starts further out: nose {new[0]:.1f}px from the wall "
        f"(old edge {old[0]:.1f}px)"
    )
    assert new[1] < 0.3 and new[1] < old[1] / 2.0, (
        f"no jolt: one-frame change in curvature {new[1]:.2f} (old edge "
        f"{old[1]:.2f})"
    )
    assert new[3], "its side reaches the wall"


@pytest.mark.parametrize("impulse", [0.3, 0.9])
def test_a_loud_passage_keeps_every_fish_on_the_panel(impulse):
    """A loud passage drives his music fish to 3-6x cruise. The glance is a
    CURVATURE (the same arc at any speed, and wider for a fast fish by
    `wall_lookahead`), so no middle leaves the panel — and his "the trail
    is always subtle" bar still holds."""
    worst, ratio = _run(W.loud_run(W.MUSIC_FISH, 1, impulse))
    assert worst <= 0.0, f"a middle got {worst:.2f}px past the lit edge"
    assert ratio < 0.6, f"the wake must stay subtle (median {ratio:.2f})"


def test_the_glance_arc_widens_with_speed_and_eases_with_strength():
    """The arc a fish sweeps in on: never tighter than its own turn radius
    or the nose's own rule, wider for a fast fish (`wall_lookahead` seconds
    of its swimming), and divided by `wall_turn_strength`."""
    async def main():
        r = await W.rig("arc", W.MUSIC_FISH)
        r.step(1)
        eff = r.effect
        steep = np.full(3, np.pi / 3, dtype=np.float32)
        speeds = np.array([0.0, eff.cruise_px, 20 * eff.cruise_px],
                          dtype=np.float32)
        a = eff._glance_radius(steep, speeds)
        eff.update_config({"wall_turn_strength": 2.0})
        r.step(1)
        b = eff._glance_radius(steep, speeds)
        floor = eff.turn_radius_px
        await W.close(r)
        return a, b, floor

    a, b, floor = _run(main())
    assert (a >= floor - 1e-4).all() and (b >= floor - 1e-4).all()
    assert a[2] > a[0], "a fast fish sweeps wider"
    assert b[2] == pytest.approx(max(a[2] / 2.0, floor), rel=1e-4), (
        "strength 2 halves the arc (never under the turn radius)"
    )


# ── the escape hatch ────────────────────────────────────────────────────
def test_wall_lookahead_zero_is_the_old_effect_bit_for_bit():
    base = W.load_baseline_effect(name="fish_wall_baseline_probe")
    assert base is not None, (
        f"git could not produce the pinned merge-base {W.WALL_BASELINE_REF}"
    )
    a = _run(W.kinematics("b", W.HOUSE_FISH, 3, base, True))
    b = _run(W.kinematics("n", dict(W.HOUSE_FISH, **W.OLD, **W.HOLD_LULL),
                          3, "fish", True))
    assert W.same_kinematics(a, b), (
        "wall_lookahead=0 must reproduce the pre-wall fish exactly, through "
        "swim, charge, lull and drop"
    )
    c = _run(W.kinematics("d", W.HOUSE_FISH, 3, "fish", True))
    assert not W.same_kinematics(a, c), "the shipped default is not inert"


# ── the solo burst ──────────────────────────────────────────────────────
def test_solo_bursts_land_at_about_the_rate_and_ease_back():
    rate = 20.0
    cfg = dict(W.HOUSE_FISH, **dict(SOLO_BURST_PARAMS, solo_burst_rate=rate))
    count, starts, peak, back, left = _run(W.burst_run(cfg, 60.0, seed=4))
    want = rate * 1.0
    assert abs(count - want) <= 3.0 * np.sqrt(want), (
        f"{count} bursts in a minute at {rate}/min"
    )
    assert peak >= 0.85 * SOLO_BURST_PARAMS["solo_burst_speed"], (
        f"a burst must reach its speed (saw {peak:.2f}x cruise)"
    )
    assert left == 0.0, "every burst's envelope returns to zero"
    assert back <= 1.4, (
        f"once they stop, every fish is back at its ordinary speed "
        f"({back:.2f}x cruise; the stroke pulse alone peaks at 1.25x)"
    )


def test_solo_bursts_are_off_unless_a_scene_turns_them_on():
    count, _, _, _, _ = _run(W.burst_run(dict(W.HOUSE_FISH), 30.0))
    assert count == 0
    assert FX.Fish2d.schema()({})["solo_burst_rate"] == 0.0


def test_no_solo_burst_during_a_charge():
    async def main():
        cfg = dict(W.HOUSE_FISH, solo_burst_rate=30.0)
        r = await W.rig("charge", cfg, seed=3)
        r.step(30)
        before = r.effect.solo_bursts
        r.phase("charge", 4.0, beats_every=12)
        during = r.effect.solo_bursts - before
        await W.close(r)
        return during

    assert _run(main()) == 0


# ── the settings ────────────────────────────────────────────────────────
NEW = ("wall_lookahead", "wall_turn_strength", "solo_burst_rate",
       "solo_burst_speed", "solo_burst_time")


@pytest.mark.parametrize("name", NEW)
def test_sonic_reaches_every_new_setting_with_the_effects_own_bounds(name):
    import voluptuous as vol
    from fx import device_model
    from spectra.services import scene_console

    info = scene_console.get_param_info("fish", name)
    assert info["type"] == "numeric"
    assert info["default"] == device_model.resting_default("fish", name)
    schema = FX.Fish2d.schema()
    assert schema({})[name] == info["default"]
    assert schema({name: info["min"]})[name] == info["min"]
    assert schema({name: info["max"]})[name] == info["max"]
    for outside in (info["min"] - 1e-3, info["max"] + 1e-3):
        with pytest.raises(vol.Invalid):
            schema({name: outside})
    reg = json.loads((REPO / "config" / "effect_params.json").read_text())
    assert reg["effects"]["fish"]["defaults"][name] == info["default"]


def test_sonic_sets_a_house_fish_solo_burst_through_its_own_operation(
    tmp_path, monkeypatch,
):
    """The real Sonic write path, end to end, on an isolated store: "make
    the house fish burst more often" lands as `set_scene_entry_param` on
    the House Fish's Matrix entry, validated against the registry (an
    out-of-range rate is refused by name, nothing saved)."""
    from spectra import config as scfg
    for attr, name in (("SPECTRA_STORAGE", None),
                       ("SCENES_FILE", "scenes.json"),
                       ("SCENE_AGENT_LOG_FILE", "scene_agent_log.json"),
                       ("SCENE_BACKUPS_FILE", "scene_backups.json"),
                       ("SCENE_GENESIS_FILE", "scene_genesis.json"),
                       ("COLOR_SETS_FILE", "color_sets.json"),
                       ("DRIFT_PROFILES_FILE", "drift_profiles.json")):
        monkeypatch.setattr(scfg, attr, tmp_path / name if name else tmp_path)
    from spectra.models.scene import SceneDeviceConfig, SceneV2
    from spectra.services import scene_console as sc
    from spectra.services import scene_store

    scene = SceneV2(name="House Fish", devices=[SceneDeviceConfig(
        target_kind="category", target="Matrix", effect_type="fish",
        params={"particle_count": 5, "solo_burst_rate": 4.0})])
    scene_store.save(scene)
    out = _run(sc.apply_scene_entry_param("House Fish", "Matrix",
                                          "solo_burst_rate", 8.0))
    assert out["status"] == "applied"
    entry = scene_store.get_by_id(scene.id).devices[0]
    assert entry.params["solo_burst_rate"] == 8.0
    assert entry.params["particle_count"] == 5
    out = _run(sc.apply_scene_entry_param("House Fish", "Matrix",
                                          "wall_lookahead", 1.0))
    assert out["status"] == "applied"
    with pytest.raises(sc.SceneOpError):
        _run(sc.apply_scene_entry_param("House Fish", "Matrix",
                                        "solo_burst_rate", 99.0))
    assert scene_store.get_by_id(scene.id).devices[0].params[
        "solo_burst_rate"] == 8.0


def test_the_new_fish_params_declare_their_help_topics():
    """InitialSetTab.tsx renders `meta.help_topic && <HelpLink topic={...}
    />` straight off `GET /api/registry`'s own `effects[type]["params"]`,
    which `spectra/api/registry.py` serves VERBATIM from
    `fx.device_model.effect_params(etype)` — read the five new params
    through that same live function, the registry's actual consumer."""
    from fx import device_model

    params = device_model.effect_params("fish")
    for topic, names in (("fish-wall", NEW[:2]), ("fish-solo-burst", NEW[2:])):
        for name in names:
            assert params[name]["help_topic"] == topic


# ── the House Fish scene ────────────────────────────────────────────────
def _store(tmp_path, params):
    store = {
        "hf": {"id": "hf", "name": "House Fish", "labels": ["house"],
               "devices": [
                   {"id": "d0", "target_kind": "category", "target": "Matrix",
                    "effect_type": "fish", "params": params},
                   {"id": "d1", "target_kind": "category", "target": "Strips",
                    "effect_type": "melt", "params": {"speed": 0.08}},
               ]},
        "other": {"id": "other", "name": "Fish", "devices": [
            {"id": "e0", "target_kind": "category", "target": "Matrix",
             "effect_type": "fish", "params": {"blob_size": 2.5}}]},
    }
    path = tmp_path / "scenes.json"
    path.write_text(json.dumps(store, indent=2))
    return path


def _migrate(path, *args):
    import subprocess
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / "add_house_fish_solo_burst.py"),
         "--scenes-file", str(path), *args],
        capture_output=True, text=True, cwd=REPO,
    )


def test_the_migration_turns_it_on_in_house_fish_only(tmp_path):
    path = _store(tmp_path, {"particle_count": 5, "blob_size": 6})
    before = json.loads(path.read_text())
    dry = _migrate(path)
    assert dry.returncode == 0, dry.stderr
    assert json.loads(path.read_text()) == before, "a dry run writes nothing"
    done = _migrate(path, "--apply")
    assert done.returncode == 0, done.stderr
    after = json.loads(path.read_text())
    params = after["hf"]["devices"][0]["params"]
    assert params == {"particle_count": 5, "blob_size": 6, **SOLO_BURST_PARAMS}
    after["hf"]["devices"][0]["params"] = before["hf"]["devices"][0]["params"]
    assert after == before, "nothing else in the store changed"
    again = _migrate(path, "--apply")
    assert "nothing to do" in again.stdout


def test_the_migration_keeps_a_value_he_already_set(tmp_path):
    path = _store(tmp_path, {"solo_burst_rate": 1.0})
    assert _migrate(path, "--apply").returncode == 0
    params = json.loads(path.read_text())["hf"]["devices"][0]["params"]
    assert params["solo_burst_rate"] == 1.0
    assert params["solo_burst_speed"] == SOLO_BURST_PARAMS["solo_burst_speed"]


def test_the_seeded_house_fish_carries_the_solo_burst():
    import scripts.seed_house_lighting as seed

    scenes = seed.scene_entries()
    fish = next(s for s in scenes.values() if s["name"] == "House Fish")
    entry = next(d for d in fish["devices"] if d["effect_type"] == "fish")
    for key, value in SOLO_BURST_PARAMS.items():
        assert entry["params"][key] == value
    star = next(s for s in scenes.values() if s["name"] == "House Star")
    assert all("solo_burst_rate" not in d["params"] for d in star["devices"])
