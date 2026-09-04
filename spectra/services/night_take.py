"""THE SELF-TAKING NIGHT — the room takes itself, comes up DARK, and is
given back on every way out.

THE ADMIRAL'S OVERRULE, and it replaces a boundary this codebase used to
call non-negotiable. `night_run.py`'s own docstring still carries the old
one because it is still true of an UNARMED deploy: a start arriving while
SPECTRA does not hold the room declines by name and touches nothing. What
changed is that he said, of having to leave his room in a special state
before bed, "no!!! i dont want to have to turn it on. why can't you" — so
sleep-triggered work must stop depending on a press. The design is the
seam's addenda 10 and 11 (/home/javi/fleet-seam/river-dj-night-run-seam.md)
and NOTHING here departs from it.

────────────────────────────────────────────────────────────────────────────
THE ARMING LEVER — one, named, and absent by default
────────────────────────────────────────────────────────────────────────────

`SPECTRA_NIGHT_SELF_TAKE=1` in the process environment. Absent (the shipped
state, and the state this PR lands in) means every line below is unreachable
and a start on a released room declines with `night_not_owned`'s own
sentence, byte for byte, exactly as it did before this file existed —
`tests/test_night_self_take.py` goes RED if that ever stops being true.

It is deliberately NOT `SPECTRA_HANDOVER_ARMED`. That latch guards the
INTERACTIVE route — a hand change he presses, between two worlds that may
both be running. This is a different act with a different consent behind it
(his spoken word, and a per-declaration `may_take_room` field to come), and
two levers for one act is how a night silently fails to run for a reason
nobody thinks to look at. One lever, one sentence when it is off.

────────────────────────────────────────────────────────────────────────────
IT ONLY EVER TAKES A **RELEASED** ROOM
────────────────────────────────────────────────────────────────────────────

`released` is the only owner state a take is attempted from. A room held by
the older SpotFX process, or mid-handover, still declines exactly as before:
displacing a live writer while he sleeps is not what he asked for, and
`released` is the one state that means "nobody is writing" — which is also
the state it is restored to on the way out.

────────────────────────────────────────────────────────────────────────────
THE QUIET TAKE — arming gate one
────────────────────────────────────────────────────────────────────────────

An ordinary take-back RESUMES HIS SHOW: it restores each virtual's stored
effect (whatever last painted the room) and switches the engine live, so the
drift conductor starts moving colour within seconds. At 1am that lights his
house, which is the exact class of failure this whole seam spent a week
killing. So the take is QUIET, and it is quiet in two independent places
because there are two independent sources of light:

  1. THE STACK COMES UP BLACK. `live_host.activate(quiet=True)` →
     `FxHost.start(blackout=True)` → `Virtuals.create_from_config(
     blackout=True)` (fx/VENDOR.md deviation #32): every virtual that would
     have restored a stored effect gets `singleColor` #000000 at brightness
     0 instead — the same write `room_mapping` uses for its own dark step.
     Same segments, same `activate=stored_active` semantics, same render
     thread, same VIRTUAL_UPDATE freshness the activation gate verifies
     against. THE FIRST FRAME IT EVER FLUSHES IS ZEROS. It is a load-time
     substitution and never a config edit, so nothing about his stored room
     changes and the next ordinary take-back restores his show as always.
  2. THE ENGINE STAYS ON PAPER. `SpectraSide(quiet=True).activate()` never
     calls `engine.go_live`, so the conductor/response/trigger engines keep
     writing to the RecordingExecutor. `fx_seam` routes on the OWNERSHIP
     RECORD plus `facade.set_host` and never on the engine's executor, so
     the night's own capture writes land perfectly while the show does not.

And a third, which is a skip rather than a mode: `run_handover(quiet=True)`
does NOT run the post-commit ambient reconcile. That call exists to land a
hold he pressed for while the room was released — and a hold is Hue bulbs
lit at ambient colour. The intent stays stored; the next ordinary take-back
applies it.

Proven at the emitted light, not at the call: `tests/test_quiet_take_dark.py`
records every frame that reaches a device's transport across a real
`fx.headless` load and asserts the maximum is zero — and asserts the SAME
rig goes non-black on the unquiet path, so it is a proof and not a
decoration.

────────────────────────────────────────────────────────────────────────────
NO DARK MUSIC. HIS SLEEPING HOUSE **IS** THE ENVELOPE.
────────────────────────────────────────────────────────────────────────────

Settled with River, 2026-09-03, and stated here so nobody helpfully adds it
back: THE SELF-TAKING FLOW FIRES NO "Dark Music" HOUSE SCENE. The envelope
belongs to the press path, where his house prepared before it started a
night; on the self-taking path he is already asleep in a dark house, and
his-routine-outranks-our-envelope is the recorded rule. So:

  * the quiet take darkens only SPECTRA'S OWN fixtures — nothing here fires
    a house scene, touches a house light, or assumes one is off, which is
    the same boundary `night_run.py` has always kept;
  * a stray house light that DOES come on is measured, not guessed at: the
    contamination witness (`spectra/services/witness.py`) indicts the
    captures it overlaps, per capture, and the re-take pass handles them;
  * River's independent morning backstop stays the outer net.

Adding a house-scene fire here would be this side reaching into his house
while he sleeps — a larger act than taking the lights, and one nobody has
asked for.

────────────────────────────────────────────────────────────────────────────
SNAPSHOT AND RESTORE ON EVERY EXIT — arming gate two
────────────────────────────────────────────────────────────────────────────

BEFORE the take, the pre-take state is written to disk
(`config.NIGHT_TAKE_FILE`, atomic tmp+replace, the shape
`flare_preview_hold`'s own restart-survival snapshot already established):
the owner it found (`released`), when, and which night. It is written FIRST,
so a crash in the take itself is still recoverable, and it is the durable
"SPECTRA is holding this room right now" record even with this process gone.

EVERY exit gives the room back, and there are four:

  complete / refused / failed  `night_run._finish`
  aborted (he stirred, or he
    touched a light)           `night_run.abort`
  ended by his morning routine `night_run.abort`
  CRASH                        `recover_orphaned_take()`, from the cold
                               start, BEFORE anything re-activates

"Give back" means: release the room to `released` — the state he left it in —
then stamp the night's terminal state and save it (River's re-dark trigger
rides that state, so it lands promptly), then announce. THE ORDER IS THE
SEMANTICS and `tests/test_night_self_take.py` asserts it: the room is his
again before he is told it is, never the other way round.

THE EXIT REPORT IS STILL READ AT THE LIGHT, and the ordering above is why it
takes a small piece of care: releasing tears the live stack down, so the
instruments (`live.host`, the driver objects) are gone afterwards. They are
CAPTURED before the release and handed to `night_exit.build`, which then
reads the fixtures back with the room ALREADY GIVEN BACK — a strictly better
question than the one it used to answer, because it now also says whether
letting go actually worked.

A NIGHT THAT DID NOT TAKE THE ROOM NEVER GIVES IT BACK. If SPECTRA already
owned the lights when the start arrived, this file does nothing at all: the
night runs exactly as it always has and his ownership state is not ours to
change on the way out. `give_back` is gated on the snapshot, not on the
armed flag and not on the state of the room.

────────────────────────────────────────────────────────────────────────────
THE ANNOUNCEMENT — both ends, timestamped, SILENT
────────────────────────────────────────────────────────────────────────────

River's refinement 1, and the Admiral's Order 22 read for a sleeping house:
he is told when the room is TAKEN and when it is GIVEN BACK — both, never
one — and neither may wake him. So there is no sound and no push: the take
and the give-back are durable records (the night's own `take` block in
`night_runs.json`, plus this module's snapshot file while it is held) and
FIELDS on the polled night status (`night_run.status_brief()["take"]`),
which is what River's HA sensors read and render into a morning he can look
at. "Spectra took the room 01:12, gave it back 02:30" is a read at
breakfast, never an alert at 01:12.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from spectra import config as scfg
from spectra.services import mapping_refusals

logger = logging.getLogger(__name__)

#: The two words the announcement uses. Small and closed on purpose — River
#: renders them, and a vocabulary that grows quietly is a contract that
#: breaks quietly.
EVENT_TAKEN = "taken"
EVENT_GIVEN_BACK = "given_back"

#: Why the room was handed back, on the give-back announcement. These are
#: LABELS for a log line, never a branch: River branches on the night's own
#: `state`/`active`, which is the frozen part of the contract.
WHY_FINISHED = "finished"
WHY_ABORTED = "aborted"
WHY_MORNING = "morning-routine"
WHY_CRASH = "crash-recovery"


def armed() -> bool:
    """THE ONE LEVER. Read at call time, never cached at import, for
    `config.night_run_token()`'s own reason: arming is a systemd
    `Environment=` edit and a restart, with no module global that could keep
    serving a stale answer."""
    return scfg.night_self_take()


# ── the pre-take snapshot ──────────────────────────────────────────────────

def _snapshot_path(path=None):
    return path or scfg.NIGHT_TAKE_FILE


def _atomic_write(path, body: dict) -> None:
    os.makedirs(os.path.dirname(str(path)) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(str(path)) or ".",
                               prefix="night-take", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(body, fh, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save_snapshot(*, run_id: str, owner_before: str, path=None) -> dict:
    """Record the pre-take state, BEFORE the take. A crash between this and
    the commit is then recoverable exactly like a crash mid-night."""
    body = {"run_id": run_id, "owner_before": owner_before,
            "taken_at": time.time(), "quiet": True}
    _atomic_write(_snapshot_path(path), body)
    return body


def load_snapshot(path=None) -> Optional[dict]:
    p = _snapshot_path(path)
    try:
        if not os.path.exists(p):
            return None
        with open(p, "r", encoding="utf-8") as fh:
            body = json.load(fh)
    except Exception:                                   # noqa: BLE001
        logger.exception("night take: unreadable snapshot %s", p)
        return None
    return body or None


def clear_snapshot(path=None) -> bool:
    p = _snapshot_path(path)
    if not os.path.exists(p):
        return False
    os.unlink(p)
    return True


def holding(path=None) -> bool:
    """Whether a self-taken room is being held RIGHT NOW, according to the
    durable record — the question a cold start asks, and the question
    `status_brief()` answers on every `engine.status()` poll.

    A STAT, NOT A PARSE, for `night_run.declared()`'s own reason: this is on
    a surface answering every few seconds, and the presence of the file IS
    the whole question there."""
    p = _snapshot_path(path)
    try:
        return os.stat(p).st_size > 0
    except OSError:
        return False


# ── the take ───────────────────────────────────────────────────────────────

@dataclass
class TakeResult:
    """What the take did, in the shape the night's record carries it."""
    took: bool = False
    owner_before: str = ""
    taken_at: float = 0.0
    detail: str = ""
    #: `mapping_refusals`' own sentence when the take could not happen. A
    #: take that refuses is a DECLINED night, never a half-held room.
    refusal: str = ""
    quiet: bool = True
    #: Which virtuals came up black rather than restoring a stored effect.
    blacked_out: list = field(default_factory=list)
    #: PARTIAL take-backs commit (the owner's 2026-08-21 ruling) and say so.
    partial: bool = False
    announce: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"self_taken": self.took, "owner_before": self.owner_before,
                "taken_at": self.taken_at, "detail": self.detail,
                "refusal": self.refusal, "quiet": self.quiet,
                "blacked_out": list(self.blacked_out),
                "partial": self.partial,
                "announce": list(self.announce)}


