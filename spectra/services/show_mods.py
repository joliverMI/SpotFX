"""THE LIGHT SHOW's EFFECT MODIFIERS — Pulse modulation and flares on/off
(the Admiral, 2026-10-08: "modulate a few things on the 'pulse' effect.
1. Overall reactivity ... 2. the brightness floor and ceiling ... 3. Ability
to turn flares on and off for devices and device categories. This is
specifically important that we be able to turn flares off for the hues").

Both are HOLDS shaped like show_output's Levels: they start when the step
fires, end after a time / at the next scene change / when released, survive
a restart (a timed one whose end has passed is dropped), are let go by End
show, and are dropped outright when the room is released. show_output's own
`tick`, `repush`, `release_all`, `on_scene_change`, `on_release` and `reset`
call into this module, so every existing caller of those carries them too.

BOTH WORK ON VIRTUALS, NOT FIXTURES, and that is a fact about the room, not
a choice: Pulse is an effect on a virtual, and a flare is a write to a
virtual's effect config. A target resolves to virtuals here
(`resolve_virtuals`): a category to its own virtuals (the shared category
registry), a fixture to every virtual whose segments touch it, Everything to
every virtual in the live stack. A fixture that shares a virtual with
another (his `hues` virtual drives BOTH Hue areas) takes the other one with
it, and the step's outcome NAMES those fixtures.

PULSE MODULATION. Stacked per virtual — reactivities multiply, the highest
floor and the lowest ceiling win — and pushed into `fx/pulse_modulation.py`
with the hold's fade, which `fx/effects/pulse.py` reads every frame. A
virtual not running Pulse right now is unaffected, and picks the
modulation up the moment it does while the hold lasts. Suspended (reads
untouched, targets kept) whenever the per-device output layer is: a preview,
capture or night run holding the room.

FLARES OFF. `blocked_virtuals()` is the set scene_response skips
(ResponseEngine `flare_blocked`, wired in engine.py): every FLARE KIND
(dice re-rolls, param patches, gains, colour jumps/rotates, firework bursts,
blob rushes, Pulse flash/flip) AND the charge/lull/drop choreography (the
Admiral, 2026-10-08: "turning off flares should also turn off drop effect.
so it shouldn't get dark on a drop, or burst") — those virtuals just keep
playing their normal look through a sequence, and a charge/lull already
under way there is let go when the switch goes off
(ResponseEngine.release_phase_on). NOT the analysed scene-cue colour
moment, which is a scene-level colour change, not a flare. A momentary
spike that landed BEFORE the switch went off still releases. "Flares on"
lifts every flare switch touching the targeted virtuals.
"""
from __future__ import annotations

import logging
from typing import Iterable, Optional

from fx import pulse_modulation
from spectra.models.light_show import FlareBlock, PulseModHold, now_ms
from spectra.services import show_store

logger = logging.getLogger(__name__)

MAX_FADE_MS = 60_000


def _fade_s(ms) -> float:
    return max(0, min(MAX_FADE_MS, int(ms or 0))) / 1000.0


def _host():
    from spectra.services.live_host import live
    return live.host


# ── targets → virtuals ─────────────────────────────────────────────────────

def _all_virtual_ids(host) -> list[str]:
    return [str(v) for v in list(host.virtuals)] if host is not None else []


def _virtual_device_ids(host, vid: str) -> list[str]:
    from spectra.services import show_output
    return show_output._virtual_devices(host, vid)


def resolve_virtuals(target: dict) -> tuple[list[str], str, list[str], list[str]]:
    """(virtual_ids, label, shared_with, problems). `shared_with` names the
    fixtures a FIXTURE target takes along because they share a virtual with
    it. An unresolvable target returns no virtuals and a problem sentence —
    never a guess."""
    from spectra.services import show_output
    kind = (target or {}).get("kind", "everything")
    tid = (target or {}).get("id")
    host = _host()
    if kind == "category":
        from fx import device_model
        vids = list(device_model.get_virtuals_for_category(tid or ""))
        if not vids:
            return [], str(tid), [], [f"no category called {tid!r} (or it has no virtuals)"]
        return vids, str(tid), [], []
    if host is None:
        return [], "", [], ["the live stack is not up, so no fixture can be resolved"]
    if kind == "everything":
        return _all_virtual_ids(host), "everything", [], []
    if kind == "fixture":
        if tid not in host.devices:
            return [], str(tid), [], [f"no fixture called {tid!r} is in the live stack"]
        vids = [v for v in _all_virtual_ids(host)
                if tid in _virtual_device_ids(host, v)]
        if not vids:
            return [], show_output.device_label(tid), [], [
                f"fixture {show_output.device_label(tid)!r} is fed by no virtual"]
        others: list[str] = []
        for v in vids:
            for d in _virtual_device_ids(host, v):
                if d != tid and d not in others:
                    others.append(d)
        return (vids, show_output.device_label(tid),
                [show_output.device_label(d) for d in others], [])
    return [], "", [], [f"unknown target kind {kind!r}"]


