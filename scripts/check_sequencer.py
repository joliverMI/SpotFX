"""Executable spec for the SPECTRA sequencer — decision-complete per
data/spectra-sequencing-design/decision-five-answers.md: models, curve
evaluation, composition + fallback ladder, dwell-in-songs, the
transition-only engine clock, flare selector, rainbow exemption, store,
agent-adjustment API, seeder.
Run from repo root: .venv/bin/python scripts/check_sequencer.py
Isolated: temp files for the store and profile census; fakes injected into
the engine; no live storage, no LedFX I/O, no audio."""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from random import Random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pydantic import ValidationError

from models.color_set import ColorSetCard, ColorSetEntry
from models.sequencer import (AffinityEdge, CurvePoint, CurveProfile,
                              SelectorEntry, SequencerConfig)
from services import color_wheel
from services.selection_kernel import (Candidate, TERMINAL_NOTHING,
                                       TERMINAL_STAY, affinity_multiplier,
                                       build_flare_candidates,
                                       build_scene_candidates, compose,
                                       curve_eval, genre_multiplier,
                                       resolve_curve, resolve_dwell_songs,
                                       select, select_flare, wheel_travel_deg,
                                       wheel_travel_mult)


def check(cond, label):
    if not cond:
        raise SystemExit(f"FAIL: {label}")
    print(f"ok: {label}")


def expect_invalid(model, label, **kwargs):
    try:
        model(**kwargs)
        raise SystemExit(f"FAIL: {label} — accepted")
    except ValidationError:
        print(f"ok: {label} rejected")


def pts(*pairs):
    return [CurvePoint(x=x, y=y) for x, y in pairs]


SWEEP = [i / 200 for i in range(201)]

# ── model validation ─────────────────────────────────────────────────────────
expect_invalid(CurvePoint, "point x > 1", x=1.2, y=0.5)
expect_invalid(CurvePoint, "negative y", x=0.5, y=-0.1)
expect_invalid(CurveProfile, "empty curve", name="e", points=[])
expect_invalid(CurveProfile, "unsorted x", name="u", points=pts((0.5, 1), (0.2, 1)))
step = CurveProfile(name="step", points=pts((0, 0), (0.45, 0), (0.45, 1)))
check(len(step.points) == 3, "duplicate x allowed — a step discontinuity")

entry = SelectorEntry()
check(entry.dwell_weight == 1.0 and entry.curve_ref is None
      and entry.inline_points is None and entry.genre_mult == {},
      "SelectorEntry defaults: dwell 1.0, no curve (≡ flat 1.0), no genre mults")
expect_invalid(SelectorEntry, "dwell_weight 0 (must be > 0)", dwell_weight=0.0)
expect_invalid(SelectorEntry, "negative dwell_weight", dwell_weight=-2.0)
expect_invalid(SelectorEntry, "negative genre mult", genre_mult={"edm": -1.0})
expect_invalid(SelectorEntry, "curve_ref AND inline_points",
               curve_ref="p1", inline_points=pts((0, 1)))
check(SelectorEntry(inline_points=pts((0, 0.7))).inline_points[0].y == 0.7,
      "inline one-off curve accepted")

edge = AffinityEdge(from_id="drop", to_id="quiet", mult=2.5)
check(edge.from_id == "drop" and edge.to_id == "quiet",
      "affinity edge: explicit from/to, directional by construction")
check(AffinityEdge(from_id="a", to_id="b").mult == 1.0, "affinity mult defaults 1.0")
expect_invalid(AffinityEdge, "self-affinity (the diagonal IS dwell_weight)",
               from_id="x", to_id="x")

config = SequencerConfig(
    entries={"s1": SelectorEntry(dwell_weight=2.0, genre_mult={"edm": 1.5})},
    affinity=[AffinityEdge(from_id="a", to_id="b", mult=2.5),
              AffinityEdge(from_id="b", to_id="a", mult=0.5)])
check(len(config.affinity) == 2, "A→B and B→A are distinct edges")
expect_invalid(SequencerConfig, "duplicate affinity edge",
               affinity=[AffinityEdge(from_id="a", to_id="b"),
                         AffinityEdge(from_id="a", to_id="b", mult=2.0)])
