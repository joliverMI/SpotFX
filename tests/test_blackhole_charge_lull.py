"""The Black Hole charge/lull rework (his ask, 2026-08-24, item 5) — the
drop is deliberately untouched by it and is pinned here too.

    "for charge: instead of the black hole expanding, accelerate the number
    of blobs forming (up to 12/second, but not all at once), ignore max
    counts, accelerate their fall speed, and increase the thickness of the
    event horizon slowly. Then, on the lull, continue the fast blob falling
    but expand the event horizon until it fills the hex (i think it
    currently expands too far) at half way through the duration of the
    lull. So half of the lull should be dark. Then the drop can stay the
    same as it is now."

Frame-level, on the real vendored effects (fx.headless, audio silenced).
scripts/check_blackhole_charge_lull.py is the measured, printed version of
the same runs, including the darkness measured over crystal-mapper's REAL
cells and the strip mirror."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import headless
from fx.effects import blackhole as bh
from fx.effects import blackhole1d as bh1d

DT = 1.0 / 60.0
CHARGE_S = 4.0
LULL_S = 2.5

CFG = {
    "horizon_scale": 0.2, "blob_size": 1.75, "swirl": 0.0, "reverse": False,
    "horizon_audio": 0.3, "base_speed": 2.0, "accel": 5.0, "spawn_rate": 30.0,
    "beat_burst": 0, "spawn_audio": 1.5, "speed_audio": 2.0,
    "max_blobs": 50, "edge_speed": 0.2, "horizon_hold": 2.8,
}


async def _drive(tmp_path, sub, effect_type="blackhole", config=None,
                 through_drop=True):
    """The production sequence scene_response._drive_phase drives."""
    host = await headless.start_headless_host(
        str(tmp_path / sub), device_id=sub, pixel_count=72 * 37, rows=37)
    virtual = host.virtuals.get(sub)
    rows = {"charge": [], "lull": []}
    forced = []
    burst_frames = []
    frame = [0]
    with headless.fake_clock() as clock:
        effect = headless.attach_effect(host, virtual, effect_type,
                                        dict(CFG, **(config or {})))
        two_d = hasattr(effect, "_horizon_radius")
        orig_spawn, orig_burst = effect._spawn, effect._phase_burst
        where = {"phase": "none", "p": 0.0}

        def logged_spawn(count, beat_count, *a, _o=orig_spawn, **kw):
            before = effect.n
            _o(count, beat_count, *a, **kw)
            if effect.n > before and kw.get("ignore_cap"):
                forced.append({"phase": where["phase"], "p": where["p"],
                               "added": effect.n - before, "frame": frame[0],
                               "ambient": int(effect.n - np.count_nonzero(
                                   effect.p_nocap[: effect.n]))
                               if hasattr(effect, "p_nocap") else effect.n})

        def logged_burst(*a, _o=orig_burst, **kw):
            burst_frames.append(frame[0])
            return _o(*a, **kw)

        effect._spawn = logged_spawn
        effect._phase_burst = logged_burst

        def step(n):
            for _ in range(n):
                clock.advance(DT)
                f = virtual.assemble_frame()
                if f is not None:
                    virtual.flush(f)
                frame[0] += 1

        def snap(phase, p):
            rows[phase].append({
                "p": p,
                "rh": effect._horizon_radius() if two_d else 0.0,
                "disc": effect._disc_radius(effect._horizon_radius())
                if two_d else 0.0,
                "rate": effect._phase_spawn_rate(),
                "speed": effect._phase_speed_mult(),
                "frame": np.asarray(virtual.assemble_frame(), dtype=np.float32),
            })

        step(int(4.0 / DT))          # fill the ordinary population first
        base_rh = effect._horizon_radius() if two_d else 0.0

        where.update(phase="charge", p=0.0)
        effect.update_config({"phase": "charge", "phase_progress": 0.0})
        n_c = int(CHARGE_S / DT)
        for i in range(1, n_c + 1):
            where["p"] = i / n_c
            effect.update_config({"phase_progress": where["p"]})
            step(1)
            snap("charge", where["p"])

        where.update(phase="lull", p=0.0)
        effect.update_config({"phase": "lull", "phase_progress": 0.0})
        n_l = int(LULL_S / DT)
        for i in range(1, n_l + 1):
            where["p"] = i / n_l
            effect.update_config({"phase_progress": where["p"]})
            step(1)
            snap("lull", where["p"])

        drop_entry = frame[0]
        end_phase = effect._phase
        if through_drop:
            where.update(phase="drop", p=0.0)
            effect.update_config({"phase": "drop", "phase_progress": 0.0})
            n_d = int(0.4 / DT)
            for i in range(1, n_d + 1):
                effect.update_config({"phase_progress": i / n_d})
                step(1)
            step(int(0.6 / DT))
            end_phase = effect._phase
        end_reverse = effect.reverse
        r_max = float(getattr(effect, "r_max", 0.0))
    await host.shutdown()
    return {"rows": rows, "forced": forced, "burst_frames": burst_frames,
            "drop_entry": drop_entry, "end_phase": end_phase,
            "end_reverse": end_reverse, "base_rh": base_rh, "r_max": r_max}


def _real_mask():
    import json
    prof = json.loads((Path(__file__).resolve().parent.parent
                       / "storage/device_profiles/crystal-mapper.json")
                      .read_text(encoding="utf-8"))
    mask, v = [], False
    for run in prof["mask_rle"]:
        mask.extend([v] * run)
        v = not v
    return np.array(mask, dtype=bool).reshape(prof["rows"], prof["cols"])


def _rate(forced, phase, lo, hi, phase_s):
    win = [r for r in forced if r["phase"] == phase and lo <= r["p"] <= hi]
    return sum(r["added"] for r in win) / max((hi - lo) * phase_s, 1e-9)


def test_charge_holds_the_radius_and_thickens_the_ring(tmp_path):
    """"instead of the black hole expanding": the horizon radius holds at
    its musical baseline for the whole build, and no separate black disc
    grows behind it either. The ring's THICKNESS is what builds."""
    res = asyncio.run(_drive(tmp_path, "hold"))
    ch = res["rows"]["charge"]
    assert all(abs(r["rh"] - res["base_rh"]) < 0.06 for r in ch)
    assert all(abs(r["disc"] - r["rh"]) < 1e-9 for r in ch)
    assert bh.CHARGE_HALO_W_MAX > bh.CHARGE_HALO_W_MIN