# ── Pulse modulation ───────────────────────────────────────────────────────

def combined(vid: str, mods: Iterable[PulseModHold]) -> pulse_modulation.Mod:
    r, floor, ceiling = 1.0, 0.0, 1.0
    for m in mods:
        if vid not in m.virtual_ids:
            continue
        if m.reactivity is not None:
            r *= max(0.0, min(1.0, m.reactivity))
        if m.floor is not None:
            floor = max(floor, m.floor)
        if m.ceiling is not None:
            ceiling = min(ceiling, m.ceiling)
    return pulse_modulation.Mod(r, floor, ceiling)


def _push_pulse(vids: Iterable[str], fade_ms) -> None:
    st = show_store.state()
    for vid in vids:
        m = combined(vid, st.pulse_mods)
        pulse_modulation.set_mod(vid, reactivity=m.reactivity, floor=m.floor,
                                 ceiling=m.ceiling, fade_s=_fade_s(fade_ms))


def _ends(until: str, duration_s: Optional[float]) -> tuple[str, Optional[int]]:
    if until == "time":
        if not duration_s or duration_s <= 0:
            return "released", None
        return "time", now_ms() + int(float(duration_s) * 1000)
    return until, None


def _pulse_dimension(reactivity: Optional[float], floor: Optional[float],
                     ceiling: Optional[float]) -> str:
    return "reactivity" if reactivity is not None else "brightness"


def add_pulse_mod(virtual_ids: list[str], *, label: str = "",
                  reactivity: Optional[float] = None, floor: Optional[float] = None,
                  ceiling: Optional[float] = None, fade_in_ms: int = 0,
                  fade_out_ms: int = 0, until: str = "released",
                  duration_s: Optional[float] = None, source: str = "") -> PulseModHold:
    st = show_store.state()
    until, ends = _ends(until, duration_s)
    # RE-FIRING THE SAME HOLD KIND ON THE SAME TARGETS RESTARTS IT (the
    # Admiral, 2026-10-08: firing the same step twice left two holds
    # listed instead of resetting the one). A hold on the SAME exact
    # virtual set and the SAME dimension (reactivity, or floor/ceiling)
    # replaces the matching one outright — never a second entry. A
    # DIFFERENT target set, or the OTHER dimension on the same targets,
    # still composes (PulseModHold's own docstring: "several stack").
    target = frozenset(virtual_ids)
    dim = _pulse_dimension(reactivity, floor, ceiling)
    st.pulse_mods = [m for m in st.pulse_mods
                     if not (frozenset(m.virtual_ids) == target
                             and _pulse_dimension(m.reactivity, m.floor, m.ceiling) == dim)]
    m = PulseModHold(virtual_ids=list(virtual_ids), label=label, reactivity=reactivity,
                     floor=floor, ceiling=ceiling, fade_in_ms=int(fade_in_ms or 0),
                     fade_out_ms=int(fade_out_ms or 0), until=until,
                     ends_at_ms=ends, source=source)
    st.pulse_mods.append(m)
    _push_pulse(m.virtual_ids, m.fade_in_ms)
    _mark_started()
    show_store.save_state()
    return m


def end_pulse_mod(mod_id: str, *, fade_ms: Optional[int] = None) -> bool:
    st = show_store.state()
    m = next((x for x in st.pulse_mods if x.id == mod_id), None)
    if m is None:
        return False
    st.pulse_mods = [x for x in st.pulse_mods if x.id != mod_id]
    _push_pulse(m.virtual_ids, m.fade_out_ms if fade_ms is None else fade_ms)
    show_store.save_state()
    return True


# ── flares on/off ──────────────────────────────────────────────────────────

def add_flare_block(virtual_ids: list[str], *, label: str = "",
                    until: str = "released", duration_s: Optional[float] = None,
                    source: str = "") -> FlareBlock:
    st = show_store.state()
    until, ends = _ends(until, duration_s)
    # Same rule as add_pulse_mod: a block on the SAME exact virtual set
    # RESTARTS the matching one (resets until/ends_at) instead of stacking
    # a second, visually-duplicate "flares off" entry.
    target = frozenset(virtual_ids)
    st.flare_blocks = [b for b in st.flare_blocks if frozenset(b.virtual_ids) != target]
    b = FlareBlock(virtual_ids=list(virtual_ids), label=label, until=until,
                   ends_at_ms=ends, source=source)
    st.flare_blocks.append(b)
    _mark_started()
    show_store.save_state()
    return b


def end_flare_block(block_id: str) -> bool:
    st = show_store.state()
    before = len(st.flare_blocks)
    st.flare_blocks = [b for b in st.flare_blocks if b.id != block_id]
    if len(st.flare_blocks) == before:
        return False
    show_store.save_state()
    return True


def lift_flares(virtual_ids: Iterable[str]) -> list[str]:
    """'Flares on' for these virtuals: end every flare switch touching any
    of them. Returns the ended ids."""
    want = set(virtual_ids)
    st = show_store.state()
    ended = [b.id for b in st.flare_blocks if want & set(b.virtual_ids)]
    if ended:
        st.flare_blocks = [b for b in st.flare_blocks if b.id not in ended]
        show_store.save_state()
    return ended