check(SequencerConfig(**json.loads(config.model_dump_json())).entries["s1"].dwell_weight == 2.0,
      "config JSON round-trip")
check(config.enabled is False, "sequencer's own dark switch defaults OFF")
check(config.change_mode == "transition",
      "decision 5: shipped default change_mode is transition — no timer")
check(config.flare_entries == {}, "flare selector entries default empty")

# ── curve_eval identities ────────────────────────────────────────────────────
flat = pts((0.3, 0.7))
check(all(curve_eval(flat, x) == 0.7 for x in (0.0, 0.3, 0.5, 1.0)),
      "one flat point ≡ scalar weight 0.7 everywhere")
ramp = pts((0.2, 0.0), (0.8, 1.0))
check(abs(curve_eval(ramp, 0.5) - 0.5) < 1e-12, "linear interpolation at midpoint")
check(curve_eval(ramp, 0.0) == 0.0 and curve_eval(ramp, 1.0) == 1.0,
      "clamped flat outside the outer points")
check(curve_eval(step.points, 0.45) == 1.0, "at a duplicate x the later point wins")

w = 1.7
legacy_floor = lambda e: w if e >= 0.45 else 0.0   # trigger_engine energy gate
floor_curve = pts((0, 0), (0.45, 0), (0.45, w))
check(all(curve_eval(floor_curve, e) == legacy_floor(e) for e in SWEEP + [0.45]),
      "legacy energy_floor=0.45 gate ≡ 3-point curve (exact, incl. the boundary)")

lo, hi, s = 0.2, 0.9, 0.6
tilt_curve = pts((lo, 1 - s), (hi, 1 + s))
legacy_tilt = lambda e: 1 + s * (2 * ((e - lo) / (hi - lo)) - 1)   # trigger_engine:2338
check(all(abs(curve_eval(tilt_curve, e) - legacy_tilt(e)) < 1e-9
          for e in SWEEP if lo <= e <= hi),
      "energy_scale tilt 1+s·(2t−1) ≡ two-point line across the window")

# ── composition (decisions 1+2): multiply, zero is a hard veto ───────────────
check(compose(0.8, 1.5, 2.0) == 0.8 * 1.5 * 2.0, "score = curve × genre × affinity")
check(compose(0.0, 9.0, 9.0) == 0.0 and compose(0.9, 0.0, 9.0) == 0.0
      and compose(0.9, 9.0, 0.0) == 0.0,
      "zero from ANY factor vetoes the candidate")

profile_lib = {"p1": CurveProfile(id="p1", name="ramp", points=ramp)}
check(resolve_curve(SelectorEntry(curve_ref="p1"), profile_lib) == ramp,
      "curve_ref resolves the named profile")
check(resolve_curve(SelectorEntry(inline_points=flat), profile_lib) == flat,
      "inline escape hatch wins when set")
check(curve_eval(resolve_curve(SelectorEntry(), profile_lib), 0.42) == 1.0,
      "no curve ≡ flat 1.0")
check(genre_multiplier(SelectorEntry(genre_mult={"EDM": 1.5}), "edm") == 1.5,
      "genre bucket matched case-insensitively")
check(genre_multiplier(SelectorEntry(genre_mult={"EDM": 1.5}), None) == 1.0
      and genre_multiplier(SelectorEntry(), "edm") == 1.0,
      "no bucket / unstated genre = neutral ×1.0")
edges = [AffinityEdge(from_id="drop", to_id="quiet", mult=2.5)]
check(affinity_multiplier(edges, "drop", "quiet") == 2.5
      and affinity_multiplier(edges, "quiet", "drop") == 1.0
      and affinity_multiplier(edges, None, "quiet") == 1.0,
      "affinity lookup is directional; missing edge / no prev = ×1.0")

# ── selection: weighted draw, exclusion, veto ────────────────────────────────
FLAT1 = pts((0, 1.0))
N = 8000
rng = Random(42)
cands = [Candidate(id="a", points=FLAT1),
         Candidate(id="b", points=pts((0, 3.0))),
         Candidate(id="z", points=pts((0, 0.0)))]