async def take_room(run_id: str, *, sides=None,
                    run_handover=None) -> TakeResult:
    """THE QUIET TAKE. Snapshot first, then the guarded handover in its quiet
    mode. Never raises: a take that cannot happen comes back as a refusal
    with a sentence, and the caller declines the night — which is the status
    quo, and the whole point of the arming gates.

    IT REUSES `handover.run_handover` RATHER THAN A NIGHT-ONLY PATH, so
    every gate a pressed take-back applies applies here: the readiness gate
    (a missing or unusable fx-live config refuses BEFORE the record moves),
    the activation verification, the partial-take-back tolerance coming from
    `released`, and the single-owner landing on any failure. There is no
    capability here a person pressing the ownership bar does not have —
    except that this one comes up dark."""
    from fx import light_ownership
    from spectra.services import handover as handover_mod

    sides = sides if sides is not None else \
        handover_mod.production_sides(quiet=True)
    run_handover = run_handover or handover_mod.run_handover

    owner_before = light_ownership.load().owner
    if owner_before != light_ownership.RELEASED:
        # Should be unreachable — `night_run.evaluate_start` only asks for a
        # take from a released room — but a gate that is only true by
        # argument is not a gate. It also closes the window between the
        # preflight and the start, where he may have taken the room back
        # himself.
        return TakeResult(refusal="not_released",
                          owner_before=owner_before,
                          detail=mapping_refusals.night_take_not_released(
                              owner_before))
    # THE SNAPSHOT IS WRITTEN FIRST. Nothing has moved yet, so a crash here
    # costs one stale file the cold start clears with a stated reason —
    # where a crash AFTER the commit with no snapshot on disk would leave a
    # taken room nothing knows how to give back.
    save_snapshot(run_id=run_id, owner_before=owner_before)
    try:
        await run_handover(light_ownership.SPECTRA, sides, quiet=True)
    except Exception as exc:                            # noqa: BLE001
        logger.exception("night take: the quiet take failed")
        # run_handover lands single-owner on every failure path, so the room
        # is back at `released` already. Drop the snapshot rather than leave
        # a cold start believing a room is held.
        clear_snapshot()
        return TakeResult(refusal="take_failed", owner_before=owner_before,
                          detail=mapping_refusals.night_take_failed(exc))

    from spectra.services import activation_report
    from spectra.services.live_host import live
    report = activation_report.current()
    partial = bool(report is not None and report.partial)
    taken_at = time.time()
    detail = mapping_refusals.night_took_the_room(partial=partial)
    result = TakeResult(took=True, owner_before=owner_before,
                        taken_at=taken_at, detail=detail, partial=partial,
                        blacked_out=list(getattr(live, "blacked_out", [])))
    result.announce.append({"event": EVENT_TAKEN, "at": taken_at,
                            "owner_before": owner_before, "quiet": True,
                            "partial": partial, "detail": detail})
    logger.warning("night take: SPECTRA took the room for night %s (quiet, "
                   "%d virtual(s) held black%s)", run_id,
                   len(result.blacked_out), " — PARTIAL" if partial else "")
    return result


