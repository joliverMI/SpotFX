#!/usr/bin/env python3
"""Drop sequences fire (drop-detection plan, phase 5) — an OFFLINE SHOW RUN
of the Admiral's four test songs through the shipped trigger clock.

READ-ONLY against the live checkout's storage (default /home/javi/SpotFX,
override with --live-root): every file it reads is COPIED into a throwaway
temp directory first and every store it touches is repointed there
(scripts/check_drop_detector.py's own isolation, reused). Nothing reaches
the room: the trigger clock's fire paths are recorders, so this is a dry
run of WHAT WOULD FIRE, tick by tick at the production 200 ms cadence.

For each song (Contra, Dopamine, Pop Off, 100 Millones) it detects the
drops, then sweeps the whole song under every scene-change mode, twice:

  as stored     his own triggers present (the real song), plus the song's
                stored generated scene cues;
  analysed show his triggers taken away, so the song plays the analysed
                show (what an untouched song of his library does).

and reports, per run, the sequences and members that fired and the stored
scene cues the protected windows held back. It FAILS (non-zero) when:

  - anything fires under "Transitions only";
  - a suggested or dismissed detection fires;
  - a sequence member fires within two beats of one of his own triggers
    of the same class (a double fire);
  - an analysed scene change fires inside a protected window, or an
    analysed flare fires in a lull or on a drop;
  - the planner (midsong_generator.plan_moments, real analysis) keeps a
    scene change inside a window or a moment at a drop.

Prints a markdown table (the PR body's).

Run from repo root: .venv/bin/python scripts/check_drop_firing.py
                     [--live-root /home/javi/SpotFX]
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MODES = ("transitions", "analysed", "triggers_only", "full")


class _Rec:
    def __init__(self):
        self.position = 0
        self.seq: list[tuple[int, str]] = []
        self.scenes: list[int] = []
        self.flares: list[int] = []
        self.his: list[tuple[int, str]] = []

    async def fire_sequence(self, cls, intensity, gap):
        self.seq.append((self.position, cls))

    async def fire_response(self, cls, intensity, gap=None):
        self.his.append((self.position, cls))

    async def fire_scene(self, scene_id, color_set_id, intensity):
        self.scenes.append(self.position)

    async def fire_flare(self, intensity):
        self.flares.append(self.position)


async def _noop(_uri):
    return None


def _sweep(uri: str, triggers: list, mode: str, duration: int) -> _Rec:
    from spectra.services import analysed_flares
    from spectra.services.trigger_engine import TriggerEngine
    rec = _Rec()
    eng = TriggerEngine(
        list_triggers=lambda u: list(triggers), scene_change_mode=lambda: mode,
        fire_sequence=rec.fire_sequence, fire_response=rec.fire_response,
        fire_scene=rec.fire_scene, fire_analysed_flare=rec.fire_flare,
        analysed_plan=lambda u, stored: analysed_flares.plan_for_song(u, stored),
        render_intensity=lambda x: x, lead_ms=lambda t: 0,
        response_offset_ms=lambda a: 0, sequencer_enabled=lambda: False,
        select_scene=lambda i: "S", transition_intensity=lambda: 0.5,
        auto_generate=_noop, auto_refresh=_noop)

    async def run():
        await eng.on_track_state(uri)
        await eng.plan_analysed_flares(uri)
        for pos in range(0, duration + 200, 200):
            rec.position = pos
            await eng.tick(pos)
    asyncio.run(run())
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live-root", default="/home/javi/SpotFX")
    args = ap.parse_args()
    import check_drop_detector as cdd

    tmp = Path(tempfile.mkdtemp(prefix="check_drop_firing_"))
    cdd._isolate(Path(args.live_root), tmp)
    from spectra import config as scfg
    scfg.INTENSITY_SCALE_MARKS_FILE = tmp / "spectra" / "marks.json"
    from spectra.services import drop_firing, drop_sequences, midsong_generator as mg
    from spectra.services import trigger_store

    problems: list[str] = []
    print("# Drop sequences fire — offline show run (phase 5)\n")
    print("| Song | Triggers | Mode | Sequences fired | Members fired | Stored scene cues held |")
    print("|---|---|---|---:|---:|---:|")
    notes: list[str] = []
    for name, uri, _is_edm in cdd.SONGS:
        drop_sequences.ensure_detected(uri)
        stored = trigger_store.list_for_song(uri)
        det = drop_sequences.stored(uri)["detected"]
        beat = float(det.get("beat_ms") or 500.0)
        duration = int(det.get("duration_ms") or det.get("captured_to_ms"))
        generated = [t for t in stored if t.source == "generated"]
        his = [t for t in stored if t.source == "authored"]
        his_phase = [(t.action.event_class, t.timestamp_ms + t.trigger_offset_ms)
                     for t in his if t.enabled and t.action.kind == "fire_response"
                     and t.action.event_class in ("charge", "lull", "drop")]
        for label, trigs in (("as stored", stored), ("analysed show", generated)):
            view = drop_sequences.view(uri, triggers=trigs)
            windows = drop_firing.windows_from_view(view)
            states = {s["drop_ms"]: s["state"] for s in view["sequences"]}
            for mode in MODES:
                rec = _sweep(uri, trigs, mode, duration)
                drops = [p for p, c in rec.seq if c == "drop"]
                gen_scene = [t.timestamp_ms + t.trigger_offset_ms for t in trigs
                             if t.source == "generated" and t.action.kind == "fire_scene"]
                held = [t for t in gen_scene
                        if drop_firing.holding_window(windows, t) is not None]
                print(f"| {name} | {label} | {mode} | {len(drops)} | {len(rec.seq)} "
                      f"| {len(held) if mode in ('analysed', 'full') else 0} |")
                if mode == "transitions" and rec.seq:
                    problems.append(f"{name} {label}: fired under transitions only")
                for d in drops:
                    st = next((s for ms, s in states.items() if abs(ms - d) <= 200), None)
                    if st not in drop_firing.PROTECTED_STATES:
                        problems.append(f"{name} {label} {mode}: a {st} sequence fired at {d}")
                for pos, cls in rec.seq:
                    if label == "as stored" and mode in ("full", "triggers_only"):
                        for hc, hms in his_phase:
                            if hc == cls and abs(hms - pos) <= 2 * beat + 200:
                                problems.append(f"{name} {mode}: {cls} at {pos} doubles his at {hms}")
                for p in rec.scenes:
                    w = drop_firing.holding_window(windows, p)
                    if w is not None and any(abs(p - g) <= 200 for g in gen_scene):
                        problems.append(f"{name} {label} {mode}: scene change at {p} inside {w.key}")
                for p in rec.flares:
                    w = drop_firing.silencing_window(windows, p)
                    if w is not None:
                        problems.append(f"{name} {label} {mode}: analysed flare at {p} in {w.key}")
        # the planner, on the real analysis, with the song's own windows
        windows = drop_firing.protected_windows(uri, generated)
        plan = mg.plan_moments(uri, protected=windows)
        for m in plan.kept:
            w = drop_firing.holding_window(windows, m.timestamp_ms)
            if w is not None:
                problems.append(f"{name}: the planner kept a scene change at {m.timestamp_ms} in {w.key}")
        for m in plan.kept + plan.unselected:
            if any(w.at_drop(m.timestamp_ms) for w in windows):
                problems.append(f"{name}: the planner acts at a drop moment {m.timestamp_ms}")
        free = mg.plan_moments(uri, protected=[])
        notes.append(f"- {name}: {len(windows)} protected windows on the analysed show; "
                     f"the planner's scene changes {len(free.kept)} → {len(plan.kept)} "
                     f"(none inside a window, none at a drop), actions "
                     f"{len(free.kept) + len(free.unselected)} → "
                     f"{len(plan.kept) + len(plan.unselected)}.")

    print("\nThe planner (real analysis, stored claims and settings of the copy):\n")
    print("\n".join(notes))
    print()
    if problems:
        print("FAILED:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("OK: what fires, the stand-downs and the protected windows hold on all four songs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