counts = {"a": 0, "b": 0, "z": 0}
for _ in range(N):
    pick = select(cands, intensity=0.5, rng=rng)
    counts[pick.picked_id] += 1
    if pick.rung != "full":
        raise SystemExit("FAIL: fallback rung on a drawable config")
check(counts["z"] == 0, f"curve at zero is a hard veto (0 of {N} draws)")
check(abs(counts["b"] / N - 0.75) < 0.02,
      f"draw proportional to scores (3:1 → {counts['b'] / N:.3f} ≈ 0.75)")

seen = {select([Candidate(id="a", points=FLAT1), Candidate(id="b", points=FLAT1)],
               intensity=0.5, rng=rng, current_id="a").picked_id
        for _ in range(200)}
check(seen == {"b"}, "current scene excluded from the draw — stay is dwell's job")

# directional affinity biases among the eligible but never overrides the curve
aff_cands = [Candidate(id="quiet", points=FLAT1, affinity_mult=2.5),
             Candidate(id="loud", points=FLAT1, affinity_mult=1.0),
             Candidate(id="gated", points=pts((0, 0.0)), affinity_mult=99.0)]
aff_counts = {"quiet": 0, "loud": 0, "gated": 0}
for _ in range(N):
    aff_counts[select(aff_cands, intensity=0.5, rng=rng).picked_id] += 1
check(aff_counts["gated"] == 0 and abs(aff_counts["quiet"] / N - 2.5 / 3.5) < 0.02,
      "affinity biases the eligible (×2.5 → ~71%) but cannot revive a zero curve")

# ── the fallback ladder, rung by rung ────────────────────────────────────────
ladder_rng = Random(7)

pick = select([Candidate(id="a", points=FLAT1, affinity_mult=0.0),
               Candidate(id="b", points=FLAT1, affinity_mult=0.0)],
              intensity=0.5, rng=ladder_rng)
check(pick.rung == "no_affinity" and pick.picked_id in ("a", "b"),
      "rung 1: all affinity-vetoed → affinity dropped")

pick = select([Candidate(id="a", points=FLAT1, genre_mult=0.0, affinity_mult=0.0)],
              intensity=0.5, rng=ladder_rng)
check(pick.rung == "no_genre" and pick.picked_id == "a",
      "rung 2: genre veto dropped after affinity")

pick = select([Candidate(id="cur", points=FLAT1),
               Candidate(id="other", points=pts((0, 0.0)))],
              intensity=0.5, rng=ladder_rng, current_id="cur")
check(pick.rung == "readmit_current" and pick.picked_id == "cur",
      "rung 3: only the current scene is curve-eligible → re-admitted")

inf_pts = [CurvePoint(x=0.0, y=float("inf"))]
uni = {select([Candidate(id="a", points=inf_pts), Candidate(id="b", points=inf_pts),
               Candidate(id="z", points=pts((0, 0.0)))],
              intensity=0.5, rng=ladder_rng).picked_id for _ in range(200)}
check(uni == {"a", "b"},
      "rung 4: non-finite scores fall through to UNIFORM among curve-eligible "
      "(zero curve still out)")

pick = select([Candidate(id="a", points=pts((0, 0.0)))],
              intensity=0.5, rng=ladder_rng, terminal=TERMINAL_STAY)
check(pick.picked_id is None and pick.rung == "stay",
      "scene ladder terminates at STAY — a room must always show something")
check(select([], intensity=0.5, rng=ladder_rng).rung == "stay",
      "empty candidate set → stay")

pick = select_flare([Candidate(id="f1", points=pts((0, 0), (0.8, 0), (0.8, 1)))],
                    intensity=0.5, rng=ladder_rng)
check(pick.picked_id is None and pick.rung == TERMINAL_NOTHING,
      "flare ladder terminates at NOTHING — all-gated-out means silence")
check(select_flare([Candidate(id="f1", points=FLAT1, genre_mult=0.0)],
                   intensity=0.5, rng=ladder_rng).rung == "no_genre",
      "flare selector is curve × genre only; its ladder still relaxes genre")

# every pick carries the full-factor breakdown for observability
pick = select([Candidate(id="a", points=ramp, genre_mult=1.5, affinity_mult=2.0)],
              intensity=0.5, rng=ladder_rng)
