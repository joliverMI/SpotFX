"""TESTING IN PROGRESS — the room-visibility surface (his ask, 2026-08-24,
his third time asking: "Make it loud when it's being tested and just add a
whole top bar it says testing in progress", after "Are my lights being
tested on?" and "weve been thru this befkre").

The question this answers is NOT "who owns the lights" — an owner
indicator showed green right through an outage he sat in. It answers "is
somebody messing with my room RIGHT NOW, and is it actually painting?"
Two halves, deliberately separate:

  THE AUTO FOLD (zero agent discipline required).  The app's own test
  paths already hold his room, and each one has silently outlived its
  purpose at least once — preview_pause (the 14-minute hold), the flare
  preview's light hold, the colour-set room preview. Every one of them
  already publishes a live active() predicate, so folding them here needs
  no new plumbing and, critically, no agent remembering to declare
  anything. If a path holds the room, the bar lights. Full stop.

  THE DECLARED TAKE (for work the app can't see).  An external agent
  driving his fixtures through fx_seam, a script, a bridge poke — none of
  that trips an auto source. POST /declare records {actor, reason,
  since_ms, expires_ms}. It is a RECORD HE CAN READ, not reporting
  discipline: nothing enforces it, and its absence never makes the bar
  claim the room is idle when an auto source says otherwise.

THREE RULES THIS MODULE EXISTS TO ENFORCE, all of them scar tissue:

1. IT CLEARS ITSELF.  A declaration carries a MANDATORY ttl (capped at
   MAX_TTL_S) and expiry is evaluated AT READ against the stored wall
   clock — the preview_pause._until deadline shape, not a flag someone
   must remember to clear and not a background task that can die. A
   banner that outlives the testing is the same defect class as the
   preview hold that outlived its preview; that one cost him 14 minutes
   of a dark room and 85 refused scene changes.

2. UNKNOWN IS A REAL ANSWER, AND IT SHOWS.  Any auto-source read that
   raises, or a store that won't parse, yields "unknown" — never a
   cheerful "no". The bar renders "unknown" as a visible, distinct state.
   Guessing "no" here is exactly how an indicator lies through an outage.

3. STORAGE IS DURABLE AND ATOMIC.  storage/spectra/test_session.json,
   tmp+os.replace (the trigger_store/room_controls discipline), so a
   SPECTRA restart mid-test cannot silently drop a live declaration and
   go quiet on him. Wall-clock (time.time()) not monotonic, precisely
   BECAUSE it must survive a restart — the one place the deadline shape
   deliberately differs from preview_pause's in-memory monotonic one.

IMPORT DISCIPLINE (the light-mode cold-start crash, AGENTS.md): every
auto-source import happens INSIDE the fold function, never at module
scope, so nothing here can be constructed or resolved at another
module's import time.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from spectra import config

logger = logging.getLogger(__name__)

# A declaration MUST carry a ttl and it MUST be bounded. An hour is long
# enough for any single live proof session (tonight's room window is ~2h,
# and a real session re-declares as it works) and short enough that a
# forgotten declaration is a nuisance measured in minutes-to-an-hour, not
# a bar that sits up until someone notices. Renewable by re-declaring.
MAX_TTL_S = 3600.0
MIN_TTL_S = 1.0

YES = "yes"
NO = "no"
UNKNOWN = "unknown"


@dataclass
class AutoSource:
    """One of the app's own test paths, folded live.

    `key` is stable and machine-readable; `label` is the phrase that goes
    in front of him on the bar. `probe` returns True while that path is
    holding/driving his room. A probe that RAISES makes the whole fold
    "unknown" — see fold_sources()."""
    key: str
    label: str
    probe: Callable[[], bool]
    detail: Callable[[], Optional[str]] = field(default=lambda: None)


def _auto_sources() -> list[AutoSource]:
    """The app's own test paths. Imported HERE, not at module scope —
    lazy-import discipline (AGENTS.md's light-mode cold-start crash)."""
    from spectra.services import flare_preview_hold, preview_pause, room_preview

    def _room_preview_detail() -> Optional[str]:
        st = room_preview.status()
        virtuals = st.get("virtuals") or []
        if not virtuals:
            return None
        return f"{len(virtuals)} virtual(s)"

    return [
        AutoSource(
            key="preview_pause",
            label="a preview is holding your room (automatic changes paused)",
            probe=preview_pause.active,
            detail=lambda: (
                f"{preview_pause.remaining_s():.0f}s left"
                if preview_pause.remaining_s() > 0 else None),
        ),
        AutoSource(
            key="flare_preview_hold",
            label="a flare preview is driving your lights",
            probe=flare_preview_hold.active,
        ),
        AutoSource(
            key="room_preview",
            label="a colour-set preview is painting your room",
            probe=room_preview.active,
            detail=_room_preview_detail,
        ),
    ]


# ── the durable declared-take record ────────────────────────────────────

def _load_raw() -> tuple[Optional[dict], bool]:
    """(record, readable). readable=False means the store exists but could
    not be parsed — the caller must report "unknown", never "no": an
    unreadable store is exactly the case where we cannot tell whether a
    declaration is live."""
    path = config.TEST_SESSION_FILE
    if not path.exists():
        return None, True
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("test_session: store unreadable at %s — reporting unknown", path)
        return None, False
    if raw is None:
        return None, True
    if not isinstance(raw, dict):
        logger.warning("test_session: store is not an object — reporting unknown")
        return None, False
    return raw, True


def _save_raw(record: Optional[dict]) -> None:
    path = config.TEST_SESSION_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def declare(actor: str, reason: str, ttl_s: float) -> dict:
    """Record (or renew) a declared take. ttl is MANDATORY at the call
    site — there is no default — and clamped to [MIN_TTL_S, MAX_TTL_S].

    Re-declaring REPLACES the record wholesale rather than extending the
    old one's since_ms: a second agent taking over is a new take, and
    showing him the first agent's start time under the second agent's
    name would be a lie about how long his room has been busy. An actor
    renewing its OWN session keeps its original since_ms, so the bar's
    "since HH:MM" doesn't reset every heartbeat."""
    actor = (actor or "").strip() or "an agent"
    reason = (reason or "").strip() or "live testing"
    ttl = max(MIN_TTL_S, min(MAX_TTL_S, float(ttl_s)))
    now = time.time()

    prior, _readable = _load_raw()
    since = now * 1000.0
    if isinstance(prior, dict) and prior.get("actor") == actor:
        prior_expires = prior.get("expires_ms")
        prior_since = prior.get("since_ms")
        # Only carry the original start forward if that session is still
        # live — a stale record from hours ago must not make a fresh take
        # claim it has been running since then.
        if (isinstance(prior_expires, (int, float))
                and isinstance(prior_since, (int, float))
                and prior_expires > now * 1000.0):
            since = float(prior_since)

    record = {
        "actor": actor,
        "reason": reason,
        "since_ms": since,
        "expires_ms": (now + ttl) * 1000.0,
        "ttl_s": ttl,
    }
    _save_raw(record)
    return record


def clear() -> bool:
    """Drop any declared take. True if one existed (expired or not)."""
    raw, _readable = _load_raw()
    had = raw is not None
    _save_raw(None)
    return had


def declared(now_ms: Optional[float] = None) -> tuple[Optional[dict], bool]:
    """(the live declaration or None, readable).

    Expiry is evaluated HERE, at read — a record past its expires_ms is
    invisible to every caller with no background task, no cleanup pass,
    and no flag anyone must remember to clear. A malformed record (no
    usable expires_ms) is treated as UNREADABLE, not as absent: we cannot
    prove nobody is testing, so we must not claim it."""
    now_ms = time.time() * 1000.0 if now_ms is None else now_ms
    raw, readable = _load_raw()
    if not readable:
        return None, False
    if raw is None:
        return None, True
    expires = raw.get("expires_ms")
    if not isinstance(expires, (int, float)):
        logger.warning("test_session: record has no usable expires_ms — reporting unknown")
        return None, False
    if float(expires) <= now_ms:
        return None, True
    return raw, True


# ── the live fold ───────────────────────────────────────────────────────

def fold_sources() -> tuple[list[dict], bool]:
    """(live auto sources, all_readable).

    A probe that raises does NOT take the others down with it — the
    remaining sources are still reported (a real hold must stay visible
    even if an unrelated module is broken) — but all_readable goes False,
    which the caller turns into "unknown" whenever nothing else already
    proves "yes". Honest about what we could not check, without discarding
    what we could."""
    out: list[dict] = []
    all_readable = True
    try:
        sources = _auto_sources()
    except Exception:
        logger.exception("test_session: could not resolve auto sources")
        return [], False
    for src in sources:
        try:
            live = bool(src.probe())
        except Exception:
            logger.exception("test_session: auto source %s failed to probe", src.key)
            all_readable = False
            continue
        if not live:
            continue
        detail: Optional[str] = None
        try:
            detail = src.detail()
        except Exception:
            # A detail string is decoration; failing to compute one must
            # never hide the fact that the source IS live.
            detail = None
        out.append({"key": src.key, "label": src.label, "detail": detail,
                    "kind": "auto"})
    return out, all_readable


def status(now_ms: Optional[float] = None) -> dict[str, Any]:
    """The whole answer, in the shape GET /api/test-session returns.

    testing:
      "yes"     at least one auto source is live, or an unexpired
                declaration exists (a declared test is a declared test —
                it shows regardless of who owns the lights).
      "unknown" nothing proves "yes" AND something could not be read (a
                broken probe, an unparseable store). Default to showing.
      "no"      everything was readable and nothing is testing. This is
                the ONLY state that hides the bar, and it is only ever
                reached on positive evidence of quiet."""
    now_ms = time.time() * 1000.0 if now_ms is None else now_ms
    sources, sources_readable = fold_sources()
    record, store_readable = declared(now_ms)

    if record is not None:
        sources = sources + [{
            "key": "declared",
            "label": f"{record.get('actor')}: {record.get('reason')}",
            "detail": None,
            "kind": "declared",
        }]

    if sources:
        testing = YES
    elif not (sources_readable and store_readable):
        testing = UNKNOWN
    else:
        testing = NO

    since_ms: Optional[float] = None
    if record is not None and isinstance(record.get("since_ms"), (int, float)):
        since_ms = float(record["since_ms"])

    return {
        "testing": testing,
        "sources": sources,
        "declared": record,
        "since_ms": since_ms,
        "readable": bool(sources_readable and store_readable),
        "now_ms": now_ms,
    }
