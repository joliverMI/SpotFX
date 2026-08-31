"""WHAT THE ROOM BUILDER PICKS FROM — the carriers, not the fixtures.

HIS WORDS, and the criterion this module exists to hold: "i want to be able
to work with the devices that i directly use in spectra even if they have
layers of virtuals before shining. The devices that actually run effects
should be the ones that are shown by default and these are the ones i want
to calibrate... spectra can delayer it if easier."

A CARRIER is a genuinely-driven virtual — one of the things his scenes and
categories actually address (spectra/services/room_topology.
genuinely_driven_virtual_ids, the same ground truth the compiler resolves a
real fire against). It is NOT a fixture: four of his seven carriers fan out
to several devices at once —

    tv-mapper           -> tv-backlight + both kitchen sconces
    hues                -> both Hue groups
    single-color-effect -> porch-rail + dining-table
    crystal-mapper      -> crystal, through its chain dummy

— so a device-keyed picker cannot name the things he calibrates, and asking
him to calibrate a fixture he never addresses is asking the wrong question.

TWO QUESTIONS, ONE COMPOSITE CRITERION. `device_usage`'s `in_use` answers
"does this back something driven" — right for the /devices page, which is
about fixtures and stays exactly as it was. This picker's question is "what
do I address that a camera can see", and it is a composite:

    a carrier is offered  iff  it is genuinely driven
                          AND  its segment chain reaches at least one
                               physical, light-emitting device

The second half is `emitters.emits_light`, applied at the CHAIN rather than
at the picked thing: `radial-dummy` is genuinely driven and reaches no
emitter at all, so a camera cannot see it and it is not offered. Nothing
here consults a device's type for any other purpose — the per-device timing
offsets stay per DEVICE, underneath and orthogonal.

THE CHAIN IS ALREADY RESOLVED, which is the fact worth noticing: the
capture lamp writes to VIRTUALS and the render gain mask is per VIRTUAL, so
the machinery beneath was carrier-native all along. Only the list disagreed
with him.
"""
from __future__ import annotations

from typing import Iterable, Optional

from spectra.services import emitters


def devices_by_carrier(device_entries: Iterable[dict]) -> dict[str, list[dict]]:
    """carrier id -> the device entries whose segments back it.

    Built by REVERSING the device listing's own `virtuals` field — the one
    definition of that mapping in this app (device_console), so this can
    never disagree with what the /devices page shows."""
    out: dict[str, list[dict]] = {}
    for entry in device_entries or []:
        for vid in (entry or {}).get("virtuals") or []:
            out.setdefault(vid, []).append(entry)
    return out


def reaches_an_emitter(devices: Iterable[dict]) -> bool:
    """Whether any fixture in this carrier's chain actually emits light."""
    return any(emitters.emits_light(d) for d in devices or [])


def carrier_rows(device_entries: Iterable[dict],
                 driven: Optional[set[str]] = None) -> list[dict]:
    """Every offerable carrier, with the fixtures it reaches.

    `driven` defaults to the room's own ground truth. An ABSENT ground
    truth is no restriction (room_topology's own rule): every carrier the
    devices name is offered, so a fresh install shows a list rather than an
    empty page — the chain check still applies, because a dummy is
    unphotographable whether or not anything is seeded."""
    if driven is None:
        from spectra.services import room_topology
        driven = room_topology.genuinely_driven_virtual_ids()
    by_carrier = devices_by_carrier(device_entries)
    candidates = sorted(by_carrier) if not driven else sorted(
        c for c in by_carrier if c in driven)
    rows = []
    for carrier in candidates:
        chain = by_carrier.get(carrier) or []
        if not reaches_an_emitter(chain):
            continue
        rows.append({
            "id": carrier,
            "devices": [d.get("id") for d in chain if emitters.emits_light(d)],
            "all_devices": [d.get("id") for d in chain],
            "device_types": sorted({str(d.get("type") or "")
                                    for d in chain if emitters.emits_light(d)}),
        })
    return rows


def hidden_rows(device_entries: Iterable[dict],
                driven: Optional[set[str]] = None) -> list[dict]:
    """The driven carriers a camera could NOT see, with why — so "where is
    radial-dummy" has an answer that is not a shrug."""
    if driven is None:
        from spectra.services import room_topology
        driven = room_topology.genuinely_driven_virtual_ids()
    by_carrier = devices_by_carrier(device_entries)
    out = []
    for carrier in sorted(by_carrier):
        if driven and carrier not in driven:
            continue
        chain = by_carrier.get(carrier) or []
        if reaches_an_emitter(chain):
            continue
        out.append({"id": carrier,
                    "all_devices": [d.get("id") for d in chain],
                    "reason": "nothing in this carrier's chain emits light, "
                              "so a camera has nothing to photograph"})
    return out
