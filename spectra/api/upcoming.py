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

EVERY ROW CARRIES `id` — THE TRIGGER ID tick() FIRES FOR IT (2026-11-12): a
stored trigger's own id, the analysed plan's synthetic ids (`analysed_plan.
_plan`), or a drop sequence member's `drop_firing.ID_PREFIX + key + ":" +
class`. Light Show cues have none. It is how a row is joined to anything
else the engine says about the same fire — never by time, since a flare's
landing moment carries its lead and its mark does not.

WORD COLOURS (the Admiral, 2026-11-12: "Add a visual highlight to scene
changes and flares and drops that are getting a word related effect"; his
pick on data/word-effect-highlight-options: option A plus E's live pulse).
On a song whose show has word colours on (`lyric_events.enabled`), the SAME
plan the Test Bed's Word actions row shows (`TriggerEngine.
preview_lyric_events`, `lyric_events.plan_words`) is joined on here by id:
an event a word imprints on gains `word` / `word_ms` / `swatch` (the word's
first candidate set's colour, as the Word matches row draws it — which set
really lands is decided at fire time and pushed as {"type": "word_colour"}),
and a word firing on its own becomes its own row, `kind: "word"`, drawn
where it is sung and counted down to like any other event (his answer to
decision 3). Words that do nothing add nothing here — the Test Bed is
where those are explained. That includes a word sitting out this play (THE
ROLL, lyric_events.py): for the song playing the preview is this play's
roll, so only the words that won it are lent to an event or drawn. No new gating rule: `plan_words` is the one
plan, read once per request on this worker thread, and a failure to read
the words leaves the list exactly as it was (the strip must never go blank
because the lyrics are unreadable).
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Query

from spectra.api.analysed_plan import _plan_with_cues
from spectra.services import drop_firing, lyric_events, trigger_store
from spectra.services.trigger_engine import TriggerEngine, trigger_engine

logger = logging.getLogger(__name__)

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
                "source": plan.get("scene_source") or "analysed", "id": s.get("id"),
            })
        for f in plan["flares"]:
            events.append({
                "ms": f["timestamp_ms"], "kind": "flare",
                "rank": f.get("rank"), "rank_of": f.get("rank_of"),
                "source": "analysed", "id": f.get("id"),
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
                "rank": None, "rank_of": None, "source": "authored", "id": str(t.id),
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
        member_id = (lambda cls: f"{drop_firing.ID_PREFIX}{s['key']}:{cls}"
                     if s.get("key") is not None else None)
        if (s.get("charge_ms") is not None and not s.get("charge_off")
                and "charge" not in stood_down):
            events.append({"ms": s["charge_ms"], "kind": "charge",
                           "rank": None, "rank_of": None,
                           "source": "drop_sequence", "num": num, "id": member_id("charge")})
        if (s.get("lull_ms") is not None and not s.get("lull_off")
                and "lull" not in stood_down):
            events.append({"ms": s["lull_ms"], "kind": "lull",
                           "rank": None, "rank_of": None,
                           "source": "drop_sequence", "num": num, "id": member_id("lull")})
        if s.get("drop_ms") is not None:
            ev = {"ms": s["drop_ms"], "kind": "drop", "rank": None, "rank_of": None,
                  "source": "drop_sequence", "num": num, "id": member_id("drop")}
            if s.get("fire_ms") is not None:
                ev["fire_ms"] = int(s["fire_ms"])
            events.append(ev)

    cues = plan.get("show_cues") or {}
    for level in ("high", "low"):
        c = cues.get(level)
        if isinstance(c, dict) and c.get("timestamp_ms") is not None:
            events.append({"ms": c["timestamp_ms"], "kind": level,
                           "rank": None, "rank_of": None, "source": "show_cue"})

    events = with_words(uri, events)
    events.sort(key=lambda e: e["ms"])
    return {"uri": uri, "effective_mode": mode, "has_authored": has_authored,
            "events": events[:max(0, limit)]}


def word_plan(uri: str) -> lyric_events.Preview | None:
    """The word plan for the join above — the engine's own preview, the one
    the Test Bed shows — or None when the show has word colours off (the
    common case: one store read, nothing else touched). Split out so a test
    can hand the route a plan without a lyrics timeline on disk."""
    if not lyric_events.enabled(uri):
        return None
    return trigger_engine.preview_lyric_events(uri)


def with_words(uri: str, events: list[dict]) -> list[dict]:
    """Lend each imprinted event its word, and add a marker per word firing
    alone (lyric_events.word_marks). Any failure leaves `events` untouched."""
    try:
        preview = word_plan(uri)
    except Exception:                                    # noqa: BLE001
        logger.exception("upcoming: the word plan is unreadable for %s", uri)
        return events
    if preview is None or not preview.actions:
        return events
    imprints, fires = lyric_events.word_marks(preview.actions)
    out: list[dict] = []
    for ev in events:
        word = imprints.get(ev.get("id") or "")
        out.append({**ev, **word} if word else ev)
    out.extend(fires)
    return out


@router.get("/upcoming")
async def get_upcoming(uri: str = Query(..., min_length=1),
                       limit: int = Query(default=20, ge=1, le=200)):
    return await asyncio.to_thread(upcoming_for_song, uri, limit)