f = pick.factors["a"]
check(abs(f["curve"] - 0.5) < 1e-9 and f["genre"] == 1.5 and f["affinity"] == 2.0
      and abs(f["score"] - 1.5) < 1e-9,
      "pick.factors carries curve/genre/affinity/score per candidate")

# ── dwell in songs (decision 5): fractional weights resolve probabilistically ─
d_rng = Random(11)
check(all(resolve_dwell_songs(2.0, d_rng) == 2 for _ in range(50)),
      "integer weight 2 → always 2 songs")
halves = [resolve_dwell_songs(1.5, d_rng) for _ in range(6000)]
check(set(halves) == {1, 2} and abs(sum(halves) / len(halves) - 1.5) < 0.05,
      "weight 1.5 → one song half the time, two the other half (mean 1.5)")
means = {wt: sum(resolve_dwell_songs(wt, d_rng) for _ in range(6000)) / 6000
         for wt in (1.0, 2.0, 3.0, 2.5)}
check(all(abs(means[wt] - wt) < 0.06 for wt in means),
      f"mean dwell (songs) proportional to weight: {means}")

# ── rainbow exemption (binding wheel rule) ───────────────────────────────────
rgb = ColorSetCard(name="rgb", entries=[
    ColorSetEntry(color_kind="solid", color_value=c)
    for c in ("#ff0000", "#00ff00", "#0000ff")])
position = color_wheel.wheel_position(rgb)
check(position.rainbow and position.position_deg is None,
      "R/G/B set carries the rainbow tag (span > 180°, no position)")
prefer_near = pts((0, 1.0), (1, 0.0))   # 'prefer small steps' downhill line
check(wheel_travel_mult(prefer_near, position.position_deg, 120.0) == 1.0
      and wheel_travel_mult(prefer_near, 120.0, position.position_deg) == 1.0,
      "rainbow set is neutral ×1.0 on either side of the travel factor")
check(wheel_travel_deg(None, None) is None, "achromatic/rainbow travel is undefined, not 0")
check(abs(wheel_travel_deg(10.0, 350.0) - 20.0) < 1e-9, "travel wraps the wheel (10°↔350° = 20°)")
check(abs(wheel_travel_mult(prefer_near, 0.0, 90.0) - 0.5) < 1e-12,
      "chromatic sets read the travel curve (90° of 180° → 0.5)")

# ── seeder: translation + apply plan ─────────────────────────────────────────
from scripts.seed_sequencer_from_legacy import (apply_seed, band_edges,
                                                band_points, build_seed,
                                                gate_points, scale_points)

bands = band_edges([0.3, 0.65, 0.85, 0.95])
check(bands == [(0.0, 0.3), (0.3, 0.65), (0.65, 0.85), (0.85, 0.95), (0.95, 1.0)],
      "live chooser thresholds → five bands")
mid = band_points(0.3, 0.65)
check([(p.x, p.y) for p in mid] == [(0.2, 0.0), (0.3, 1.0), (0.65, 1.0), (0.75, 0.0)],
      "interior band → trapezoid with 0.1 skirts")
first, last = band_points(0.0, 0.3), band_points(0.95, 1.0)
check(first[0].x == 0.0 and first[0].y == 1.0 and last[-1].y == 1.0,
      "edge bands skip the skirt on the axis end")
check(all(curve_eval(gate_points(0.45, None), e) == (1.0 if e >= 0.45 else 0.0)
          for e in SWEEP),
      "gate_points(floor 0.45) ≡ legacy gate under curve_eval")
check(all(curve_eval(gate_points(None, 0.45), e) == (1.0 if e < 0.45 else 0.0)
          for e in SWEEP if e != 0.45),
      "gate_points(ceiling 0.45) ≡ legacy gate except at exactly the ceiling")
check([p.y for p in scale_points(mid, 2.0)] == [0.0, 2.0, 2.0, 0.0],
      "member weight 2.0 → same shape at 2× height")