def test_charge_formation_accelerates_to_twelve_a_second_past_the_cap(tmp_path):
    """A RATE through an accumulator, accelerating to his 12/second, landing
    even with the ordinary population already at max_blobs."""
    res = asyncio.run(_drive(tmp_path, "rate"))
    early = _rate(res["forced"], "charge", 0.0, 0.25, CHARGE_S)
    late = _rate(res["forced"], "charge", 0.9, 1.0, CHARGE_S)
    assert late >= bh.CHARGE_SPAWN_RATE_MAX
    assert early < late / 4.0, "it accelerates in, never all at once"
    per_frame = {}
    for r in res["forced"]:
        per_frame[r["frame"]] = per_frame.get(r["frame"], 0) + r["added"]
    assert max(per_frame.values()) <= 2
    at_cap = [r for r in res["forced"] if r["ambient"] >= CFG["max_blobs"] - 2]
    assert len(at_cap) >= len(res["forced"]) // 2


def test_charge_accelerates_the_fall_and_the_lull_holds_it(tmp_path):
    res = asyncio.run(_drive(tmp_path, "speed"))
    ch, lu = res["rows"]["charge"], res["rows"]["lull"]
    assert ch[0]["speed"] < ch[-1]["speed"]
    assert abs(ch[-1]["speed"] - bh.CHARGE_FALL_SPEED_MAX) < 0.05
    assert all(abs(r["speed"] - bh.CHARGE_FALL_SPEED_MAX) < 1e-6 for r in lu)


def test_lull_fills_the_hex_at_half_progress_then_holds_dark(tmp_path):
    """The horizon reaches the hex silhouette's own bound at
    phase_progress=0.5 and HOLDS — never r_max, the rectangle corner the old
    swallow grew to ("i think it currently expands too far") — and every
    REAL cell of his panel is black for the rest of the lull."""
    res = asyncio.run(_drive(tmp_path, "fill", through_drop=False))
    lu = res["rows"]["lull"]
    fill_r = bh.HEX_FILL_RADIUS + bh.LULL_FILL_MARGIN
    at_half = min((r for r in lu if r["p"] >= bh.LULL_FILL_PROGRESS),
                  key=lambda r: r["p"])
    assert abs(at_half["rh"] - fill_r) < 0.03
    after = [r for r in lu if r["p"] > bh.LULL_FILL_PROGRESS]
    assert after and all(abs(r["rh"] - fill_r) < 0.03 for r in after)
    assert fill_r < res["r_max"] - 0.2
    mask = _real_mask()
    for r in after:
        assert float(r["frame"].reshape(37, 72, -1)[mask].max()) == 0.0
    # …and the FIRST half is genuinely not dark yet
    before = [r for r in lu if r["p"] < bh.LULL_FILL_PROGRESS * 0.5]
    assert any(float(r["frame"].reshape(37, 72, -1)[mask].max()) > 0
               for r in before)


def test_lull_keeps_forming_until_it_is_dark_then_stops(tmp_path):
    """"continue the fast blob falling" through the first half; nothing
    spawns unseen after the panel goes dark."""
    res = asyncio.run(_drive(tmp_path, "lullrate", through_drop=False))
    before = _rate(res["forced"], "lull", 0.05,
                   bh.LULL_FILL_PROGRESS - 0.05, LULL_S)
    after = _rate(res["forced"], "lull", bh.LULL_FILL_PROGRESS + 0.05, 1.0,
                  LULL_S)
    assert before >= bh.CHARGE_SPAWN_RATE_MAX
    assert after == 0.0


def test_the_drop_is_unchanged(tmp_path):
    """"Then the drop can stay the same as it is now": the payoff still
    fires on the drop's own first frame, the phase still self-resets after
    DROP_RESET_S, and the saved reverse is still restored."""
    res = asyncio.run(_drive(tmp_path, "drop"))
    assert res["burst_frames"]
    assert res["burst_frames"][0] - res["drop_entry"] <= 1
    assert res["end_phase"] == "none"
    assert res["end_reverse"] == CFG["reverse"]


def test_the_strip_mirrors_the_formation_and_the_half_dark_lull(tmp_path):
    """blackhole1d: the same accelerating formation and the same
    half-way-dark lull ("fills the hex" becomes "covers the strip"), with
    its own drop untouched. The pre-existing lull phosphor dot stays."""
    res = asyncio.run(_drive(tmp_path, "strip", effect_type="blackhole1d",
                             config={"reverse": True}))
    late = _rate(res["forced"], "charge", 0.9, 1.0, CHARGE_S)
    assert late >= bh1d.CHARGE_SPAWN_RATE_MAX
    lu = res["rows"]["lull"]
    after = [r for r in lu if r["p"] > bh1d.LULL_FILL_PROGRESS]
    assert after and all(float(r["frame"].max()) <= 70.0 for r in after)
    assert any(float(r["frame"].max()) > 70.0
               for r in lu if r["p"] < bh1d.LULL_FILL_PROGRESS * 0.5)
    assert res["burst_frames"]
    assert res["burst_frames"][0] - res["drop_entry"] <= 1
