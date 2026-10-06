#!/usr/bin/env python3
"""Which of his charge and lull builds change under the PHASE PARTNER rule.

Drop-detection plan phase 1 (spectra/services/phase_partner.py is the
binding statement): a charge builds to its own lull or drop and a lull to its
own drop, whatever flare, scene change, colour change or update sits between.
This lists, per song, every charge and lull whose build target moves, with
its old and new build length, against his REAL trigger store.

THE OLD ANSWER IS THE OLD CODE, not a re-derivation of it: the pre-rule
trigger engine is loaded out of git at BASELINE_REF and its own
_next_trigger_gap_ms is asked, beside the current engine's
_phase_partner_gap_ms, over the identical trigger list and mode. Both are
real TriggerEngine instances with only list_triggers and scene_change_mode
injected, so the per-song effective mode and the enabled/allowed gate are
each engine's own.

Only triggers that would actually FIRE under the mode are listed — a charge
the mode mutes changes nothing in the room. Two modes are reported by
default: "triggers_only" (his "My triggers only") and "full" ("Everything",
where generated scene cues fire too and can sit inside his sequences).

Read-only: his storage is read in place and never written; nothing reaches
the live app, the room or any network. Exit status is non-zero if any change
is not a build moving out to its own partner, or the baseline cannot load.

Run:
  .venv/bin/python scripts/check_phase_partner_library.py
  .venv/bin/python scripts/check_phase_partner_library.py --markdown   # PR-ready
  .venv/bin/python scripts/check_phase_partner_library.py --storage /path/to/storage --mode full
"""
from __future__ import annotations

import argparse
import glob
import importlib.util
import json
import os
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from spectra.models.trigger import SpectraTrigger  # noqa: E402
from spectra.services import phase_partner  # noqa: E402
from spectra.services.scene_response import _phase_ramp_ms  # noqa: E402
from spectra.services.trigger_engine import TriggerEngine  # noqa: E402

# The last commit before the rule: master when phase 1 was built.
BASELINE_REF = "fedd12ae40a72f97cd02d13fba82b9e8df45b804"
DEFAULT_STORAGE = Path(os.path.expanduser("~/SpotFX/storage"))
DEFAULT_MODES = ("triggers_only", "full")
MODE_LABEL = {"triggers_only": "My triggers only", "full": "Everything",
              "analysed": "Transitions + analysed", "transitions": "Transitions only"}