legacy_events = [
    {"id": "grp", "name": "Mid Group", "event_type": "scene_group",
     "scene_group_members": [{"event_id": "sc1", "weight": 1.5},
                             {"event_id": "sc2", "weight": 100.0},
                             {"event_id": "sc3", "weight": 1.0}]},
    {"id": "sc1", "name": "Nebula", "event_type": "scene_update"},
    {"id": "sc2", "name": "Favorite", "event_type": "scene_update"},
    {"id": "sc3", "name": "Orphan", "event_type": "scene_update"},
    {"id": "chooser", "name": "Intensity Scene", "event_type": "composite",
     "root": {"type": "intensity_chooser", "source": "trigger_intensity", "lanes": [
         {"threshold": 0.0, "actions": [{"type": "event_ref", "event_id": "grp",
                                         "weight": 1.0}]},
         {"threshold": 0.65, "actions": []}]}},
    {"id": "dancer", "name": "Dancer", "event_type": "composite",
     "root": {"type": "random_group", "options": [
         {"id": "o1", "name": "low", "weight": 1.0, "energy_ceiling": 0.45,
          "actions": []},
         {"id": "o2", "name": "high", "weight": 1.0, "energy_floor": 0.45,
          "actions": []}]}},
]
V2_MAP = {"nebula": "v2-nebula", "favorite": "v2-favorite"}
plan = build_seed(legacy_events, V2_MAP)
kinds = [r[0] for r in plan.rows]
check(kinds.count("curve_profile") == 2 and len(plan.profiles) == 2,
      "one band profile per chooser lane")
nebula = plan.entries["v2-nebula"]
check(nebula.curve_ref is None and nebula.inline_points is not None
      and [p.y for p in nebula.inline_points][:2] == [1.5, 1.5],
      "weight 1.5 member → INLINE points at 1.5× height (the escape hatch)")
check(any(k == "FLAGGED" and "100" in d for k, n, d in plan.rows),
      "the 100.0 force-favorite outlier is flagged, not seeded")
check("v2-favorite" not in plan.entries,
      "flagged outlier writes no entry")
check(any(k == "SKIPPED" and n == "Orphan" for k, n, d in plan.rows)
      and len(plan.entries) == 1,
      "scene with no SceneV2 counterpart is SKIPPED, not mis-keyed")
check(kinds.count("gate_curve") == 2,
      "both Dancer energy gates printed (reference only — attach to nothing)")

