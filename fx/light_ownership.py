"""Light ownership — the ONE record of who owns the room (SpotFX-authored).

The Admiral's architecture decision, binding: one-at-a-time ownership —
spot-effects owns the lights or SPECTRA does, NEVER both; the switch is an
explicit safe handover, never two writers. This module is that record and
its state machine, in the shared library so both worlds (and the future
standalone SPECTRA process) read the SAME implementation. stdlib only.

The record (storage/spectra/ownership.json) has ONE `owner` field — it
cannot express two owners. Its values:

    spot-effects   the shipped default: the external LedFX service streams
                   to the devices; spot-effects' write plane is open;
                   nothing in SPECTRA touches a device or audio input.
    spectra        SPECTRA's in-process fx/ pipeline drives the devices;
                   spot-effects' write plane is shed and its LedFX-restart
                   watchdog is dormant (the merge-scout §4d resurrect trap).
    handing-over   the two-step switch is in flight: NEITHER world's write
                   path is granted. The `handover` block carries from/to,
                   the current step, and a token only the orchestrator holds.

Exactly-one-owner is enforced by construction, not convention:
  - writes_allowed(world) is consulted by both worlds' write choke points
    (api/ledfx_client._request; spectra/services/fx_seam); handing-over
    grants neither.
  - Device-layer activation (FxHost with non-dummy devices) requires an
    ActivationGrant minted here, mintable only when the record grants
    SPECTRA the room — and re-validated against the live record at use time.
  - Every transition validates the expected current state under an exclusive
    file lock (two orchestrators cannot interleave), and the handover steps
    are ordered: activation cannot be granted until the quiesce step is
    marked complete, so the new writer cannot start before the old one
    stopped.

A missing or unreadable record means the shipped default: spot-effects owns.
That asymmetry is deliberate — spot-effects' gate fails OPEN to today's
behavior, SPECTRA's gates fail CLOSED (they need an affirmative grant).

Failure landings: abort() lands the record back at the from-world from any
handover step. A handover orphaned by a crash is landed by
recover_stale_handover() (both worlds call it at startup; age-gated so a
live orchestrator in the other process is never fought).
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
OWNERSHIP_FILE = _REPO_ROOT / "storage" / "spectra" / "ownership.json"

SPOT_EFFECTS = "spot-effects"
SPECTRA = "spectra"
HANDING_OVER = "handing-over"
WORLDS = (SPOT_EFFECTS, SPECTRA)

STEP_QUIESCING = "quiescing"
STEP_ACTIVATING = "activating"
STEPS = (STEP_QUIESCING, STEP_ACTIVATING)

# Any real handover lands in well under this (service stop/start in seconds,
# the Hue DTLS handshake budget is 6 s). Past it, a handing-over record is a
# crash orphan, not an in-flight switch.
HANDOVER_STALE_S = 120.0

HISTORY_LIMIT = 50


class OwnershipError(RuntimeError):
    """A transition or grant the record refuses. Callers land single-owner."""


@dataclass
class Handover:
    from_world: str
    to_world: str
    step: str
    started_at: float
    token: str

    def to_json(self) -> dict:
        return {"from": self.from_world, "to": self.to_world,
                "step": self.step, "started_at": self.started_at,
                "token": self.token}

    @classmethod
    def from_json(cls, data: dict) -> "Handover":
        return cls(from_world=data["from"], to_world=data["to"],
                   step=data["step"], started_at=float(data["started_at"]),
                   token=data["token"])


@dataclass
class OwnershipRecord:
    owner: str = SPOT_EFFECTS
    handover: Optional[Handover] = None
    updated_at: float = 0.0
    history: list[dict] = field(default_factory=list)

    def to_json(self) -> dict:
        return {"owner": self.owner,
                "handover": self.handover.to_json() if self.handover else None,
                "updated_at": self.updated_at,
                "history": self.history}


def _default_record() -> OwnershipRecord:
    return OwnershipRecord()


def load() -> OwnershipRecord:
    """Read the record; a missing or unreadable file is the shipped default
    (spot-effects owns). Never raises — the write gates must always get an
    answer, and the safe answer is the default owner."""
    try:
        data = json.loads(OWNERSHIP_FILE.read_text())
        owner = data.get("owner")
        handover = data.get("handover")
        if owner == HANDING_OVER:
            if not handover:
                raise ValueError("handing-over with no handover block")
            return OwnershipRecord(
                owner=owner, handover=Handover.from_json(handover),
                updated_at=float(data.get("updated_at", 0.0)),
                history=list(data.get("history", [])))
        if owner not in WORLDS:
            raise ValueError(f"unknown owner {owner!r}")
        return OwnershipRecord(
            owner=owner, handover=None,
            updated_at=float(data.get("updated_at", 0.0)),
            history=list(data.get("history", [])))
    except FileNotFoundError:
        return _default_record()
    except Exception as exc:
        logger.error("light ownership: unreadable record %s (%r) — treating "
                     "as the shipped default (%s owns)",
                     OWNERSHIP_FILE, exc, SPOT_EFFECTS)
        return _default_record()


def _save(record: OwnershipRecord) -> None:
    record.updated_at = time.time()
    record.history = record.history[-HISTORY_LIMIT:]
    OWNERSHIP_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = OWNERSHIP_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record.to_json(), indent=2))
    os.replace(tmp, OWNERSHIP_FILE)


def _note(record: OwnershipRecord, event: str, detail: str) -> None:
    record.history.append({"at": time.time(), "event": event, "detail": detail})
    logger.warning("light ownership: %s — %s", event, detail)


class _Locked:
    """Exclusive cross-process lock for read-modify-write transitions. Plain
    reads don't lock (atomic replace keeps them consistent)."""

    def __enter__(self):
        OWNERSHIP_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(OWNERSHIP_FILE.with_suffix(".lock"), "w")
        fcntl.flock(self._fh, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        fcntl.flock(self._fh, fcntl.LOCK_UN)
        self._fh.close()
        return False


def _transition(mutate: Callable[[OwnershipRecord], None]) -> OwnershipRecord:
    with _Locked():
        record = load()
        mutate(record)          # raises OwnershipError to refuse; nothing saved
        _save(record)
        return record


# ── Write grants (the never-two-writers predicates) ──────────────────────────

def writes_allowed(world: str) -> bool:
    """May `world`'s light write plane run right now? handing-over grants
    NEITHER world — during the switch nobody writes; the orchestrator's
    device activation runs under its own step-gated grant instead."""
    if world not in WORLDS:
        raise ValueError(f"unknown world {world!r}")
    return load().owner == world


@dataclass(frozen=True)
class ActivationGrant:
    """Proof that the record granted `world` the device layer. Minted only by
    mint_activation_grant(); consumers re-validate against the LIVE record
    (grant_valid) at use time, so a stale grant dies with the state that
    minted it."""
    world: str
    token: str


def _activation_permitted(record: OwnershipRecord, world: str) -> bool:
    if record.owner == world:
        return True
    return (record.owner == HANDING_OVER
            and record.handover is not None
            and record.handover.to_world == world
            and record.handover.step == STEP_ACTIVATING)


def mint_activation_grant(world: str) -> ActivationGrant:
    """Grant `world` the device layer: only when it owns the room outright,
    or a handover TO it has passed the quiesce gate (step=activating — the
    old writer is verified stopped). Anything else refuses."""
    if world not in WORLDS:
        raise ValueError(f"unknown world {world!r}")
    record = load()
    if not _activation_permitted(record, world):
        raise OwnershipError(
            f"device activation refused for {world!r}: owner={record.owner}"
            + (f" step={record.handover.step}" if record.handover else ""))
    token = (record.handover.token if record.handover
             else secrets.token_hex(8))
    return ActivationGrant(world=world, token=token)


def grant_valid(grant: Optional[ActivationGrant], world: str) -> bool:
    """Is this grant good NOW? Re-reads the record: a grant minted under a
    state that has since changed is dead."""
    if grant is None or grant.world != world:
        return False
    record = load()
    if not _activation_permitted(record, world):
        return False
    if record.handover is not None and grant.token != record.handover.token:
        return False
    return True


def require_grant(grant: Optional[ActivationGrant], world: str,
                  detail: str = "") -> None:
    if not grant_valid(grant, world):
        record = load()
        raise OwnershipError(
            f"live device layer refused for {world!r}"
            + (f" ({detail})" if detail else "")
            + f": owner={record.owner}, grant={'stale/absent' if grant else 'absent'}")


# ── The handover state machine ───────────────────────────────────────────────

def check_can_begin(to_world: str) -> None:
    """Pure read-only preflight of begin_handover's refusal conditions, so
    orchestrator gates that must run BEFORE the record moves (the readiness
    gate) don't shadow an already-owner / in-flight refusal with their own.
    begin_handover still re-validates atomically under its transition."""
    if to_world not in WORLDS:
        raise ValueError(f"unknown world {to_world!r}")
    record = load()
    if record.owner == HANDING_OVER:
        raise OwnershipError("a handover is already in flight")
    if record.owner == to_world:
        raise OwnershipError(f"{to_world} already owns the lights")


def begin_handover(to_world: str) -> Handover:
    """owner=<from> → handing-over(step=quiescing). Refuses if `to_world`
    already owns or a handover is in flight — the two-step always starts
    from a settled single owner."""
    if to_world not in WORLDS:
        raise ValueError(f"unknown world {to_world!r}")
    box: list[Handover] = []

    def mutate(record: OwnershipRecord) -> None:
        if record.owner == HANDING_OVER:
            raise OwnershipError("a handover is already in flight")
        if record.owner == to_world:
            raise OwnershipError(f"{to_world} already owns the lights")
        handover = Handover(from_world=record.owner, to_world=to_world,
                            step=STEP_QUIESCING, started_at=time.time(),
                            token=secrets.token_hex(8))
        _note(record, "handover_begin",
              f"{handover.from_world} → {handover.to_world} (quiescing)")
        record.owner = HANDING_OVER
        record.handover = handover
        box.append(handover)

    _transition(mutate)
    return box[0]


def _require_in_flight(record: OwnershipRecord, token: str) -> Handover:
    if record.owner != HANDING_OVER or record.handover is None:
        raise OwnershipError(f"no handover in flight (owner={record.owner})")
    if record.handover.token != token:
        raise OwnershipError("handover token mismatch — not your handover")
    return record.handover


def mark_quiesced(token: str) -> None:
    """step quiescing → activating: the orchestrator VERIFIED the old writer
    stopped (independently of the quiesce call's own claim). Only past this
    gate can the to-world mint its device-layer grant."""

    def mutate(record: OwnershipRecord) -> None:
        handover = _require_in_flight(record, token)
        if handover.step != STEP_QUIESCING:
            raise OwnershipError(f"cannot mark quiesced from step {handover.step}")
        handover.step = STEP_ACTIVATING
        _note(record, "handover_quiesced",
              f"{handover.from_world} outputs verified stopped; "
              f"{handover.to_world} may activate")

    _transition(mutate)


def commit(token: str) -> OwnershipRecord:
    """handing-over(activating) → owner=<to>. The new writer is up and
    verified; the room changes hands."""

    def mutate(record: OwnershipRecord) -> None:
        handover = _require_in_flight(record, token)
        if handover.step != STEP_ACTIVATING:
            raise OwnershipError(
                f"cannot commit from step {handover.step} — the quiesce gate "
                "was never passed")
        _note(record, "handover_commit",
              f"{handover.to_world} owns the lights "
              f"(from {handover.from_world})")
        record.owner = handover.to_world
        record.handover = None

    return _transition(mutate)


def abort(token: str, reason: str) -> OwnershipRecord:
    """Any handover step → owner=<from>: the failure landing. The caller has
    already torn down whatever the to-world partially activated; the record
    lands settled on the old owner — a safe single-owner state, never split."""

    def mutate(record: OwnershipRecord) -> None:
        handover = _require_in_flight(record, token)
        _note(record, "handover_abort",
              f"landed back at {handover.from_world} from step "
              f"{handover.step}: {reason}")
        record.owner = handover.from_world
        record.handover = None

    return _transition(mutate)


def recover_stale_handover(max_age_s: float = HANDOVER_STALE_S) -> bool:
    """Land a crash-orphaned handover back at its from-world. Age-gated:
    a young handing-over record may be a live orchestrator in the other
    process — never fight it. Both worlds call this at startup; while the
    orphan persists both write gates refuse (dark but safe), so landing it
    restores the old owner's room. Returns True if a landing happened."""
    with _Locked():
        record = load()
        if record.owner != HANDING_OVER or record.handover is None:
            return False
        age = time.time() - record.handover.started_at
        if age < max_age_s:
            return False
        logger.critical(
            "light ownership: stale handover (%s → %s, step=%s, %.0fs old) — "
            "landing back at %s", record.handover.from_world,
            record.handover.to_world, record.handover.step, age,
            record.handover.from_world)
        _note(record, "handover_recovered",
              f"stale ({age:.0f}s) at step {record.handover.step}; landed at "
              f"{record.handover.from_world}")
        record.owner = record.handover.from_world
        record.handover = None
        _save(record)
        return True