def load_baseline_engine(ref: str):
    """The pre-rule trigger_engine module, exactly as it shipped at `ref`."""
    try:
        src = subprocess.run(
            ["git", "-C", str(REPO), "show", f"{ref}:spectra/services/trigger_engine.py"],
            check=True, capture_output=True, text=True).stdout
    except subprocess.CalledProcessError as exc:
        sys.exit(f"cannot load the pre-rule engine at {ref}: {exc.stderr.strip()}")
    if "_next_trigger_gap_ms" not in src:
        sys.exit(f"{ref} is not a pre-rule engine (no _next_trigger_gap_ms)")
    name = "_baseline_trigger_engine"
    spec = importlib.util.spec_from_loader(name, loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__file__ = f"<git {ref[:12]}>/spectra/services/trigger_engine.py"
    sys.modules[name] = mod
    exec(compile(src, mod.__file__, "exec"), mod.__dict__)
    return mod


def load_titles(storage: Path) -> dict[str, str]:
    titles: dict[str, str] = {}
    for f in glob.glob(str(storage / "audio_shapes" / "*.json")):
        if f.endswith(".librosa.json"):
            continue
        try:
            with open(f) as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        uri = d.get("spotify_uri")
        if uri and d.get("title"):
            titles[uri] = f"{d['title']} — {d.get('artist') or '?'}"
    return titles


def load_store(storage: Path) -> tuple[dict[str, list[SpectraTrigger]], int]:
    with open(storage / "spectra" / "triggers.json") as fh:
        raw = json.load(fh)
    songs: dict[str, list[SpectraTrigger]] = {}
    skipped = 0
    for uri, rows in raw.items():
        out = []
        for row in rows:
            try:
                out.append(SpectraTrigger.model_validate(row))
            except Exception:
                skipped += 1
        songs[uri] = out
    return songs, skipped


def stored_mode(storage: Path) -> Optional[str]:
    try:
        with open(storage / "spectra" / "room_controls.json") as fh:
            return json.load(fh).get("scene_change_mode")
    except (OSError, ValueError):
        return None


def describe(trig: Optional[SpectraTrigger]) -> str:
    if trig is None:
        return "nothing"
    a = trig.action
    if a.kind == "fire_response":
        what = a.event_class
    else:
        what = {"fire_scene": "scene change", "select_color_set": "colour change",
                "fire_scene_update": "update"}.get(a.kind, a.kind)
    return what if trig.source == "authored" else f"generated {what}"


def mmss(ms: int) -> str:
    return f"{ms // 60000}:{(ms % 60000) / 1000:06.3f}"


@dataclass
class Change:
    uri: str
    cls: str
    at_ms: int
    old_gap: Optional[int]
    new_gap: Optional[int]
    old_target: str
    new_target: str
    between: list[str]

    @property
    def old_build(self) -> int:
        return _phase_ramp_ms(self.cls, self.old_gap)

    @property
    def new_build(self) -> int:
        return _phase_ramp_ms(self.cls, self.new_gap)


def analyse(songs: dict[str, list[SpectraTrigger]], mode: str, baseline_mod) -> dict:
    changes: list[Change] = []
    fired = Counter()
    unchanged_by_reason = Counter()
    problems: list[str] = []
    for uri, triggers in songs.items():
        new = TriggerEngine(list_triggers=lambda _u, t=triggers: t,
                            scene_change_mode=lambda m=mode: m)
        old = baseline_mod.TriggerEngine(list_triggers=lambda _u, t=triggers: t,
                                         scene_change_mode=lambda m=mode: m)
        new._uri = old._uri = uri
        eff = new._effective_mode_for_song(mode, triggers)
        live = [t for t in triggers if t.enabled and new._trigger_allowed(t, eff)]
        by_ms: dict[int, list[SpectraTrigger]] = {}
        for t in live:
            by_ms.setdefault(t.timestamp_ms, []).append(t)
        for trig in live:
            a = trig.action
            if a.kind != "fire_response" or a.event_class not in phase_partner.BUILD_CLASSES:
                continue
            fired[a.event_class] += 1
            old_gap = old._next_trigger_gap_ms(trig)
            new_gap = new._phase_partner_gap_ms(trig)
            later = [(t.timestamp_ms, _cls(t)) for t in live if t.id != trig.id]
            target = phase_partner.build_target(a.event_class, trig.timestamp_ms, later)
            if old_gap == new_gap:
                unchanged_by_reason[(a.event_class, target.reason)] += 1
                continue

            def at(gap: Optional[int]) -> Optional[SpectraTrigger]:
                if gap is None:
                    return None
                here = [t for t in by_ms.get(trig.timestamp_ms + gap, []) if t.id != trig.id]
                phase = [t for t in here if _cls(t) is not None]
                return (phase or here or [None])[0]

            between = [describe(t) for t in sorted(live, key=lambda t: t.timestamp_ms)
                       if t.id != trig.id
                       and trig.timestamp_ms < t.timestamp_ms
                       < trig.timestamp_ms + (new_gap or 0)]
            ch = Change(uri, a.event_class, trig.timestamp_ms, old_gap, new_gap,
                        describe(at(old_gap)), describe(at(new_gap)), between)
            changes.append(ch)
            if target.reason != phase_partner.TARGET_PARTNER:
                problems.append(f"{uri} {a.event_class}@{trig.timestamp_ms}: changed "
                                f"without a partner ({target.reason})")
            elif not (old_gap is not None and new_gap is not None and new_gap > old_gap):
                problems.append(f"{uri} {a.event_class}@{trig.timestamp_ms}: build did "
                                f"not lengthen ({old_gap} -> {new_gap})")
    return {"changes": changes, "fired": fired, "unchanged": unchanged_by_reason,
            "problems": problems}


def _cls(t: SpectraTrigger) -> Optional[str]:
    a = t.action
    if a.kind == "fire_response" and a.event_class in phase_partner.PHASE_ORDER:
        return a.event_class
    return None


def median(xs: list[int]) -> int:
    s = sorted(xs)
    if not s:
        return 0
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else round((s[mid - 1] + s[mid]) / 2)


def report(mode: str, res: dict, titles: dict[str, str], markdown: bool) -> None:
    changes: list[Change] = res["changes"]
    by_cls = Counter(c.cls for c in changes)
    songs = sorted({c.uri for c in changes}, key=lambda u: titles.get(u, u).lower())
    lone = sum(n for (cls, reason), n in res["unchanged"].items()
               if reason != phase_partner.TARGET_PARTNER)
    already = sum(n for (cls, reason), n in res["unchanged"].items()
                  if reason == phase_partner.TARGET_PARTNER)
    between = Counter(w for c in changes for w in set(c.between))
    head = f"{MODE_LABEL.get(mode, mode)} (`{mode}`)"
    lines = []
    if markdown:
        lines.append(f"#### {head}")
        lines.append("")
        lines.append(f"- Charges that fire: {res['fired']['charge']}; lulls: {res['fired']['lull']}.")
        lines.append(f"- **Builds that change: {by_cls['charge']} charges and {by_cls['lull']} lulls, "
                     f"on {len(songs)} songs.** Every one now runs out to its own lull or drop.")
        for cls in ("charge", "lull"):
            cs = [c for c in changes if c.cls == cls]
            if cs:
                lines.append(f"- {cls.capitalize()} builds: median {median([c.old_build for c in cs])} ms "
                             f"→ {median([c.new_build for c in cs])} ms.")
        if between:
            lines.append("- What sat inside them (per build): "
                         + ", ".join(f"{w} {n}" for w, n in between.most_common()) + ".")
        lines.append(f"- Unchanged: {already} builds already ran straight to their own lull or "
                     f"drop; {lone} have no lull or drop of their own ahead and keep the old "
                     "next-trigger build.")
        lines.append("")
        lines.append("| Song | Build | At | Old: built to | Old build | New: built to | New build | In between |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for uri in songs:
            for c in sorted((c for c in changes if c.uri == uri), key=lambda c: c.at_ms):
                lines.append(f"| {titles.get(uri, uri)} | {c.cls} | {mmss(c.at_ms)} | {c.old_target} "
                             f"| {c.old_build} ms | {c.new_target} | {c.new_build} ms "
                             f"| {', '.join(c.between)} |")
        lines.append("")
    else:
        lines.append(f"── {head} " + "─" * 40)
        lines.append(f"charges that fire: {res['fired']['charge']}   lulls that fire: {res['fired']['lull']}")
        lines.append(f"builds that change: {by_cls['charge']} charges, {by_cls['lull']} lulls, "
                     f"on {len(songs)} songs (all now build to their own lull or drop)")
        lines.append(f"unchanged: {already} already built to their own partner; {lone} have no "
                     "partner ahead and keep the old next-trigger build")
        if between:
            lines.append("inside the changed builds: "
                         + ", ".join(f"{w} {n}" for w, n in between.most_common()))
        for uri in songs:
            lines.append(f"\n  {titles.get(uri, uri)}   [{uri}]")
            for c in sorted((c for c in changes if c.uri == uri), key=lambda c: c.at_ms):
                lines.append(f"    {c.cls:<6} @ {mmss(c.at_ms)}   old: {c.old_build:>6} ms to "
                             f"{c.old_target:<22} new: {c.new_build:>6} ms to {c.new_target:<8}"
                             f"   between: {', '.join(c.between)}")
        lines.append("")
    print("\n".join(lines))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--storage", type=Path, default=DEFAULT_STORAGE,
                    help="storage tree to read (never written); default ~/SpotFX/storage")
    ap.add_argument("--mode", action="append", choices=sorted(MODE_LABEL),
                    help="scene_change_mode to evaluate (repeatable); default: "
                         "triggers_only and full")
    ap.add_argument("--baseline-ref", default=BASELINE_REF)
    ap.add_argument("--markdown", action="store_true", help="PR-ready markdown")
    args = ap.parse_args()

    store = args.storage / "spectra" / "triggers.json"
    if not store.exists():
        print(f"no trigger store at {store} — pass --storage", file=sys.stderr)
        return 2
    baseline = load_baseline_engine(args.baseline_ref)
    songs, skipped = load_store(args.storage)
    titles = load_titles(args.storage)
    live_mode = stored_mode(args.storage)
    modes = args.mode or list(DEFAULT_MODES)

    intro = (f"Read {store} ({len(songs)} songs; {skipped} unreadable rows skipped). "
             f"Old answer: the pre-rule engine at {args.baseline_ref[:12]}. ")
    if live_mode:
        intro += (f"The room's stored mode right now is `{live_mode}` "
                  f"({MODE_LABEL.get(live_mode, live_mode)})")
        intro += ("; his own charges and lulls do not fire in it, so nothing changes in the "
                  "room until a mode that fires them is chosen." if live_mode in
                  ("analysed", "transitions") else ".")
    print(intro + "\n")

    failed = False
    for mode in modes:
        res = analyse(songs, mode, baseline)
        report(mode, res, titles, args.markdown)
        if res["problems"]:
            failed = True
            print("UNEXPECTED CHANGES:", *res["problems"], sep="\n  ")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