# ── store + apply + agent-adjustment API + engine ────────────────────────────
with tempfile.TemporaryDirectory() as td:
    from services import sequencer_store
    sequencer_store.SEQUENCER_FILE = Path(td) / "sequencer.json"

    profile = CurveProfile(name="High-energy ramp",
                           points=pts((0, 0), (0.65, 0.2), (1, 1)))
    sequencer_store.save_curves({profile.id: profile})
    sequencer_store.save_config(SequencerConfig(
        entries={"s1": SelectorEntry(curve_ref=profile.id, dwell_weight=2.0)}))
    check(sequencer_store.load_curves()[profile.id].name == "High-energy ramp"
          and sequencer_store.load_config().entries["s1"].dwell_weight == 2.0,
          "store round-trip keeps curves and config side by side")
    check(not list(Path(td).glob("*.tmp")), "atomic write leaves no tmp files")

    # seeder --apply path: merge, idempotence, preservation
    sequencer_store.save_config(SequencerConfig(
        enabled=False,
        entries={"keepme": SelectorEntry(dwell_weight=3.0)},
        affinity=[AffinityEdge(from_id="x", to_id="y", mult=2.0)]))
    n_profiles, n_entries = apply_seed(plan)
    check(n_profiles == 2 and n_entries == 1, "apply writes the plan")
    applied = sequencer_store.load_config()
    check("v2-nebula" in applied.entries and "keepme" in applied.entries
          and len(applied.affinity) == 1 and applied.enabled is False,
          "apply merges: seeded entries added, unseeded entries / affinity / "
          "dark flag preserved")
    curve_ids_before = set(sequencer_store.load_curves())
    apply_seed(build_seed(legacy_events, V2_MAP))
    check(set(sequencer_store.load_curves()) == curve_ids_before,
          "re-apply is idempotent — profiles matched by name, no duplicates")

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers import sequencer_router

    profiles_dir = Path(td) / "profiles"
    profiles_dir.mkdir()
    (profiles_dir / "song.json").write_text(json.dumps(
        {"triggers": [{"intensity": 0.05}, {"intensity": 0.77}, {"intensity": 0.97}]}))
    sequencer_router.PROFILES_DIR = profiles_dir
    sequencer_router._census_cache = None

    app = FastAPI()
    app.include_router(sequencer_router.router)
    client = TestClient(app)

    sequencer_store.save_curves({profile.id: profile})
    sequencer_store.save_config(SequencerConfig(
        entries={"s1": SelectorEntry(curve_ref=profile.id, dwell_weight=2.0)}))

    check(client.get("/api/sequencer/curves").json()[profile.id]["name"] == "High-energy ramp",
          "GET curves")
    got = client.get("/api/sequencer/config").json()
    check(got["entries"]["s1"]["curve_ref"] == profile.id
          and got["change_mode"] == "transition" and got["enabled"] is False,
          "GET config — transition-only default, dark by default")

    bad_curve = {"bad": {"id": "bad", "name": "b",
                         "points": [{"x": 0.9, "y": 1}, {"x": 0.1, "y": 1}]}}
    check(client.put("/api/sequencer/curves", json=bad_curve).status_code == 422,
          "unsorted curve → 422 at the API boundary")
    mismatch = {"other-key": json.loads(profile.model_dump_json())}
    check(client.put("/api/sequencer/curves", json=mismatch).status_code == 422,
          "curve key ≠ profile id → 422")
    check(client.put("/api/sequencer/curves", json={}).status_code == 422,
          "deleting a still-referenced profile → 422")

    dangling = json.loads(SequencerConfig(
        entries={"s2": SelectorEntry(curve_ref="no-such-profile")}).model_dump_json())
    check(client.put("/api/sequencer/config", json=dangling).status_code == 422,
          "config referencing an unknown curve → 422")
    dangling_flare = json.loads(SequencerConfig(
        flare_entries={"f1": SelectorEntry(curve_ref="no-such-profile")}).model_dump_json())
    check(client.put("/api/sequencer/config", json=dangling_flare).status_code == 422,
          "flare entry referencing an unknown curve → 422")
    two_curves = {p.id: json.loads(p.model_dump_json())
                  for p in (profile, CurveProfile(name="Quiet-only", points=pts((0, 1), (0.5, 0))))}
    check(client.put("/api/sequencer/curves", json=two_curves).json()["profiles"] == 2,
          "PUT curves accepts a valid library")
    agent_config = json.loads(SequencerConfig(
        base_dwell_s=240.0,
        entries={"s1": SelectorEntry(curve_ref=profile.id, dwell_weight=3.0,
                                     genre_mult={"edm": 1.5})},
        flare_entries={"f1": SelectorEntry(curve_ref=profile.id)},
        affinity=[AffinityEdge(from_id="drop", to_id="quiet", mult=2.5)]).model_dump_json())
    put_res = client.put("/api/sequencer/config", json=agent_config).json()
    check(put_res["affinity_edges"] == 1 and put_res["flare_entries"] == 1,
          "PUT config — the agent-adjustment channel (scene + flare selectors)")
    check(client.get("/api/sequencer/config").json()["entries"]["s1"]["dwell_weight"] == 3.0,
          "agent adjustment persists")

    status = client.get("/api/sequencer/status").json()
    check(status["enabled"] is False and status["next_change_source"] == "transition"
          and status["active_scene_id"] is None and status["dwell"] is None,
          "GET status: dark engine reports enabled=false, transition clock, no scene")

    sim_cfg = SequencerConfig(entries={
        "s1": SelectorEntry(inline_points=pts((0, 1.0))),
        "s2": SelectorEntry(inline_points=pts((0, 3.0))),
        "s3": SelectorEntry(inline_points=pts((0, 0.0)))})
    sequencer_store.save_config(sim_cfg)
    sim = client.post("/api/sequencer/simulate",
                      json={"intensity": 0.5, "n": 4000, "seed": 1}).json()
    check("s3" not in sim["shares"] and abs(sim["shares"]["s2"] - 0.75) < 0.03
          and sim["rungs"] == {"full": 4000},
          "simulate: dry kernel rolls — veto holds, shares ∝ scores, nothing fired")
    sim_flare = client.post("/api/sequencer/simulate",
                            json={"intensity": 0.5, "n": 10, "kind": "flare"}).json()
    check(sim_flare["shares"] == {"<nothing>": 1.0},
          "simulate kind=flare with no flare entries → terminal NOTHING")

    # ── engine: transition-only clock, dwell in songs, deferrals, dark ──────
    from models.state import SpotifyTrackInfo, state
    from services.scene_sequencer import SceneSequencer

    def track(uri):
        return SpotifyTrackInfo(spotify_uri=uri, title=uri, artist="t",
                                duration_ms=200_000, progress_ms=0,
                                is_playing=True, fetched_at=0.0)

    def mk_engine(seed=5, intensity=0.5):
        fires, casts = [], []

        async def fake_fire(scene_id):
            fires.append(scene_id)

        async def fake_broadcast(payload):
            casts.append(payload)

        eng = SceneSequencer(
            rng=Random(seed), fire=fake_fire,
            intensity=lambda: intensity, genre_bucket=lambda: None,
            list_scene_ids=lambda: {"s1", "s2", "s3"},
            scene_name=lambda sid: sid.upper(), broadcast=fake_broadcast)
        return eng, fires, casts

    saved_state = (state.paused, state.dinner_party_mode,
                   state.ambient_mode_enabled, state.last_scene_update_id)
    state.paused = False
    state.dinner_party_mode = False
    state.ambient_mode_enabled = False
    state.last_scene_update_id = ""

    async def engine_spec():
        # DARK: enabled False → transitions change nothing, nothing fires.
        sequencer_store.save_config(SequencerConfig(
            entries={"s1": SelectorEntry()}))
        eng, fires, _ = mk_engine()
        for uri in ("spotify:track:a", "spotify:track:b", "spotify:track:c"):
            await eng.on_track_state(track(uri))
        check(fires == [] and eng.status()["last_moment"] is None,
              "DARK: enabled=False → moments are inert, nothing fires")

        # Transition-only clock: same-URI polls and stop/None are not moments.
        sequencer_store.save_config(SequencerConfig(
            enabled=True,
            entries={"s1": SelectorEntry(), "s2": SelectorEntry()}))
        eng, fires, casts = mk_engine()
        await eng.on_track_state(track("spotify:track:a"))   # arms only
        for _ in range(5):
            await eng.on_track_state(track("spotify:track:a"))
        await eng.on_track_state(None)
        check(fires == [] and eng.status()["last_moment"] is None,
              "transition clock: polls without a URI change (and stop) are not "
              "moments; the first URI only arms")
        await eng.on_track_state(track("spotify:track:b"))
        check(len(fires) == 1 and fires[0] in ("s1", "s2")
              and eng.status()["last_moment"]["result"] == "picked",
              "a song transition is a change moment — first pick fires")
        first = fires[0]
        await eng.on_track_state(track("spotify:track:c"))
        check(fires == [first, "s2" if first == "s1" else "s1"],
              "dwell weight 1 → held exactly one song; current excluded → the "
              "other scene fires")
        check(casts and casts[0]["type"] == "sequencer_pick"
              and "factors" in casts[0] and casts[0]["dwell_target_songs"] == 1,
              "sequencer_pick broadcast carries the factor breakdown")

        # Dwell in songs: weight 2 holds two transitions (renewal, no re-fire).
        sequencer_store.save_config(SequencerConfig(
            enabled=True, entries={"s2": SelectorEntry(dwell_weight=2.0)}))
        eng, fires, _ = mk_engine()
        results = []
        for i, uri in enumerate("abcdefg"):
            await eng.on_track_state(track(f"spotify:track:{uri}"))
            lm = eng.status()["last_moment"]
            results.append(lm["result"] if lm else None)
        check(fires == ["s2"],
              "sole candidate fired once, then renewed — never re-fired "
              "through the write plane")
        check(results == [None, "picked", "held", "renewed", "held", "renewed", "held"],
              f"dwell weight 2 holds 2 songs per term: {results}")
        st = eng.status()
        check(st["active_scene_id"] == "s2" and st["active_scene_name"] == "S2"
              and st["dwell"]["target_songs"] == 2
              and st["dwell"]["weight"] == 2.0,
              "status: active scene + dwell progress in songs")

        # Deferrals skip the moment entirely (no served count, no roll).
        sequencer_store.save_config(SequencerConfig(
            enabled=True, entries={"s1": SelectorEntry(), "s2": SelectorEntry()}))
        eng, fires, _ = mk_engine()
        await eng.on_track_state(track("spotify:track:a"))
        await eng.on_track_state(track("spotify:track:b"))
        served_before = eng.status()["dwell"]["served_songs"]
        state.paused = True
        await eng.on_track_state(track("spotify:track:c"))
        check(eng.status()["last_moment"]["result"] == "deferred:paused"
              and eng.status()["dwell"]["served_songs"] == served_before
              and len(fires) == 1,
              "paused → moment deferred, dwell count untouched")
        state.paused = False
        state.ambient_mode_enabled = True
        await eng.on_track_state(track("spotify:track:d"))
        check(eng.status()["last_moment"]["result"] == "deferred:ambient",
              "ambient mode defers the sequencer")
        state.ambient_mode_enabled = False
        from config import settings as _settings
        object.__setattr__(_settings, "force_scene_enabled", True)
        await eng.on_track_state(track("spotify:track:e"))
        check(eng.status()["last_moment"]["result"] == "deferred:force_scene",
              "Force Scene pins the room — sequencer defers")
        object.__setattr__(_settings, "force_scene_enabled", False)

        # A trigger-fired scene resets the dwell count (pure observation).
        eng, fires, _ = mk_engine()
        await eng.on_track_state(track("spotify:track:a"))
        await eng.on_track_state(track("spotify:track:b"))   # picks, baselines
        state.last_scene_update_id = "legacy-ev-9"
        await eng.on_track_state(track("spotify:track:c"))
        st = eng.status()
        check(st["active_scene_id"] == "legacy-ev-9"
              and st["last_moment"]["result"] == "held"
              and st["dwell"]["served_songs"] == 0 and len(fires) == 1,
              "trigger-fired scene adopted with a fresh dwell count — this "
              "moment holds instead of rolling")
        await eng.on_track_state(track("spotify:track:d"))
        check(len(fires) == 2 and fires[1] in ("s1", "s2"),
              "after its served song the adopted scene rolls normally "
              "(legacy id simply isn't a candidate)")

        # All curves zero at the moment's intensity → ladder ends at STAY.
        sequencer_store.save_config(SequencerConfig(
            enabled=True,
            entries={"s1": SelectorEntry(inline_points=pts((0, 0.0)))}))
        eng, fires, _ = mk_engine(intensity=0.9)
        await eng.on_track_state(track("spotify:track:a"))
        await eng.on_track_state(track("spotify:track:b"))
        check(fires == [] and eng.status()["last_moment"]["result"] == "stay"
              and eng.status()["last_pick"]["rung"] == "stay",
              "nothing eligible → STAY, and the stay is observable in last_pick")

        # Stored non-transition mode still ticks transitions only (logged).
        sequencer_store.save_config(SequencerConfig(
            enabled=True, change_mode="both", entries={"s1": SelectorEntry()}))
        eng, fires, _ = mk_engine()
        await eng.on_track_state(track("spotify:track:a"))
        await eng.on_track_state(track("spotify:track:b"))
        check(fires == ["s1"],
              "stored change_mode=both: no timer exists — transitions still tick")

    asyncio.run(engine_spec())
    (state.paused, state.dinner_party_mode,
     state.ambient_mode_enabled, state.last_scene_update_id) = saved_state

    hist = client.get("/api/sequencer/intensity-histogram").json()
    check(hist["total"] == 3 and len(hist["counts"]) == hist["bins"] == 20
          and hist["counts"][1] == 1 and hist["counts"][15] == 1 and hist["counts"][19] == 1,
          "intensity histogram bins the profile census")

print("\nALL CHECKS PASSED")