def blocked_virtuals() -> frozenset:
    """Every virtual flares are switched off on right now. Read on every
    flare fire: a list walk over a handful of holds, no I/O."""
    try:
        blocks = show_store.state().flare_blocks
    except Exception:                                    # noqa: BLE001
        logger.exception("light show: flare switches could not be read")
        return frozenset()
    if not blocks:
        return frozenset()
    t = now_ms()
    return frozenset(v for b in blocks
                     if not (b.until == "time" and b.ends_at_ms is not None
                             and b.ends_at_ms <= t)
                     for v in b.virtual_ids)


# ── lifecycle (called from show_output) ────────────────────────────────────

def _mark_started() -> None:
    st = show_store.state()
    if st.started_ms is None:
        st.started_ms = now_ms()


def tick() -> None:
    """End timed holds whose time has come; prune finished fades; follow the
    output layer's suspension."""
    from fx import device_output
    pulse_modulation.suspend(device_output.suspended())
    st = show_store.state()
    t = now_ms()
    for m in list(st.pulse_mods):
        if m.until == "time" and m.ends_at_ms is not None and m.ends_at_ms <= t:
            end_pulse_mod(m.id)
    for b in list(st.flare_blocks):
        if b.until == "time" and b.ends_at_ms is not None and b.ends_at_ms <= t:
            end_flare_block(b.id)
    pulse_modulation.prune()


def on_scene_change() -> list[str]:
    st = show_store.state()
    ending = [m.id for m in st.pulse_mods if m.until == "scene_change"]
    for mid in ending:
        end_pulse_mod(mid)
    blocks = [b.id for b in st.flare_blocks if b.until == "scene_change"]
    for bid in blocks:
        end_flare_block(bid)
    return ending + blocks


def repush() -> dict:
    """Re-install every saved Pulse modulation (the live stack came up). A
    timed hold whose end has passed is dropped, never resurrected."""
    st = show_store.state()
    t = now_ms()
    expired = [m for m in st.pulse_mods
               if m.until == "time" and m.ends_at_ms is not None and m.ends_at_ms <= t]
    stale_blocks = [b.id for b in st.flare_blocks
                    if b.until == "time" and b.ends_at_ms is not None and b.ends_at_ms <= t]
    if expired or stale_blocks:
        gone = {m.id for m in expired}
        st.pulse_mods = [m for m in st.pulse_mods if m.id not in gone]
        st.flare_blocks = [b for b in st.flare_blocks if b.id not in stale_blocks]
        show_store.save_state()
    vids = {v for m in st.pulse_mods for v in m.virtual_ids}
    for vid in vids:
        m = combined(vid, st.pulse_mods)
        pulse_modulation.set_mod(vid, reactivity=m.reactivity, floor=m.floor,
                                 ceiling=m.ceiling, fade_s=0.0)
    for vid in {v for m in expired for v in m.virtual_ids} - vids:
        pulse_modulation.clear(vid)
    return {"pulse_mods": len(st.pulse_mods), "flare_blocks": len(st.flare_blocks)}


def release_all(fade_ms: int) -> dict:
    """End show: let every modulation fade back and switch flares on."""
    st = show_store.state()
    vids = {v for m in st.pulse_mods for v in m.virtual_ids}
    n_mods, n_blocks = len(st.pulse_mods), len(st.flare_blocks)
    st.pulse_mods.clear()
    st.flare_blocks.clear()
    for vid in vids:
        pulse_modulation.set_mod(vid, fade_s=_fade_s(fade_ms))
    if n_mods or n_blocks:
        show_store.save_state()
    return {"pulse_mods": n_mods, "flare_blocks": n_blocks}


def on_release() -> None:
    """The room is being released: drop everything at once."""
    pulse_modulation.clear()
    st = show_store.state()
    if st.pulse_mods or st.flare_blocks:
        st.pulse_mods.clear()
        st.flare_blocks.clear()
        show_store.save_state()


def reset() -> None:
    """Tests."""
    pulse_modulation.clear()
    pulse_modulation.suspend(False)


def status() -> dict:
    st = show_store.state()
    t = now_ms()

    def remaining(h) -> Optional[float]:
        return (round((h.ends_at_ms - t) / 1000.0, 1)
                if h.ends_at_ms is not None else None)

    return {
        "pulse_mods": [{"id": m.id, "virtual_ids": m.virtual_ids, "label": m.label,
                        "reactivity": m.reactivity, "floor": m.floor,
                        "ceiling": m.ceiling, "until": m.until,
                        "remaining_s": remaining(m), "source": m.source}
                       for m in st.pulse_mods],
        "flare_blocks": [{"id": b.id, "virtual_ids": b.virtual_ids, "label": b.label,
                          "until": b.until, "remaining_s": remaining(b),
                          "source": b.source}
                         for b in st.flare_blocks],
        "pulse_live": pulse_modulation.snapshot(),
    }
