"""Frame-level proofs for the FISH WALL and the House Fish SOLO BURST
(fx/effects/fish.py — the WALL and SOLO BURST blocks), on the real vendored
render pipeline with his crystal-mapper's REAL shape (real cells on one
dummy device, the gaps on a `gap-` device, segment for segment from the
device profile — scripts/check_fish_wall.py's rig).

HIS WORDS (2026-10-06): "the fish don't interact with the 'wall' naturally.
Have them 'anticipate' the wall and start turning away. Do this on both fish
scenes. In house fish scene, give individual ones an occasional burst of
speed."

scripts/check_fish_wall.py is the measured, printed version (and writes the
before/after GIFs); this file pins what has to hold:

  * the wall is the panel's real shape, read off the virtual's own segments
    through the effect's own flips;
  * no swimming fish's nose or middle ever leaves the lit area, at both of
    his scenes' live params — judged against a lit area computed HERE, not
    the effect's own;
  * the turn starts well before the wall and eases in, where the old one
    started late and snapped;
  * `wall_lookahead = 0` is the old effect bit for bit (the escape hatch);
  * a fast shoal keeps swimming its ring instead of collapsing into a ball;
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


# ── the wall held ───────────────────────────────────────────────────────
@pytest.mark.parametrize("name,cfg", [
    ("house-fish", W.HOUSE_FISH),
    ("fish", W.MUSIC_FISH),
])
@pytest.mark.parametrize("seed", [0, 1])
def test_no_fish_ever_swims_past_the_lit_area(name, cfg, seed):
    lit = W.lit_area(W.crystal_real_mask())
    worst, share = _run(W.wall_run(cfg, seed, 20.0, lit))
    assert worst <= 0.0, (
        f"{name} seed {seed}: a swimming fish's nose or middle got "
        f"{worst:.2f}px past the lit edge"
    )
    assert share < 0.01, (
        f"{name} seed {seed}: {100 * share:.2f}% of the fish light landed "
        "where the panel cannot show it"
    )


def test_the_old_edge_turn_did_cross_it():
    """The negative control: the same run with the wall off (the old pond
    edge) puts a House Fish's nose into the dark, or the test above could
    be passing on a rig that cannot see a crossing."""
    lit = W.lit_area(W.crystal_real_mask())
    worst, share = _run(W.wall_run(dict(W.HOUSE_FISH, **W.OLD), 0, 20.0, lit))
    assert worst > 1.0 and share > 0.02, (worst, share)


# ── anticipation ────────────────────────────────────────────────────────
def test_the_turn_starts_before_the_wall_and_eases_in():
    after = W.onset_and_shape(_run(W.approach(W.HOUSE_FISH)))
    before = W.onset_and_shape(
        _run(W.approach(dict(W.HOUSE_FISH, **W.OLD)))
    )
    onset, peak, jump, nearest = after
    assert onset > before[0] + 2.0, (
        f"the turn must start well before the wall: nose {onset:.1f}px "
        f"from it (the old edge turn: {before[0]:.1f}px)"
    )
    assert jump < before[2], (
        f"the turn must ease in: biggest one-frame change in curvature "
        f"{jump:.2f} (old {before[2]:.2f})"
    )
    assert jump < 0.5, f"no snap: one frame changed curvature by {jump:.2f}"
    assert nearest >= 0.0, f"the nose reached the wall ({nearest:.2f}px)"


@pytest.mark.parametrize("impulse", [0.3, 0.9])
def test_a_loud_passage_keeps_every_fish_on_the_panel(impulse):
    """A loud passage drives his music fish to 3-6x cruise. The old edge
    steer could not turn them in time and flew them off the panel (measured
    up to ~28px past it at full volume); the wall's look-ahead grows with
    speed, so they stay on it — and, because that look-ahead is capped at
    the pond's own short radius (`_wall_look`), they keep swimming instead
    of every fish turning as tight as it can (found building this: the
    uncapped look-ahead outgrew the pond and balled the shoal up, its wake
    nearly as bright as the fish). His "the trail is always subtle" bar
    still holds."""
    worst, ratio = _run(W.loud_run(W.MUSIC_FISH, 1, impulse))
    assert worst <= 0.0, f"a fish got {worst:.2f}px past the lit edge"
    assert ratio < 0.6, f"the wake must stay subtle (median {ratio:.2f})"


def test_the_old_edge_steer_flew_loud_fish_off_the_panel():
    """The negative control for the test above."""
    worst, _ = _run(W.loud_run(dict(W.MUSIC_FISH, **W.OLD), 1, 0.9))
    assert worst > 5.0, worst


def test_the_look_ahead_grows_with_speed_and_stops_at_the_pond():
    """Turn room, plus `wall_lookahead` seconds of the fish's own speed —
    never under half its own length (a big slow fish's room to swing round)
    and never past the pond's own short radius."""
    async def main():
        r = await W.rig("look", W.MUSIC_FISH)
        r.step(1)
        eff = r.effect
        cruise = eff.cruise_px
        look = eff._wall_look(np.array([0.0, cruise, 2 * cruise, 20 * cruise],
                                       dtype=np.float32))
        geometry = dict(
            pond=eff.roam_bound * eff.s_min,
            base=FX.WALL_LOOK_BASE_R * eff.turn_radius_px,
            floor=FX.WALL_LOOK_BODY * eff._body_len_px(),
            cruise=cruise, secs=eff.wall_lookahead,
        )
        await W.close(r)
        return look, geometry

    look, g = _run(main())
    assert look[0] == pytest.approx(g["base"] + g["floor"], rel=1e-5), (
        "a fish at rest still looks half its own length ahead"
    )
    assert look[1] == pytest.approx(
        g["base"] + max(g["secs"] * g["cruise"], g["floor"]), rel=1e-5
    )
    assert look[2] > look[1], "a faster fish looks further"
    assert look[3] == pytest.approx(g["base"] + g["pond"], rel=1e-5), (
        "never further than the pond is wide"
    )


# ── the escape hatch ────────────────────────────────────────────────────
def test_wall_lookahead_zero_is_the_old_effect_bit_for_bit():
    base = W.load_baseline_effect(name="fish_wall_baseline_probe")
    assert base is not None, (
        f"git could not produce the pinned merge-base {W.WALL_BASELINE_REF}"
    )
    a = _run(W.kinematics("b", W.HOUSE_FISH, 3, base, True))
    b = _run(W.kinematics("n", dict(W.HOUSE_FISH, **W.OLD), 3, "fish", True))
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


def test_the_help_topics_exist_and_are_linked():
    reg = json.loads((REPO / "config" / "effect_params.json").read_text())
    params = reg["effects"]["fish"]["params"]
    help_src = (REPO / "spectra" / "web" / "src" / "help"
                / "helpContent.ts").read_text()
    linked = (REPO / "spectra" / "web" / "src" / "scenes" / "tabs"
              / "InitialSetTab.tsx").read_text()
    for topic, names in (("fish-wall", NEW[:2]), ("fish-solo-burst", NEW[2:])):
        assert f"id: '{topic}'" in help_src
        assert f'topic="{topic}"' in linked
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
