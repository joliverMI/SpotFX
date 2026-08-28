"""WHICH DEVICES ARE ACTUALLY IN USE — the /devices page's default view.

His ask, verbatim: "we need go clean up the device list soon. only devices
i use should be visible on default. can show more with expansion tab."

THE RULE, one sentence: a device is IN USE iff it backs a virtual in
spectra/services/room_topology.genuinely_driven_virtual_ids() — the
compiler's own ground truth (imported category topology UNION every stored
scene's literal virtual targets), the same truth compile_scene() resolves a
real fire against. Nothing else counts, and in particular a device's type
is never consulted: two of his ten in-use devices are DUMMIES
(gap-crystal-mapper, load-bearing in the crystal mapper chain, and
radial-dummy), and eleven of his twenty-one are LedFX-seed machinery (gap
placeholders and mask/foreground/background layer dummies) that back
nothing. A type-based or name-based rule would get both halves wrong.

COMPUTED AT REQUEST TIME, NEVER STORED. The split is a function of the
current topology, so importing a virtual into a category or saving a scene
that targets it moves its device into the default view on the next load,
with nothing to migrate and no list that can drift out of step with the
room. This is the completeness-by-construction rule the activation gate
already relies on for the same set.

AN ABSENT GROUND TRUTH MEANS NO RESTRICTION. room_topology returns an EMPTY
set when there is nothing to go on (no categories imported AND no stored
scenes); every device is then reported in use, so a fresh or unseeded
install shows its whole list rather than an empty page.

DUPLICATES are named, never removed. A device with the same NAME and same
TYPE as another one, which is itself not in use, is flagged as a duplicate
of that other device — generic, not a hardcoded id (his real data has
exactly one: sconce-kitchen-left-1, byte-identical in name and type to the
live sconce-kitchen-left, backing nothing). The page deliberately has NO
delete, so flagging is the whole of it: removing a device tears down its
virtuals and rewrites scenes, which is not what he asked for.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional


def driven_virtual_ids() -> set[str]:
    """The ground truth, read fresh. Isolated here so a caller (and a test)
    has one seam to substitute."""
    from spectra.services import room_topology
    return room_topology.genuinely_driven_virtual_ids()


def _in_use(entry: dict, driven: set[str]) -> bool:
    if not driven:                    # no ground truth -> no restriction
        return True
    return any(vid in driven for vid in (entry.get("virtuals") or []))


def _duplicate_of(entry: dict, entries: Iterable[dict],
                  usage: dict[str, bool]) -> Optional[str]:
    """The device this one duplicates, or None. Only a NOT-IN-USE device is
    ever called a duplicate — an in-use device is doing a job regardless of
    what it is named. A used twin wins over an unused one, so the flag
    points at the fixture the room is really driving."""
    if usage.get(entry.get("id")):
        return None
    name = (entry.get("config") or {}).get("name") or entry.get("id")
    twins = [o for o in entries
             if o.get("id") != entry.get("id")
             and o.get("type") == entry.get("type")
             and ((o.get("config") or {}).get("name") or o.get("id")) == name]
    if not twins:
        return None
    twins.sort(key=lambda o: (not usage.get(o.get("id")), str(o.get("id"))))
    return twins[0].get("id")


def annotate(entries: list[dict], driven: Optional[set[str]] = None) -> list[dict]:
    """Stamp `in_use` and `duplicate_of` onto each device entry (copies —
    the caller's dicts are not mutated). `driven` is injectable purely so a
    test can pin a topology; production passes nothing and it is read live."""
    driven = driven_virtual_ids() if driven is None else driven
    usage = {e.get("id"): _in_use(e, driven) for e in entries}
    out = []
    for e in entries:
        e = dict(e)
        e["in_use"] = usage.get(e.get("id"), True)
        e["duplicate_of"] = _duplicate_of(e, entries, usage)
        out.append(e)
    return out


def summary(entries: list[dict]) -> dict[str, Any]:
    """Counts for the expansion control, so a hidden device is never a
    silent absence: the page can say "11 more not in use" without
    re-deriving anything."""
    used = sum(1 for e in entries if e.get("in_use"))
    return {"in_use": used, "not_in_use": len(entries) - used,
            "rule": "A device is in use when it backs a virtual the room's "
                    "scene engine can actually address — a category "
                    "membership or a scene's own target. Computed fresh on "
                    "every read, so adding a device to a scene or a grouping "
                    "brings it into this list on the next load."}
