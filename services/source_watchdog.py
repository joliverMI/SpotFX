"""
SpotFX — source-virtual watchdog.

Some LedFX effects (radial) render another virtual's frames via a
`source_virtual` config key. Effect switching can leave that link broken in
two ways:
  1. the consumer's config lands without a valid source (LedFX defaults the
     key to "unknown" → renders black);
  2. the source virtual itself loses its effect or gets deactivated, so the
     consumer has no frames to pull.

This watchdog runs from the 5 s virtual poller. It restores the PREVIOUS
known-good state rather than hardcoding anything: the consumer's source comes
from the morph_effect_state snapshot (falling back to effect_params
defaults), and the source virtual's effect comes from what this watchdog last
saw running there (falling back to its morph_effect_state snapshots).

Repairs require the same fault on two consecutive polls (~10 s) so we never
fight a scene transition in flight, and every repair is logged.
"""
from __future__ import annotations

import logging

from models.state import state

logger = logging.getLogger(__name__)

STRIKES_NEEDED = 2

# vid -> consecutive polls the fault was seen, per fault kind
_strikes: dict[tuple[str, str], int] = {}
# source vid -> (effect_type, config) last seen actively running there
_last_seen: dict[str, tuple[str, dict]] = {}


def _bump(vid: str, kind: str) -> bool:
    """Count a fault sighting; True when it has persisted long enough to act."""
    key = (vid, kind)
    _strikes[key] = _strikes.get(key, 0) + 1
    return _strikes[key] >= STRIKES_NEEDED


def _clear(vid: str, kind: str) -> None:
    _strikes.pop((vid, kind), None)


def _desired_source(vid: str, effect_type: str) -> str | None:
    """Previous source for (vid, effect): snapshot first, defaults second."""
    from services import morph_aspects, morph_effect_state
    snap = morph_effect_state.get(vid, effect_type) or {}
    if snap.get("source_virtual") and snap["source_virtual"] != "unknown":
        return snap["source_virtual"]
    defaults = morph_aspects.effect_defaults(effect_type) or {}
    src = defaults.get("source_virtual")
    return src if src and src != "unknown" else None


def _fallback_source_effect(src_vid: str) -> tuple[str, dict] | None:
    """No live memory of what ran on the source — use its snapshots."""
    from services import morph_effect_state
    snaps = morph_effect_state.all_for_virtual(src_vid)
    if not snaps:
        return None
    # Prefer melt (the usual strip driver) for determinism, else any.
    etype = "melt" if "melt" in snaps else sorted(snaps)[0]
    return etype, dict(snaps[etype])


async def check_and_repair() -> None:
    """One watchdog pass over the freshly-polled virtual cache."""
    from api import ledfx_client

    cache = state.ledfx_virtual_cache
    # Remember what's actively running everywhere (source-restore memory).
    for vid, vstate in cache.items():
        eff = (vstate or {}).get("effect") or {}
        if eff.get("type") and (vstate or {}).get("active", True):
            _last_seen[vid] = (eff["type"], dict(eff.get("config") or {}))

    for vid, vstate in list(cache.items()):
        eff = (vstate or {}).get("effect") or {}
        etype = eff.get("type")
        cfg = eff.get("config") or {}
        if not etype or "source_virtual" not in cfg:
            _clear(vid, "bad_source")
            _clear(vid, "dead_source")
            continue

        src = cfg.get("source_virtual")
        src_known = src in cache

        # Fault 1: missing/unknown/nonexistent source in the consumer config
        if not src or src == "unknown" or not src_known:
            desired = _desired_source(vid, etype)
            if desired and desired != src:
                if _bump(vid, "bad_source"):
                    logger.warning(
                        "source watchdog: %s/%s source_virtual=%r → restoring %r",
                        vid, etype, src, desired,
                    )
                    await ledfx_client.set_virtual_effect(
                        vid, etype, {"source_virtual": desired}
                    )
                    cfg["source_virtual"] = desired
                    _clear(vid, "bad_source")
            continue
        _clear(vid, "bad_source")

        # Fault 2: source exists but isn't producing frames
        src_state = cache.get(src) or {}
        src_eff = (src_state.get("effect") or {}).get("type")
        src_active = src_state.get("active", True)
        if src_eff and src_active:
            _clear(vid, "dead_source")
            continue
        if not _bump(vid, "dead_source"):
            continue
        _clear(vid, "dead_source")

        if not src_eff:
            restore = _last_seen.get(src) or _fallback_source_effect(src)
            if restore:
                r_type, r_cfg = restore
                logger.warning(
                    "source watchdog: %s (source of %s/%s) lost its effect → restoring %s",
                    src, vid, etype, r_type,
                )
                # POST, not PUT: the PUT patch path no-ops when the virtual
                # has no active effect (a DELETE also deactivates it); POST
                # sets the effect and reactivates in one call.
                await ledfx_client.post_virtual_effect(src, r_type, r_cfg)
                src_state["effect"] = {"type": r_type, "config": dict(r_cfg)}
                src_state["active"] = True
            else:
                logger.warning(
                    "source watchdog: %s (source of %s/%s) has no effect and "
                    "no known previous state to restore",
                    src, vid, etype,
                )
        elif not src_active:
            logger.warning(
                "source watchdog: %s (source of %s/%s) inactive → reactivating",
                src, vid, etype,
            )
            await ledfx_client.set_virtual_active(src, True)
            src_state["active"] = True
