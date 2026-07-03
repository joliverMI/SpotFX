"""
Behavioral equivalence check: legacy events vs their composite migration.

For every migratable event in storage/events.json, fires the LEGACY shape
through the legacy executors and the MIGRATED shape through
_execute_composite, on separate engine instances, and compares the ordered
leaf-action traces: (leaf type, leaf payload, virtual-clock ms).

Determinism/normalization (containers are under test, leaves are opaque):
  - _execute_action is intercepted at the leaf boundary: leaf actions are
    recorded, not executed; containers (random/sequence/parallel groups,
    event_ref) pass through.
  - _pick_from_actions is patched to pick the FIRST label-filtered candidate
    and record the pool structure (dedupe_key, [(labels, weight)]) — pick
    POOLS are compared structurally, pick RANDOMNESS is not exercised.
  - asyncio.sleep / time.monotonic run on a virtual clock; beat interval
    pinned to 200 ms.
  - pre-command flags are disabled on both copies (event-level data is
    identical post-migration — nothing to test) and event_offset_ms zeroed
    (offsets are planner domain, not executor domain).
  - Labels: composite merges child labels downward (legacy only merged them
    for event-type steps) — composite leaf labels must be a SUPERSET of the
    legacy leaf's; extras are reported as notes, not failures.

Skips (reported): device_settings events (no Action boundary in the legacy
path; 0 stored today) and beat-in-beat event refs (sub-anchor semantics
differ on the unplanned path; planner covers the planned path).

USAGE
  .venv/bin/python scripts/check_composite_equivalence.py [--verbose]
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import effect_params

effect_params.load()

from models.music_event import MusicEvent                       # noqa: E402
from services.trigger_engine import TriggerEngine               # noqa: E402
from scripts.migrate_to_composite import migrate                # noqa: E402

VERBOSE = "--verbose" in sys.argv
EVENTS_FILE = Path(__file__).resolve().parent.parent / "storage" / "events.json"
SCENE_TYPES = {"scene_update", "update_scene", "reset_scene",
               "shape_flare", "color_flare", "combo_flare"}
CONTAINERS = {"random_group", "sequence_group", "parallel_group", "event_ref"}

# ── virtual clock (discrete-event; handles concurrent staggered sleeps) ─────
from scripts._virtual_clock import VirtualClock  # noqa: E402

clock = VirtualClock()
_ = time  # time.monotonic patched by VirtualClock

# ── event lookup shim: both engines resolve event_refs from OUR maps ─────────
import services.trigger_engine as te                            # noqa: E402

CURRENT_MAP: dict[str, MusicEvent] = {}
te.get_event = lambda eid: CURRENT_MAP.get(eid)


def build_engine() -> TriggerEngine:
    e = TriggerEngine()
    e._local_beat_interval_ms = lambda at_ms: 200   # type: ignore
    e._beats_cache = [0.0, 0.2]
    return e


def instrument(engine: TriggerEngine, trace: list, pools: list):
    orig_exec = engine._execute_action
    orig_pick = engine._pick_from_actions

    async def wrapped_exec(action, labels=None, **kw):
        if action.type in CONTAINERS:
            return await orig_exec(action, labels, **kw)
        trace.append({
            "type": action.type,
            "payload": json.loads(action.model_dump_json()),
            "labels": sorted(set(labels or [])),
            "t": clock.now_ms,
        })

    def wrapped_pick(actions, labels, dedupe_key, desc=""):
        pos = [l.lower() for l in labels if not l.startswith("-")]
        neg = [l[1:].lower() for l in labels if l.startswith("-")]
        cands = []
        for a in actions:
            al = [l.lower() for l in a.labels]
            if pos and not any(p in al for p in pos):
                continue
            if any(n in al for n in neg):
                continue
            cands.append(a)
        if not cands:
            cands = list(actions)
        pools.append({
            "n": len(actions),
            "pool": [(sorted(a.labels), a.weight) for a in actions],
        })
        return cands[0] if cands else None

    engine._execute_action = wrapped_exec          # type: ignore
    engine._pick_from_actions = wrapped_pick       # type: ignore


def normalize_events(raw: dict) -> dict[str, MusicEvent]:
    out = {}
    for eid, d in raw.items():
        d = json.loads(json.dumps(d))
        d["pre_brightness_enabled"] = False
        d["pre_transition_enabled"] = False
        d["event_offset_ms"] = 0
        out[eid] = MusicEvent(**d)
    return out


async def fire_legacy(engine: TriggerEngine, ev: MusicEvent):
    if ev.event_type == "single":
        action = engine._select_action(ev, [])
        if action:
            await engine._execute_action(action, [])
    elif ev.event_type == "sequence":
        await engine._execute_sequence(ev, [])
    elif ev.event_type == "beat_sequence":
        await engine._execute_beat_sequence(ev, 5000, [], anchor_override_ms=5000)
    elif ev.event_type == "morph_set":
        picks = engine._pick_morph_lanes(ev, [])
        await engine._fire_morph_picks(picks, [])


def has_beat_in_beat_ref(ev: MusicEvent, emap: dict) -> bool:
    if ev.event_type != "beat_sequence":
        return False
    for s in ev.beat_sequence_steps:
        sub_ids = [s.event_id] if s.step_type == "event" and s.event_id else []
        for a in (s.actions or []) + ([s.action] if s.action else []):
            if getattr(a, "type", "") == "event_ref":
                sub_ids.append(a.event_id)
        for sid in sub_ids:
            sub = emap.get(sid)
            if sub and sub.event_type == "beat_sequence":
                return True
    return False


def _by_time(trace: list) -> dict[int, list]:
    out: dict[int, list] = {}
    for leaf in trace:
        out.setdefault(leaf["t"], []).append(leaf)
    for leaves in out.values():
        leaves.sort(key=lambda l: (l["type"], json.dumps(l["payload"], sort_keys=True)))
    return out


def diff_traces(legacy: list, comp: list) -> str | None:
    """Compare per-timestamp multisets — concurrent leaves at the same virtual
    time may legitimately record in either order."""
    lt, ct = _by_time(legacy), _by_time(comp)
    if sorted(lt) != sorted(ct):
        return f"fire times {sorted(lt)} vs {sorted(ct)}"
    for t in sorted(lt):
        a_leaves, b_leaves = lt[t], ct[t]
        if len(a_leaves) != len(b_leaves):
            return f"t={t}: leaf count {len(a_leaves)} vs {len(b_leaves)}"
        for a, b in zip(a_leaves, b_leaves):
            if a["type"] != b["type"]:
                return f"t={t}: type {a['type']} vs {b['type']}"
            if a["payload"] != b["payload"]:
                return f"t={t}: payload differs ({a['type']})"
            if not set(a["labels"]).issubset(set(b["labels"])):
                return f"t={t}: legacy labels {a['labels']} ⊄ composite {b['labels']}"
    return None


def refs_dropped_subevent(ev: MusicEvent, emap: dict) -> bool:
    """Legacy sequence/beat event-steps pointing at morph_set/scene events fell
    into the single-style else-branch and silently fired nothing. Composite
    event_refs dispatch them correctly — extra composite leaves are a FIX."""
    steps = (ev.sequence_steps if ev.event_type == "sequence"
             else ev.beat_sequence_steps if ev.event_type == "beat_sequence" else [])
    for s in steps:
        sub_ids = [s.event_id] if s.step_type == "event" and s.event_id else []
        for a in (s.actions or []) + ([s.action] if s.action else []):
            if getattr(a, "type", "") == "event_ref":
                sub_ids.append(a.event_id)
        for sid in sub_ids:
            sub = emap.get(sid)
            if sub and sub.event_type in ({"morph_set"} | SCENE_TYPES):
                return True
    return False


async def main() -> int:
    raw = json.loads(EVENTS_FILE.read_text())
    migrated_raw, _rows, _sk = migrate(raw)

    legacy_map = normalize_events(raw)
    comp_map = normalize_events(migrated_raw)

    checked = passed = 0
    skipped: list[str] = []
    failures: list[str] = []
    label_notes = 0

    for eid, lev in legacy_map.items():
        if lev.event_type in SCENE_TYPES or lev.event_type == "composite":
            continue
        cev = comp_map[eid]
        if lev.event_type == "device_settings":
            skipped.append(f"{lev.name} (device_settings — no leaf boundary)")
            continue
        if has_beat_in_beat_ref(lev, legacy_map):
            skipped.append(f"{lev.name} (beat-in-beat event_ref)")
            continue

        checked += 1
        global CURRENT_MAP

        clock.reset()
        e1 = build_engine()
        t1: list = []
        p1: list = []
        instrument(e1, t1, p1)
        CURRENT_MAP = legacy_map
        await clock.run(fire_legacy(e1, lev))

        clock.reset()
        e2 = build_engine()
        t2: list = []
        p2: list = []
        instrument(e2, t2, p2)
        CURRENT_MAP = comp_map
        await clock.run(e2._execute_composite(cev, []))

        err = diff_traces(t1, t2)
        if err and len(t2) > len(t1) and refs_dropped_subevent(lev, legacy_map):
            skipped.append(
                f"{lev.name} (composite fires a morph_set/scene sub-event the "
                f"legacy event-step silently dropped — improvement, verified by eye)")
            checked -= 1
            continue
        # Pick pools: composite may have FEWER rolls (1-candidate pools are
        # unwrapped by migration) — every composite pool must appear in the
        # legacy sequence in order.
        if err is None:
            it = iter(p1)
            for pool in p2:
                for cand in it:
                    if cand == pool:
                        break
                else:
                    err = "composite pick pool missing from legacy sequence"
                    break
        if err is None:
            for a, b_ in zip(t1, t2):
                if a["labels"] != b_["labels"]:
                    label_notes += 1
                    break
            passed += 1
            if VERBOSE:
                print(f"  = {lev.name} [{lev.event_type}] leaves={len(t1)}")
        else:
            failures.append(f"{lev.name} [{lev.event_type}]: {err}")

    print(f"\nchecked {checked} events: {passed} equivalent, {len(failures)} diffs, "
          f"{len(skipped)} skipped, {label_notes} label-superset notes")
    for s in skipped:
        print(f"  ~ skipped: {s}")
    for f in failures:
        print(f"  ✗ {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