# ── giving it back ─────────────────────────────────────────────────────────

@dataclass
class GiveBackResult:
    given_back: bool = False
    at: float = 0.0
    to: str = ""
    why: str = ""
    detail: str = ""
    verified: bool = False
    problems: list = field(default_factory=list)
    announce: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"given_back": self.given_back, "given_back_at": self.at,
                "given_back_to": self.to, "why": self.why,
                "detail": self.detail, "verified": self.verified,
                "problems": list(self.problems),
                "announce": list(self.announce)}


async def give_back(*, why: str, run_id: str = "",
                    release=None) -> GiveBackResult:
    """RESTORE THE STATE HE LEFT — release the room and drop the snapshot.

    GATED ON THE SNAPSHOT, not on the armed flag and not on the current
    owner: this hands back exactly what this seam took, and a night that ran
    on a room SPECTRA already held returns `given_back=False` having done
    nothing. Somebody else's ownership state is not ours to tidy.

    IDEMPOTENT. The abort path and the run task's own finish both call it,
    in an order nothing guarantees; the second call finds no snapshot and is
    a no-op that says so.

    Never raises. A release that cannot be verified is REPORTED
    (`verified=False` + the problems, exactly as `release_room` reports them
    to the ownership bar) and the snapshot is still dropped: the record has
    landed at `released` regardless, and a snapshot left behind would make
    the next cold start try to give back a room it no longer holds."""
    # GATED ON THE STAT, NOT THE PARSE. An unreadable snapshot still proves
    # a night took his room; refusing to hand it back because the paperwork
    # will not parse would keep the room over a JSON error. The parsed body
    # is only ever used for a run id to put in a log line.
    if not holding():
        return GiveBackResult(
            why=why, detail=mapping_refusals.NIGHT_NOTHING_TO_GIVE_BACK)
    snapshot = load_snapshot() or {}
    if release is None:
        from spectra.services import release as release_mod
        release = release_mod.release_room

    from fx import light_ownership
    owner_now = light_ownership.load().owner
    at = time.time()
    if owner_now != light_ownership.SPECTRA:
        # He took it back himself, or something else moved the record. The
        # night is over either way and there is nothing of ours left holding
        # his room — say so rather than releasing over the top of whatever
        # is there now.
        clear_snapshot()
        detail = mapping_refusals.night_gave_back_already(owner_now)
        result = GiveBackResult(given_back=False, at=at, to=owner_now,
                                why=why, detail=detail, verified=True)
        result.announce.append({"event": EVENT_GIVEN_BACK, "at": at,
                                "to": owner_now, "why": why,
                                "by_us": False, "detail": detail})
        logger.warning("night take: nothing to give back — the record "
                       "already reads %s", owner_now)
        return result

    reason = (f"night run {run_id or snapshot.get('run_id') or '?'} "
              f"giving the room back ({why})")
    verified, problems = True, []
    try:
        outcome = await release(reason)
        verified = bool(getattr(outcome, "verified", False))
        problems = list(getattr(outcome, "problems", []) or [])
        to_world = getattr(getattr(outcome, "record", None), "owner",
                           light_ownership.RELEASED)
    except Exception as exc:                            # noqa: BLE001
        logger.exception("night take: the give-back release raised")
        verified, problems = False, [f"{type(exc).__name__}: {exc}"]
        to_world = light_ownership.load().owner
    clear_snapshot()
    detail = mapping_refusals.night_gave_back_the_room(
        why, verified=verified, problems=problems)
    result = GiveBackResult(given_back=True, at=at, to=to_world, why=why,
                            detail=detail, verified=verified,
                            problems=problems)
    result.announce.append({"event": EVENT_GIVEN_BACK, "at": at,
                            "to": to_world, "why": why, "by_us": True,
                            "verified": verified, "detail": detail})
    (logger.warning if verified else logger.critical)(
        "night take: room given back to %s (%s)%s", to_world, why,
        "" if verified else f" — NOT VERIFIED: {'; '.join(problems)}")
    return result


