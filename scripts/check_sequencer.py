"""Executable spec for the SPECTRA sequencer unambiguous core (models, curve
evaluation, rainbow exemption, store, agent-adjustment API, seeder helpers).
Run from repo root: .venv/bin/python scripts/check_sequencer.py
Isolated: temp files for the store and profile census; no live storage, no
LedFX I/O. Engine semantics (composition, sampling, dwell gate) are OPEN
decisions and deliberately unspecified here."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pydantic import ValidationError

from models.color_set import ColorSetCard, ColorSetEntry
from models.sequencer import (AffinityEdge, CurvePoint, CurveProfile,
                              SelectorEntry, SequencerConfig)
from services import color_wheel
from services.selection_kernel import (curve_eval, wheel_travel_deg,
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

# ── seeder pure helpers ──────────────────────────────────────────────────────
from scripts.seed_sequencer_from_legacy import (band_edges, band_points,
                                                build_diff, gate_points,
                                                scale_points)

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
                             {"event_id": "sc2", "weight": 100.0}]},
    {"id": "sc1", "name": "Nebula", "event_type": "scene_update"},
    {"id": "sc2", "name": "Favorite", "event_type": "scene_update"},
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
rows = build_diff(legacy_events)
kinds = [r[0] for r in rows]
check(kinds.count("curve_profile") == 2, "one band profile per chooser lane")
check(any(k == "entry" and "Nebula" in n and "1.5×" in d for k, n, d in rows),
      "scene-group member weight becomes height scaling on the entry")
check(any(k == "FLAGGED" and "100" in d for k, n, d in rows),
      "the 100.0 force-favorite outlier is flagged, not seeded")
check(kinds.count("gate_curve") == 2, "both Dancer energy gates translated")

refusal = subprocess.run(
    [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "seed_sequencer_from_legacy.py"), "--apply"],
    capture_output=True, text=True)
check(refusal.returncode == 2 and "REFUSED" in refusal.stdout,
      "seeder --apply refuses while the storage schema awaits decisions")

# ── store + agent-adjustment API ─────────────────────────────────────────────
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

    check(client.get("/api/sequencer/curves").json()[profile.id]["name"] == "High-energy ramp",
          "GET curves")
    got = client.get("/api/sequencer/config").json()
    check(got["entries"]["s1"]["curve_ref"] == profile.id and got["change_mode"] == "both",
          "GET config")

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
    two_curves = {p.id: json.loads(p.model_dump_json())
                  for p in (profile, CurveProfile(name="Quiet-only", points=pts((0, 1), (0.5, 0))))}
    check(client.put("/api/sequencer/curves", json=two_curves).json()["profiles"] == 2,
          "PUT curves accepts a valid library")
    agent_config = json.loads(SequencerConfig(
        base_dwell_s=240.0,
        entries={"s1": SelectorEntry(curve_ref=profile.id, dwell_weight=3.0,
                                     genre_mult={"edm": 1.5})},
        affinity=[AffinityEdge(from_id="drop", to_id="quiet", mult=2.5)]).model_dump_json())
    check(client.put("/api/sequencer/config", json=agent_config).json()["affinity_edges"] == 1,
          "PUT config — the agent-adjustment channel")
    check(client.get("/api/sequencer/config").json()["entries"]["s1"]["dwell_weight"] == 3.0,
          "agent adjustment persists")

    hist = client.get("/api/sequencer/intensity-histogram").json()
    check(hist["total"] == 3 and len(hist["counts"]) == hist["bins"] == 20
          and hist["counts"][1] == 1 and hist["counts"][15] == 1 and hist["counts"][19] == 1,
          "intensity histogram bins the profile census")

print("\nALL CHECKS PASSED")
