"""WHICH FIXTURES A TAKE MAY BRING UP — the narrow half of "a capture run
touches only what it measures".

THE INCIDENT THIS EXISTS FOR (2026-09-07, the Admiral verbatim): "you turned
off the bathroom light... be more selective about which lights you turn
off." A kitchen/living-room capture run needs the two WLED sconces and the
TV backlight. It took the WHOLE room — which on his config means the `hues`
virtual, which spans BOTH Hue bridges and the two entertainment
configurations behind them, seventeen bulbs from the hallway to the
bathroom — drove every one of them, and switched every one of them off on
the way out.

Neither half of that was a bug in the release. The release let go of exactly
what the take had taken. THE TAKE WAS THE WRONG SIZE.

────────────────────────────────────────────────────────────────────────────
THE ONE RULE, and it is a rule about DEVICES, not about virtuals
────────────────────────────────────────────────────────────────────────────

A device is activated by ONE thing and one thing only: a virtual with
segments on it activating (`fx.virtuals.Virtual.activate_segments`). So the
scope is computed as a set of DEVICES the run is allowed to reach, and the
virtual scope handed to the take is then

    every config virtual whose segments touch ONLY in-scope devices

— which makes "no out-of-scope fixture can be activated by this take" a
STRUCTURAL fact rather than an intention. There is no virtual left able to
reach one.

Deriving the virtual set that way, rather than naming carriers directly,
also keeps the config's own relationships intact inside the scope: the
device-virtual/external-virtual eviction dance (`Device.add_segments_batch`,
fx/VENDOR.md #29), a copy carrier's substitute, a per-segment virtual — all
of them load and behave exactly as they do on a whole-room take, because
every one of them is either wholly inside the scope or wholly outside it.

────────────────────────────────────────────────────────────────────────────
IT READS THE STORED CONFIG, NOT A LIVE HOST
────────────────────────────────────────────────────────────────────────────

The scope has to be known BEFORE the take, so there is no live host to ask.
It reads `storage/spectra/fx-live/config.json` — the same file
`handover.SpectraSide.readiness_problems` already gates the take on — plus
the room map. Both are on disk before anything is activated.

────────────────────────────────────────────────────────────────────────────
UNRESOLVABLE MEANS THE WHOLE ROOM, AND IT SAYS SO
────────────────────────────────────────────────────────────────────────────

`resolve()` returns `None` — meaning "take the whole room, exactly as
before" — for every case it cannot answer confidently: an unknown room, a
room with no declared carriers, a carrier that is not a virtual in this
config, an unreadable config. That is the NON-REGRESSIVE direction: a
wrongly-narrow scope brings the room up missing the fixture the run needed
and wastes a night; a wrongly-wide one is today's behaviour. Every `None`
carries a `reason`, so "why did tonight take the whole house" is a read.

The refusal for an EMPTY intersection lives one layer down, in
`live_host.activate`: a scope that resolves but brings nothing up would sail
through the freshness gate vacuously, and that is a take that must fail
loudly rather than fall back.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from spectra import config as scfg

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TakeScope:
    """What a scoped take may bring up."""
    #: virtual ids allowed to come up ACTIVE — what `live_host.activate`
    #: takes as its `scope`
    virtual_ids: set[str] = field(default_factory=set)
    #: the device ids those virtuals touch — the fixtures this take can
    #: possibly reach, and the sentence a human reads
    device_ids: set[str] = field(default_factory=set)
    #: the carriers the scope was derived from, in declaration order
    carriers: list[str] = field(default_factory=list)
    #: device ids in the config that this take is provably leaving alone
    excluded_device_ids: set[str] = field(default_factory=set)

    def as_dict(self) -> dict:
        return {"virtual_ids": sorted(self.virtual_ids),
                "device_ids": sorted(self.device_ids),
                "carriers": list(self.carriers),
                "excluded_device_ids": sorted(self.excluded_device_ids)}


@dataclass(frozen=True)
class ScopeOutcome:
    """`resolve()`'s full answer. `scope is None` means the whole room, and
    `reason` says why — an unscoped take is never silent."""
    scope: Optional[TakeScope]
    reason: str = ""

    def as_dict(self) -> dict:
        return {"scoped": self.scope is not None, "reason": self.reason,
                **(self.scope.as_dict() if self.scope else {})}


def _devices_of(virtual_cfg: dict) -> set[str]:
    return {str(seg[0]) for seg in (virtual_cfg or {}).get("segments") or []
            if isinstance(seg, (list, tuple)) and seg and seg[0]}


def load_config_virtuals(config_dir: Optional[Any] = None) -> dict[str, dict]:
    """`{virtual id: stored virtual config}` from the fx-live config on
    disk. `{}` when it cannot be read — the caller treats that as
    unresolvable, never as an empty room."""
    path = Path(str(config_dir or scfg.FX_LIVE_CONFIG_DIR)) / "config.json"
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        logger.warning("take scope: fx-live config unreadable (%s): %s",
                       path, exc)
        return {}
    return {str(v.get("id")): v for v in (raw.get("virtuals") or [])
            if v.get("id")}


def carriers_for_item(room: Any, carrier_ids: Optional[Iterable[str]] = None,
                      emitter_ids: Optional[Iterable[str]] = None) -> list[str]:
    """The carriers ONE declared queue item will drive.

    An emitter id belongs to exactly one carrier and its footprint says
    which (`RoomMap.footprints`), so an emitter-scoped item resolves to
    those carriers; a carrier-scoped item to its own list; an unscoped item
    to the room's whole declared carrier list — which is still a scope,
    because a room is not the house."""
    named = [str(c) for c in (carrier_ids or []) if str(c).strip()]
    if named:
        return list(dict.fromkeys(named))
    wanted = {str(e) for e in (emitter_ids or []) if str(e).strip()}
    if wanted:
        out: list[str] = []
        for footprint in getattr(room, "footprints", []) or []:
            if getattr(footprint, "emitter_id", None) in wanted:
                carrier = getattr(footprint, "carrier", "")
                if carrier and carrier not in out:
                    out.append(str(carrier))
        if out:
            return out
        # An emitter id the map has never seen: `emitters.py`'s own id shape
        # is "<carrier>:<piece>", so the carrier is recoverable — but only
        # when it names a real carrier of this room. Anything else is
        # unresolvable and the caller widens.
        known = {str(c) for c in getattr(room, "carrier_ids", []) or []}
        for eid in sorted(wanted):
            head = eid.split(":", 1)[0]
            if head in known and head not in out:
                out.append(head)
        return out
    return [str(c) for c in getattr(room, "carrier_ids", []) or []]


def scope_for_carriers(carriers: Iterable[str],
                       virtuals: dict[str, dict]) -> Optional[TakeScope]:
    """The whole rule, as a pure function over the stored config: carriers →
    the devices they touch → every virtual confined to those devices.

    `None` when a named carrier is not a virtual in this config, or names no
    device — an answer we cannot stand behind, so the caller widens rather
    than guesses."""
    wanted = [str(c) for c in carriers if str(c).strip()]
    if not wanted:
        return None
    device_ids: set[str] = set()
    for carrier in wanted:
        cfg = virtuals.get(carrier)
        if cfg is None:
            logger.warning("take scope: carrier %r is not a virtual in the "
                           "fx-live config", carrier)
            return None
        devices = _devices_of(cfg)
        if not devices:
            logger.warning("take scope: carrier %r has no device segments",
                           carrier)
            return None
        device_ids |= devices
    virtual_ids = {vid for vid, cfg in virtuals.items()
                   if _devices_of(cfg) and _devices_of(cfg) <= device_ids}
    if not virtual_ids:
        return None
    every_device = set()
    for cfg in virtuals.values():
        every_device |= _devices_of(cfg)
    return TakeScope(virtual_ids=virtual_ids, device_ids=device_ids,
                     carriers=list(dict.fromkeys(wanted)),
                     excluded_device_ids=every_device - device_ids)


def resolve_for_items(items: Iterable[Any], *,
                      config_dir: Optional[Any] = None,
                      get_room=None) -> ScopeOutcome:
    """The scope for a whole declared capture queue — the UNION of what its
    items drive, because ONE take serves all of them.

    Every item is resolved independently and any single unresolvable item
    widens the whole take: a queue whose second item we cannot place must
    not run its second item against a room brought up for the first."""
    items = list(items or [])
    if not items:
        return ScopeOutcome(None, "no declared items to scope a take by")
    virtuals = load_config_virtuals(config_dir)
    if not virtuals:
        return ScopeOutcome(None, "the fx-live config could not be read, so "
                                  "the take cannot be narrowed")
    if get_room is None:
        from spectra.services.light_field import get_room as _get_room
        get_room = _get_room

    carriers: list[str] = []
    for item in items:
        room_id = str(getattr(item, "room_id", "") or "")
        room = get_room(room_id) if room_id else None
        if room is None:
            return ScopeOutcome(None, f"room {room_id!r} is not in the room "
                                      f"map, so the take cannot be narrowed")
        found = carriers_for_item(room,
                                  getattr(item, "carrier_ids", None),
                                  getattr(item, "emitter_ids", None))
        if not found:
            return ScopeOutcome(
                None, f"room {room_id!r} declares no carriers, so the take "
                      f"cannot be narrowed")
        for carrier in found:
            if carrier not in carriers:
                carriers.append(carrier)

    scope = scope_for_carriers(carriers, virtuals)
    if scope is None:
        return ScopeOutcome(None, f"the declared carriers {carriers} could "
                                  f"not be placed in the fx-live config, so "
                                  f"the take cannot be narrowed")
    return ScopeOutcome(
        scope,
        f"scoped to {len(scope.device_ids)} device(s) behind "
        f"{len(scope.carriers)} carrier(s) — "
        f"{len(scope.excluded_device_ids)} device(s) in the config are left "
        f"completely alone")