def merge_announcement(take: dict, landed: dict) -> dict:
    """Fold a give-back's result into a night's `take` block WITHOUT losing
    the take's own announcement.

    ONE IMPLEMENTATION, because this got written wrong twice: a give-back's
    `as_dict()` carries its OWN `announce` entry, so a plain `update` puts
    it in place of the take's — one end of Order 22 silently overwriting the
    other, on a record nobody reads until breakfast. He is told when the
    room is taken AND when it is given back; the two accumulate."""
    out = dict(take or {})
    landed = dict(landed or {})
    incoming = landed.pop("announce", [])
    out.update(landed)
    out["announce"] = list(out.get("announce") or []) + list(incoming)
    return out


# ── the crash ──────────────────────────────────────────────────────────────

@dataclass
class RecoveryResult:
    recovered: bool = False
    run_id: str = ""
    held_for_s: float = 0.0
    detail: str = ""
    give_back: dict = field(default_factory=dict)
    night: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"recovered": self.recovered, "run_id": self.run_id,
                "held_for_s": round(self.held_for_s, 1),
                "detail": self.detail, "give_back": dict(self.give_back),
                "night": dict(self.night)}


async def recover_orphaned_take(*, release=None, stamp=None) -> RecoveryResult:
    """CRASH RECOVERY, and it is the one named item DJ addendum 11 owed
    River — read that addendum before changing any of it.

    Today, without this: the night's state lives in memory with a durable
    record written at every transition, so a crash mid-night leaves the DISK
    record stuck at `running`, the restarted process has no idea a night was
    ever in flight, NO terminal state is re-posted for River's re-dark
    trigger to catch, and — since the self-taking build — the ownership
    record still says SPECTRA owns a room nobody asked for. Worse than
    leaving it: `handover.resume_own_room()` would then re-activate the
    stack and resume his show, which is his house coming on at 2am.

    So this runs FIRST at cold start, before anything re-activates, and does
    the four things the addendum names:

      1. finds the orphaned night (the snapshot on disk is the proof — this
         process cannot be the one that wrote it),
      2. stamps it FAILED-BY-CRASH (`refusal="crashed"`, its own sentence;
         the STATE stays `failed`, an ending River's `active` boolean
         already covers, because inventing a state word for a frozen
         contract is how a seam breaks quietly),
      3. gives the room back and re-posts the terminal state PROMPTLY, so
         the house's own re-dark fires normally,
      4. announces the give-back, silently, on the same durable record and
         status fields every other exit uses.

    A restart that is NOT a crash — a deploy, a `systemctl restart` mid-night
    — lands here identically and correctly: the night is over either way and
    the room goes back.

    IT NEVER RE-LIGHTS ANYTHING to do this. There is no live stack yet, so
    the release's own Hue fade and WLED let-go have nothing to reach; the
    crash already stopped the writes and both fixture classes let go on their
    own (WLED's realtime timeout, Hue's stream timeout). What this restores
    is the RECORD — the thing that decides whether his room comes back up —
    and it says exactly that rather than claiming a fade it did not do."""
    # THE STAT IS THE QUESTION, for `give_back`'s own reason: a snapshot
    # that will not parse is still proof a night was holding his room, and
    # the room outranks the paperwork. An unparseable one recovers with no
    # run id — `stamp_crashed_night` says so plainly rather than inventing
    # a night — and the room still goes back.
    if not holding():
        return RecoveryResult()
    snapshot = load_snapshot() or {}

    from spectra.services import night_run

    run_id = str(snapshot.get("run_id") or "")
    taken_at = float(snapshot.get("taken_at") or 0.0)
    held_for = max(0.0, time.time() - taken_at) if taken_at else 0.0
    detail = mapping_refusals.night_crashed_mid_run(run_id, held_for)
    logger.critical("night take: ORPHANED SELF-TAKEN NIGHT found at startup "
                    "(run %s, held %.0fs) — giving the room back before "
                    "anything re-activates", run_id or "?", held_for)

    result = RecoveryResult(recovered=True, run_id=run_id,
                            held_for_s=held_for, detail=detail)
    # THE ROOM FIRST, THE PAPERWORK SECOND — the same ordering every other
    # exit keeps.
    back = await give_back(why=WHY_CRASH, run_id=run_id, release=release)
    result.give_back = back.as_dict()
    stamp = stamp or night_run.stamp_crashed_night
    try:
        result.night = stamp(run_id, detail, back) or {}
    except Exception:                                   # noqa: BLE001
        logger.exception("night take: could not stamp the orphaned night %s "
                         "— the room is back regardless", run_id)
    return result
