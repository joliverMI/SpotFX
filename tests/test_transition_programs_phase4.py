"""THE TRANSITION PROGRAMS, PHASE 4 (fx/effects/transition_cloud.py is the
binding statement; fx/VENDOR.md #75 the effect hooks).

Measured on the real vendored pipeline (fx.headless, frame-stepped under a
fake clock, 72x37 matrix) — never a sketch:

  1. the registry, the anchors, the stages every preview draws;
  2. LENSING hands its sparks to the real Black Hole still moving (and the
     control — the same hand-off without a velocity — does not), and leaves
     on the motion the sparks had;
  3. FOUNTAIN hands its sparks to the real Fireworks still flying;
  4. FLAME LICK explodes `explode_frac` of the eye's lit cells in set
     colours, dissolves without a cut, and merges into the incoming form
     (velocity-continuous into the Black Hole, ON the moving targets of
     Orbits);
  5. IGNITION never pops the rim in, opens the slit from a hairline, and the
     real eye's body fades up FROM the brightness it was handed;
  6. SHOAL BREAK / UNRAVEL arrive ON the incoming effect's live, moving
     formation points;
  7. SHOALING: every fish starts on its blob with its velocity AND its
     turning rate (the peel), against a control without the rate;
  8. set colours only: no cell goes white on a solid-colour set;
  9. the previews carry the program's stages.

Offline throughout: tmp_path dummy hosts, no live storage or network.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import headless  # noqa: E402
from fx.effects import transition_cloud as tc  # noqa: E402
from fx.effects import transition_program as tp  # noqa: E402
from fx.host import FxHost  # noqa: E402

PIXELS, ROWS, COLS = 72 * 37, 37, 72
WARM = "linear-gradient(90deg, #ff2000 0%, #ffb000 50%, #ff00a0 100%)"
SOLID_RED = "linear-gradient(90deg, #ff0000 0%, #c00000 100%)"
# a silent rig gives Squiggles no beats to spawn on; Fireworks few sparks
WARM_UP = {"fireworks": {"spawn_rate": 6.0}, "squiggles": {"spawn_rate": 4.0}}


async def _host(tmp_path, sub):
    d = str(tmp_path / sub)
    headless.write_headless_config(d, pixel_count=PIXELS, rows=ROWS)
    headless.silence_audio()
    host = FxHost(d)
    host.audio = headless.SyntheticAudioSource()
    await host.start()
    v = host.virtuals.get(headless.DEFAULT_VIRTUAL_ID)
    v._config["transition_mode"] = "Add"
    v._config["transition_time"] = 0.5
    return host, v


def _run(coro):
    return asyncio.run(coro)


def _ang(a, b):
    d = np.arctan2(a[:, 1], a[:, 0]) - np.arctan2(b[:, 1], b[:, 0])
    return np.degrees(np.abs(np.angle(np.exp(1j * d))))


async def _program_run(tmp_path, sub, out_type, in_type, *, request=None,
                       gradient=WARM, before_switch=None, on_frame=None,
                       on_handoff=None, after=20, warm=120):
    """Switch out_type -> in_type through the registered program and record
    every frame, the program, the incoming effect, and whatever the hooks
    measure."""
    host, v = await _host(tmp_path, sub)
    out = {"frames": [], "hooks": {}}
    try:
        with headless.fake_clock() as clk:
            headless.attach_effect(host, v, out_type,
                                   {"gradient": gradient, **WARM_UP.get(out_type, {})})
            headless.render_frames(v, warm, clock=clk)
            out["last_out"] = headless.render_frames(v, 1, clock=clk)[0]
            outgoing = v.active_effect
            out["out_snap"] = outgoing._handoff_snapshot()
            new = host.effects.create(ledfx=host, type=in_type,
                                      config={"gradient": gradient})
            prog = tp.build(out_type, in_type, {"seed": 3, **(request or {})})
            assert prog is not None, (out_type, in_type)
            if before_switch:
                before_switch(prog, new, out)
            v.set_effect(new, activate=False, program=prog)
            out["transition_live"] = v._transition_effect is not None
            while not prog.done:
                f = headless.render_frames(v, 1, clock=clk)[0]
                out["frames"].append(f)
                if on_frame:
                    on_frame(prog, new, out)
                if len(out["frames"]) > 400:
                    break
            out["prog"] = prog
            out["new"] = new
            if on_handoff:
                on_handoff(prog, new, v, clk, out)
            out["after"] = headless.render_frames(v, after, clock=clk)
    finally:
        await host.shutdown()
    return out


# ── 1. registry, anchors, stages ───────────────────────────────────────────

def test_the_phase4_registry_and_anchors():
    s = tp.ProgramSettings.from_request({})
    assert tp.program_name("fireworks", "blackhole") == tp.LENSING
    assert tp.program_name("blackhole", "fireworks") == tp.FOUNTAIN
    for eye in ("sauron", "eye"):
        for other in ("blackhole", "orbits", "fish", "squiggles", "fireworks"):
            assert tp.program_name(eye, other) == tp.FLAME_LICK
            assert tp.program_name(other, eye) == tp.IGNITION
    assert tp.program_name("fish", "orbits") == tp.SHOAL_BREAK
    assert tp.program_name("fish", "squiggles") == tp.SHOAL_BREAK
    assert tp.program_name("orbits", "fish") == tp.SHOALING
    assert tp.program_name("squiggles", "orbits") == tp.UNRAVEL
    assert tp.program_name("squiggles", "fish") == tp.UNRAVEL
    assert tp.program_name("orbits", "squiggles") == tp.UNRAVEL
    # phase 3's rows stand
    assert tp.program_name("orbits", "blackhole") == tp.INFALL
    assert tp.program_name("blackhole", "orbits") == tp.ERUPTION
    # pairs with no program keep the crossfade
    for out, inc in (("sauron", "eye"), ("pacman", "sauron"), ("fish", "fireworks"),
                     ("dancer", "sauron"), ("sauron", "sauron")):
        assert tp.program_name(out, inc) is None, (out, inc)
    # the leads: Lensing's payoff is its ignition, like Infall's; the eye
    # and the shoal explode / shatter ON the mark; the threads complete
    # half way; an unspooling chain on the mark
    assert tp.lead_ms(tp.LENSING, s) == tp.lead_ms(tp.INFALL, s) == 900
    assert tp.lead_ms(tp.FOUNTAIN, s) == 420
    assert tp.lead_ms(tp.FLAME_LICK, s) == 0
    assert tp.lead_ms(tp.SHOAL_BREAK, s) == 0
    assert tp.lead_ms(tp.IGNITION, s) == 770
    assert tp.lead_ms(tp.UNRAVEL, s, "squiggles", "orbits") == 0
    assert tp.lead_ms(tp.UNRAVEL, s, "orbits", "squiggles") == 700
    # clamped, never trusted
    wild = tp.ProgramSettings.from_request(
        {"explode_frac": 7, "lensing_pull": -1, "scatter": "x"})
    assert wild.explode_frac == 1.0
    assert wild.lensing_pull == 0.2
    assert wild.scatter == tp.DEFAULT_SCATTER


def test_every_program_names_contiguous_stages_with_one_payoff():
    for on_mark in (False, True):
        s = tp.ProgramSettings.from_request({"on_mark": on_mark})
        for (out, inc) in tp.PROGRAMS:
            st = tp.stages(out, inc, s)
            assert st, (out, inc)
            assert st[0]["from"] == 0.0 and st[-1]["to"] == pytest.approx(1.0)
            for a, b in zip(st, st[1:]):
                assert a["to"] == pytest.approx(b["from"]), (out, inc, st)
            assert all(x["to"] > x["from"] for x in st)
            assert sum(1 for x in st if x.get("anchor")) == 1, (out, inc, st)
    assert tp.stages("pacman", "sauron", tp.ProgramSettings()) == []


# ── 2. lensing ─────────────────────────────────────────────────────────────

def _bh_handoff(prog, bh, v, clk, out):
    k = prog.x.size
    base = bh.n - k
    p0 = np.stack([prog.x, prog.y], 1)
    pv = np.stack([prog.vx, prog.vy], 1)
    headless.render_frames(v, 1, clock=clk)
    p1 = np.stack([
        bh.cx + bh.p_r[base:base + k] * np.cos(bh.p_theta[base:base + k]) * bh.sx,
        bh.cy + bh.p_r[base:base + k] * np.sin(bh.p_theta[base:base + k]) * bh.sy,
    ], 1)
    out["handoff"] = (pv, (p1 - p0) * 60.0)


def _strip_velocity(prog, bh, out):
    orig = bh._adopt_handoff

    def no_v(snap=None, allow_hold=True):
        if snap is not None:
            snap = {k: x for k, x in snap.items() if k not in ("vx", "vy")}
        return orig(snap=snap, allow_hold=allow_hold)
    bh._adopt_handoff = no_v


def test_lensing_hands_the_sparks_over_still_moving(tmp_path):
    r = _run(_program_run(tmp_path, "lens", "fireworks", "blackhole",
                          on_handoff=_bh_handoff))
    ctrl = _run(_program_run(tmp_path, "lensc", "fireworks", "blackhole",
                             before_switch=_strip_velocity, on_handoff=_bh_handoff))
    prog = r["prog"]
    assert prog.name == tp.LENSING and prog.done and prog.handed_off
    assert r["transition_live"] is False
    pv, after = r["handoff"]
    moving = np.linalg.norm(pv, axis=1) > 2.0
    assert moving.sum() >= 5
    dv = np.linalg.norm(after[moving] - pv[moving], axis=1)
    assert np.median(dv) < 1.0, np.median(dv)
    assert np.median(_ang(after[moving], pv[moving])) < 2.0
    # THE CONTROL: without the velocity the sparks all but stop
    cpv, cafter = ctrl["handoff"]
    cm = np.linalg.norm(cpv, axis=1) > 2.0
    assert np.median(np.linalg.norm(cafter[cm], axis=1)) < \
        0.3 * np.median(np.linalg.norm(cpv[cm], axis=1))


def test_lensing_leaves_on_the_sparks_own_motion(tmp_path):
    def first(prog, new, out):
        if prog.frames == 1:
            out["hooks"]["first"] = (prog.x.copy(), prog.y.copy())

    def snap0(prog, new, out):
        out["hooks"]["p0"] = None

    r = _run(_program_run(tmp_path, "lens0", "fireworks", "blackhole",
                          on_frame=first))
    prog = r["prog"]
    snap = r["out_snap"]
    # the cloud's first frame moves each piece by (very nearly) its own
    # inherited velocity: the pull starts at zero
    x1, y1 = r["hooks"]["first"]
    px, py, vx, vy, *_ = prog._snap_arrays()
    keep = tc._cap_by_brightness(np.clip(np.asarray(snap["bright"]), 0, 1)[
        np.isfinite(snap["px"]) & (np.clip(np.asarray(snap["bright"]), 0, 1) > 0.03)],
        tc.PIECE_CAP)
    v_first = np.stack([(x1 - px[keep]) * 60.0, (y1 - py[keep]) * 60.0], 1)
    v0 = np.stack([vx[keep], vy[keep]], 1)
    moving = np.linalg.norm(v0, axis=1) > 2.0
    assert moving.sum() >= 5
    err = np.linalg.norm(v_first[moving] - v0[moving], axis=1) \
        / np.linalg.norm(v0[moving], axis=1)
    assert np.median(err) < 0.1, np.median(err)


# ── 3. fountain ────────────────────────────────────────────────────────────

def test_fountain_hands_its_sparks_to_the_fireworks_still_flying(tmp_path):
    def watch(prog, fw, out):
        orig = fw._import_sparks

        def rec(snap):
            out["hooks"]["base"] = fw.n
            out["hooks"]["snap"] = snap
            return orig(snap)
        fw._import_sparks = rec

    def measure(prog, fw, v, clk, out):
        snap = out["hooks"]["snap"]
        base = out["hooks"]["base"]
        k = len(snap["px"])
        p0 = np.stack([snap["px"], snap["py"]], 1)
        headless.render_frames(v, 1, clock=clk)
        p1 = np.stack([fw.cx + fw.p_x[base:base + k] * fw.sx,
                       fw.cy + fw.p_y[base:base + k] * fw.sy], 1)
        out["fv"] = (np.stack([snap["vx"], snap["vy"]], 1), (p1 - p0) * 60.0)

    r = _run(_program_run(tmp_path, "fount", "blackhole", "fireworks",
                          before_switch=watch, on_handoff=measure))
    prog = r["prog"]
    assert prog.name == tp.FOUNTAIN and prog.sprayed and prog.handed_off
    pv, after = r["fv"]
    moving = np.linalg.norm(pv, axis=1) > 2.0
    assert moving.sum() >= 20
    # the fireworks' first frame continues each spark's motion
    rel = np.linalg.norm(after[moving] - pv[moving], axis=1) \
        / np.linalg.norm(pv[moving], axis=1)
    assert np.median(rel) < 0.05, np.median(rel)
    # ... and shows it at the brightness the program last drew
    assert r["prog"].last_gain == pytest.approx(1.0, abs=0.05)


# ── 4. flame lick ──────────────────────────────────────────────────────────

def _lit(f):
    return int((f.reshape(ROWS, COLS, 3).max(axis=2) > tc.LIT_MIN).sum())


@pytest.mark.parametrize("frac", [0.5, 0.25])
def test_flame_lick_explodes_its_fraction_of_the_eye(tmp_path, frac):
    r = _run(_program_run(tmp_path, f"fl{frac}", "sauron", "orbits",
                          request={"explode_frac": frac}))
    prog = r["prog"]
    assert prog.name == tp.FLAME_LICK
    pic = prog.eye_pic
    lit = int((pic.max(axis=2) > tc.LIT_MIN).sum())
    assert lit > 100
    assert prog.n == min(round(frac * lit), tc.SHARD_CAP)
    assert prog.c_x.size == lit - prog.n
    # every shard carries a set colour (the warm set's hues), never white
    assert np.all(prog.rgb_from.max(axis=1) > 200)
    assert np.all(prog.rgb_from.min(axis=1) < 160)
    # the first program frame is the eye dissolving, not a cut
    jump0 = np.abs(r["frames"][0].astype(float) - r["last_out"]).mean()
    worst = max(np.abs(np.diff(np.array(r["frames"], float), axis=0)).mean(axis=(1, 2)))
    assert jump0 < 3.0, jump0
    assert worst < 10.0, worst


def test_flame_lick_into_the_black_hole_hands_over_still_moving(tmp_path):
    r = _run(_program_run(tmp_path, "flbh", "sauron", "blackhole",
                          on_handoff=_bh_handoff))
    pv, after = r["handoff"]
    moving = np.linalg.norm(pv, axis=1) > 2.0
    assert moving.sum() >= 20
    dv = np.linalg.norm(after[moving] - pv[moving], axis=1)
    assert np.median(dv) < 1.0, np.median(dv)


def _record_cloud(prog, new, out):
    f = getattr(prog, "former", None)
    if isinstance(f, tc.TargetFormer) and f._tq is not None:
        out["hooks"]["last"] = (prog.x.copy(), prog.y.copy(), prog.vx.copy(),
                                prog.vy.copy(), f.j.copy(), f._tq, f._tu,
                                prog.form_fade.copy())


@pytest.mark.parametrize("pair,sub", [
    (("sauron", "orbits"), "flo"), (("fish", "orbits"), "sbo"),
    (("squiggles", "orbits"), "uno"), (("orbits", "squiggles"), "uns"),
    (("fish", "squiggles"), "sbs")])
def test_the_cloud_arrives_on_the_moving_incoming_form(tmp_path, pair, sub):
    r = _run(_program_run(tmp_path, sub, *pair, on_frame=_record_cloud))
    prog = r["prog"]
    assert prog.done and isinstance(prog.former, tc.TargetFormer)
    assert prog.former.targets_seen
    x, y, vx, vy, j, tq, tu, fade = r["hooks"]["last"]
    m = tq[0].size
    on = j >= 0
    assert on.mean() > 0.95
    jj = j[on] % m
    d = np.hypot(x[on] - tq[0][jj], y[on] - tq[1][jj])
    assert np.max(d) < 0.5, np.max(d)
    # every piece has faded into its target by the end
    assert np.max(fade) < 0.05
    if pair[1] == "orbits":
        # the targets really move, and the pieces arrive moving with them
        assert np.median(np.hypot(tu[0], tu[1])) > 1.0
        dv = np.hypot(vx[on] - tu[0][jj], vy[on] - tu[1][jj])
        assert np.median(dv) < 3.0, np.median(dv)
    assert prog.last_gain == pytest.approx(1.0, abs=0.05)


def test_unravel_dots_start_on_the_chains(tmp_path):
    def cells(prog, new, out):
        if prog.frames == 1:
            out["hooks"]["x0"] = (prog.x.copy(), prog.y.copy())
    r = _run(_program_run(tmp_path, "unc", "squiggles", "fish", on_frame=cells))
    prog = r["prog"]
    x, y = r["hooks"]["x0"]
    cells_ = np.concatenate([p for p, _g, _b in prog.paths]) + 0.5
    d = np.min(np.hypot(x[:, None] - cells_[None, :, 0],
                        y[:, None] - cells_[None, :, 1]), axis=1)
    # a frame in, the unspooling dots are still on (or a hair off) a cell
    assert np.median(d) < 0.6
    # released tail first: the release times rise along each chain
    assert prog.t_rel.max() == pytest.approx(tc.UNSPOOL_S, abs=1e-3)


# ── 5. ignition ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("eye", ["sauron", "eye"])
def test_ignition_builds_the_rim_with_the_eye_and_hands_over_its_brightness(
        tmp_path, eye):
    def rim(prog, new, out):
        rr = getattr(new, "program_rim", None)
        if rr is None:
            return
        f = out["frames"][-1].reshape(ROWS, COLS, 3).astype(float)
        yy, xx = np.mgrid[0:ROWS, 0:COLS]
        band = np.abs(np.hypot(xx + 0.5 - rr[0], yy + 0.5 - rr[1]) - rr[2]) < 1.2
        whole = np.hypot(xx + 0.5 - rr[0], yy + 0.5 - rr[1]) < rr[2] + 6
        out["hooks"].setdefault("rim", []).append(f[band].max(axis=1).mean())
        out["hooks"].setdefault("eye", []).append(f[whole].max(axis=1).mean())
        out["hooks"].setdefault("lens", []).append(new._lens_gain)

    def after(prog, new, v, clk, out):
        out["hooks"]["fade_up"] = dict(new._fade_up) if new._fade_up else None
        out["hooks"]["lens_after"] = new._lens_gain

    r = _run(_program_run(tmp_path, "ig" + eye, "blackhole", eye,
                          on_frame=rim, on_handoff=after))
    prog = r["prog"]
    assert prog.name == tp.IGNITION and prog.done
    rim_ = np.array(r["hooks"]["rim"])
    # the ring never appears before the rest of the eye: it starts dark and
    # rises with the fill (the clouds' own sparks are allowed — they are
    # ~1 cell each — so measure against the end)
    assert rim_[0] < 0.25 * rim_[-1], rim_[:5]
    lens = np.array(r["hooks"]["lens"])
    assert lens[0] == pytest.approx(tc.LENS_MIN, abs=1e-3)
    assert lens[-1] == pytest.approx(1.0, abs=0.02)
    assert np.all(np.diff(lens) >= -1e-6)
    assert r["hooks"]["lens_after"] == 1.0
    # the hand-off: the real eye fades up FROM the handed brightness
    fu = r["hooks"]["fade_up"]
    assert fu is not None and fu["g0"] == pytest.approx(tc.IGNITION_HANDOFF_GAIN)
    seam = np.abs(r["after"][0].astype(float) - r["frames"][-1].astype(float)).mean()
    assert seam < 3.0, seam


def test_an_ordinary_adoption_fades_up_from_a_handed_brightness(tmp_path):
    async def go():
        host, v = await _host(tmp_path, "fu")
        try:
            with headless.fake_clock() as clk:
                headless.attach_effect(host, v, "sauron", {"gradient": WARM})
                headless.render_frames(v, 2, clock=clk)
                eye = v.active_effect
                snap = {"src": "orbits", "dims": (COLS, ROWS),
                        "px": np.array([10.0, 20.0, 30.0], np.float32),
                        "py": np.array([10.0, 12.0, 14.0], np.float32),
                        "grad": np.zeros(3, np.float32),
                        "bright": np.ones(3, np.float32),
                        "body_gain": 0.6}
                eye._adopt_handoff(snap=snap, allow_hold=False)
                g_handed = eye._infall["g0"]
                snap.pop("body_gain")
                eye._adopt_handoff(snap=snap, allow_hold=False)
                return g_handed, eye._infall["g0"]
        finally:
            await host.shutdown()
    handed, default = _run(go())
    assert handed == pytest.approx(0.6)
    assert default == pytest.approx(0.25)   # unchanged when nothing is handed


# ── 7. shoaling: the peel ──────────────────────────────────────────────────

async def _shoaling(tmp_path, sub, strip_om):
    host, v = await _host(tmp_path, sub)
    try:
        with headless.fake_clock() as clk:
            headless.attach_effect(host, v, "orbits", {"gradient": WARM})
            headless.render_frames(v, 150, clock=clk)
            snap = v.active_effect._handoff_snapshot()
            fish = host.effects.create(ledfx=host, type="fish",
                                       config={"gradient": WARM})
            prog = tp.build("orbits", "fish", {"seed": 1})
            if strip_om:
                orig = fish._adopt_handoff

                def no_om(snap=None, allow_hold=True):
                    if snap is None:
                        from fx.effects import particle_handoff
                        snap = particle_handoff.take(v.id)
                    if snap is not None:
                        snap = {k: x for k, x in snap.items() if k != "om"}
                    return orig(snap=snap, allow_hold=allow_hold)
                fish._adopt_handoff = no_om
            v.set_effect(fish, activate=False, program=prog)
            hds, poss = [], []
            for _ in range(3):
                headless.render_frames(v, 1, clock=clk)
                n = fish.n
                hds.append(fish.p_hd[:n].copy())
                poss.append(np.stack([fish.cx + fish.p_x[:n] * fish.sx - fish.cam_px,
                                      fish.cy + fish.p_y[:n] * fish.sy - fish.cam_py], 1))
            while not prog.done:
                headless.render_frames(v, 1, clock=clk)
            return snap, hds, poss, fish
    finally:
        await host.shutdown()


def test_shoaling_fish_start_on_their_blobs_with_the_blobs_motion(tmp_path):
    snap, hds, poss, fish = _run(_shoaling(tmp_path, "sh", strip_om=False))
    _c, chds, cposs, _cf = _run(_shoaling(tmp_path, "shc", strip_om=True))
    blobs = np.stack([snap["px"], snap["py"]], 1)
    bv = np.stack([snap["vx"], snap["vy"]], 1)
    om = np.asarray(snap["om"])
    # match each adopted fish to its blob (the brightest blobs are taken)
    d = np.linalg.norm(poss[0][:, None, :] - blobs[None, :, :], axis=2)
    fi = np.flatnonzero(d.min(axis=1) < 2.0)
    assert fi.size >= 2, d.min(axis=1)
    bi = d[fi].argmin(axis=1)
    moving = np.linalg.norm(bv[bi], axis=1) > 3.0
    fi, bi = fi[moving], bi[moving]
    assert fi.size >= 2
    # velocity continuous: the fish's first-frame motion is its blob's
    vf = (poss[1][fi] - poss[0][fi]) * 60.0
    assert np.median(_ang(vf, bv[bi])) < 10.0
    # and the TURNING RATE too (the peel), against the control's
    def rate(h):
        return np.angle(np.exp(1j * (h[1][fi] - h[0][fi]))) * 60.0
    err = np.abs(rate(hds) - om[bi])
    cerr = np.abs(rate(chds) - om[bi])
    turning = np.abs(om[bi]) > 0.5
    if turning.any():
        assert np.median(err[turning]) < 0.5 * np.median(cerr[turning]) + 1e-6, \
            (err[turning], cerr[turning])
    # the peel has finished by the end of the program
    assert fish._peel_age is None


# ── 8. set colours only ────────────────────────────────────────────────────

@pytest.mark.parametrize("pair", [
    ("fireworks", "blackhole"), ("blackhole", "fireworks"), ("blackhole", "sauron"),
    ("fish", "orbits"), ("orbits", "fish"), ("squiggles", "orbits"),
    ("sauron", "orbits")])
def test_a_solid_colour_set_never_goes_white(tmp_path, pair):
    r = _run(_program_run(tmp_path, "w" + "".join(pair), *pair,
                          gradient=SOLID_RED))
    prog = r["prog"]
    # the outgoing eye's own picture (its white-hot core) is drawn only
    # while it dissolves; everything the program itself paints is the set
    skip = int(np.ceil(tc.DISSOLVE_S * 60)) + 2 if pair[0] == "sauron" else 0
    for f in r["frames"][skip:]:
        assert int(((f > 200).all(axis=1)).sum()) == 0
    assert prog.done


# ── 9. the previews carry the stages ───────────────────────────────────────

def test_the_previews_carry_the_program_stages():
    from spectra.services import room_controls as rc
    from spectra.services import scene_transition_lead as stl
    from spectra.services.transition_preview import _program_on_ruler
    room = rc.RoomControlState()
    writes = [{"virtual_id": "m", "effect_type": "sauron"},
              {"virtual_id": "s", "effect_type": "power"}]
    p = stl.program_stages({"m": "blackhole", "s": "power"}, writes, room)
    assert p["name"] == tp.IGNITION and p["duration_ms"] == 1400
    placed = _program_on_ruler(p, 2.0, 1.4)
    assert placed["stages"][0]["from_s"] == pytest.approx(2.0)
    assert placed["stages"][-1]["to_s"] == pytest.approx(3.4)
    anchor = [s for s in placed["stages"] if s["anchor"]][0]
    # the payoff stage opens exactly where the lead says the mark is
    assert anchor["from_s"] - 2.0 == pytest.approx(
        stl.program_lead_ms({"m": "blackhole"}, writes, room) / 1000.0, abs=1e-3)
    assert stl.program_stages({"m": "pacman"}, writes, room) is None
    off = room.model_copy(update={"transition_programs_enabled": False})
    assert stl.program_stages({"m": "blackhole"}, writes, off) is None


def test_a_drop_led_program_cut_draws_its_stages_from_the_cut():
    from types import SimpleNamespace

    from spectra.services import drop_switch as ds
    from spectra.services import phase_preview
    plan = SimpleNamespace(handoff=ds.HANDOFF_PROGRAM, from_effect="blackhole",
                           to_effect="fireworks")
    out = phase_preview._switch_program(plan, 5.0)
    assert out["name"] == tp.FOUNTAIN
    # on the mark: the payoff stage opens on the cut itself
    anchor = [s for s in out["stages"] if s["anchor"]][0]
    assert anchor["from_s"] == pytest.approx(5.0)
    plain = SimpleNamespace(handoff=ds.HANDOFF_GENERIC, from_effect="x",
                            to_effect="y")
    assert phase_preview._switch_program(plain, 5.0) is None


def test_drop_switch_runs_the_new_programs_on_the_mark():
    from spectra.services import drop_switch as ds
    assert ds.handoff_kind("blackhole", "fireworks") == ds.HANDOFF_PROGRAM
    assert ds.handoff_kind("fish", "orbits") == ds.HANDOFF_PROGRAM
    assert ds.handoff_kind("squiggles", "fish") == ds.HANDOFF_PROGRAM
    # the fireworks melds keep their rows
    assert ds.handoff_kind("fireworks", "blackhole") == ds.HANDOFF_SWALLOWED
    assert ds.handoff_kind("orbits", "fireworks") == ds.HANDOFF_KEEPERS
