"""GET /api/upcoming?uri=&limit= — the merged list of upcoming fire moments
for one song (song-layout-plan, data/ui-layout-plan/report.md §4/§7/§12):
"only what will fire", computed by the engine's OWN gating — never
re-derived here or in the browser (AGENTS.md: "a held room and a broken
room must not look the same" — a countdown that promises an event the
room will never play is exactly that same lie, one layer up).

Composes the SAME functions GET /api/analysed-plan already calls
(`spectra.api.analysed_plan._plan_with_cues`, itself built from
`analysed_flares.scene_change_moments`/`analysed_flares_allowed`,
`drop_firing.annotated_view`, `show_cues.get_or_compute` — each the one
definition its own feature owns), plus `TriggerEngine._trigger_allowed`/
`_effective_mode_for_song` — the exact two static calls `tick()` itself
makes before firing a stored trigger — for the "his own triggers fire
instead" case. No new gating rule is invented anywhere in this module.

Three sources, one merge, one sort:
  - `applies=True`  (analysed events fire): the plan's own `scene_changes`
    + `flares` — already filtered to what `scene_change_moments` says
    will land (protected drop-sequence windows excluded).
  - `applies=False` (his own triggers play this song instead, "triggers_
    only"/"full" with authored triggers present): his enabled stored
    triggers that `_trigger_allowed` admits under the song's own
    effective mode — the SAME filter `tick()` applies, so this is never a
    second idea of "will it fire".
  - Drop-sequence members whose own `fires` flag (`drop_firing.annotate`)
    says so — a `waits_for_confirm` SUGGESTED member is excluded, never
    shown as upcoming.
  - The Light Show's High/Low cues (`show_cues`) — independent of whether
    analysed events apply, same as the Timeline's own markers.

Every `ms` is SONG time, the stored-trigger convention (timestamp + the
trigger's own offset) — the caller places it against the show clock
(`show_clock_ms`), not this route's business.

A DROP ALSO CARRIES `fire_ms` (2026-10-28, the Admiral's Q4 on the Drops
panel proposal): the moment it actually fires — its mark plus the drop
band's offset plus the drop timing offset, drop_firing.annotate's
`fire_ms`. A detected sequence's own `fire_ms` comes from `drop_timing.
fire_moment_ms`; one of his own authored drop triggers (read here off
`plan["drop_sequences"]["yours"]`) comes from the separate `drop_timing.
his_fire_moment_ms` instead, since his stored timestamp is already
offset-inclusive and the plain formula would double-count a nonzero
`trigger_offset_ms` — see drop_firing.annotate's own docstring. Its
marker is drawn at `ms`, the mark; the next-event box counts to `fire_ms`.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query

from spectra.api.analysed_plan import _plan_with_cues
from spectra.services import trigger_store
from spectra.services.trigger_engine import TriggerEngine

router = APIRouter(prefix="/api", tags=["spectra-upcoming"])

_ACTION_KIND = {
    "fire_scene": "scene",
    "select_color_set": "colour",
    "fire_response": "flare",
    "fire_scene_update": "flare",
}


def upcoming_for_song(uri: str, limit: int = 20) -> dict:
    stored = trigger_store.list_for_song(uri)
    plan = _plan_with_cues(uri)
    mode = plan["effective_mode"]
    has_authored = plan["has_authored"]

    events: list[dict] = []
    view = plan.get("drop_sequences") or {}
    his_fire = {str((r.get("drop") or {}).get("id")): r.get("fire_ms")
                for r in view.get("yours") or [] if r.get("fire_ms") is not None}

    if plan["applies"]:
        for s in plan["scene_changes"]:
            events.append({
                "ms": s["timestamp_ms"], "kind": "scene",
                "rank": s.get("rank"), "rank_of": s.get("rank_of"),
                "source": plan.get("scene_source") or "analysed",
            })
        for f in plan["flares"]:
            events.append({
                "ms": f["timestamp_ms"], "kind": "flare",
                "rank": f.get("rank"), "rank_of": f.get("rank_of"),
                "source": "analysed",
            })
    else:
        # His own triggers fire instead of the planned analysed events —
        # show exactly what tick() fires, nothing it wouldn't.
        for t in stored:
            if not t.enabled or not TriggerEngine._trigger_allowed(t, mode):
                continue
            if t.action.kind == "fire_response":
                kind = t.action.event_class
            else:
                kind = _ACTION_KIND.get(t.action.kind, "flare")
            ev = {
                "ms": t.timestamp_ms + t.trigger_offset_ms, "kind": kind,
                "rank": None, "rank_of": None, "source": "authored",
            }
            if kind == "drop" and his_fire.get(str(t.id)) is not None:
                ev["fire_ms"] = int(his_fire[str(t.id)])
            events.append(ev)

    seqs = view.get("sequences") or []
    ordered = sorted(seqs, key=lambda s: s.get("drop_ms", 0))
    for num, s in enumerate(ordered, start=1):
        if not s.get("fires"):
            continue
        stood_down = s.get("stood_down") or {}
        if (s.get("charge_ms") is not None and not s.get("charge_off")
                and "charge" not in stood_down):
            events.append({"ms": s["charge_ms"], "kind": "charge",
                           "rank": None, "rank_of": None,
                           "source": "drop_sequence", "num": num})
        if (s.get("lull_ms") is not None and not s.get("lull_off")
                and "lull" not in stood_down):
            events.append({"ms": s["lull_ms"], "kind": "lull",
                           "rank": None, "rank_of": None,
                           "source": "drop_sequence", "num": num})
        if s.get("drop_ms") is not None:
            ev = {"ms": s["drop_ms"], "kind": "drop", "rank": None, "rank_of": None,
                  "source": "drop_sequence", "num": num}
            if s.get("fire_ms") is not None:
                ev["fire_ms"] = int(s["fire_ms"])
            events.append(ev)

    cues = plan.get("show_cues") or {}
    for level in ("high", "low"):
        c = cues.get(level)
        if isinstance(c, dict) and c.get("timestamp_ms") is not None:
            events.append({"ms": c["timestamp_ms"], "kind": level,
                           "rank": None, "rank_of": None, "source": "show_cue"})

    events.sort(key=lambda e: e["ms"])
    return {"uri": uri, "effective_mode": mode, "has_authored": has_authored,
            "events": events[:max(0, limit)]}


@router.get("/upcoming")
async def get_upcoming(uri: str = Query(..., min_length=1),
                       limit: int = Query(default=20, ge=1, le=200)):
    return await asyncio.to_thread(upcoming_for_song, uri, limit)
