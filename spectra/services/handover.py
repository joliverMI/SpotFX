"""The safe two-step light handover — quiesce the current writer, VERIFY it
stopped, only then activate the other; commit only after the new writer is
verified up. Every failure lands the record at a settled single owner —
never split, never two writers (the Admiral's architecture decision).

Before either step, the READINESS GATE (order-8 correction): the to-side's
rememberable go-day preparations are checked and a missing one REFUSES the
handover before the record moves and before any quiesce — the room stays
untouched under its current owner. Rememberable preparation is a defect
class, not a procedure note: verification cannot catch an empty world
(freshness is vacuously true with zero virtuals), so the world that is
about to take the room proves its preparation first.

The ordering exists because of the merge-scout §4d failure modes:
  - Hue entertainment is a hard exclusivity: one DTLS session per bridge
    group. The new writer's multi-second handshake FAILS while the old
    session lives, so quiesce must complete first and a grace pause lets
    the bridge release the session.
  - DDP/UDP has no ownership protocol: two senders interleave frames into
    garbage. Nothing errors — only the ordering protects the room.
  - Verification is INDEPENDENT of the quiesce call's own claim (a stop
    command that lies must not let the new writer start): verify_quiesced
    consults the world's real state, and the ownership record's quiesce
    gate (mark_quiesced) is only passed on that verification.
  - The record enters HANDING_OVER (light_ownership.begin_handover) BEFORE
    quiesce begins, not after — both worlds' GATED write planes (api/
    ledfx_client._request, the LedFX-restart watchdog, fx_seam) already
    deny during the whole handover. That does not cover a resurrect that
    bypasses the gate entirely (a systemd unit dependency, an operator
    command) — closed instead by re-verifying from_side.verify_quiesced()
    immediately before commit (report gate e4i, two-writers incident
    2026-08-13): a resurrect landing in the verify→activate window aborts
    the handover rather than committing over a second writer.

Rollback discipline: on activation failure the to-side is deactivated FIRST
(releasing any partial DTLS session / DDP sender / audio device), then the
from-side is restored, then the record lands back at the from-world. If even
the restore fails, the record STILL lands at the from-world: owner=spot-
effects re-arms spot-effects' own LedFX-restart watchdog, which is the
self-heal for a stopped service (api/ledfx_client._ledfx_watchdog_tick is
ownership-gated to exactly this owner).

The production sides live here but nothing calls them until the owner's
word: the API route (spectra/api/ownership.py) refuses unless the
SPECTRA_HANDOVER_ARMED latch is set, and no code path in either app invokes
run_handover() on its own. Tests drive the orchestrator with fake sides and
the SpectraSide against the headless harness (docs/SPECTRA_HANDOVER.md is
the operator procedure).

The way back from the panic release (fx/light_ownership.RELEASED — the
one-press "let go" handle, spectra/services/release.py) is this SAME
orchestrator: run_handover(SPECTRA, ...) with from_world=="released" skips
the quiesce step (nothing was writing) and, on activation failure, skips
restoring a from_side (there is none — released was already the safe state
to fall back to). Still gated by SPECTRA_HANDOVER_ARMED and the readiness
gate, same as any other handover — coming back is a deliberate, armed
decision even though letting go is not.

THE ONE PLACE the from-released special case was missed, fixed 2026-08-21
on the owner's ruling ("one unreachable device must not be able to keep his
entire room dark"): step 2's verify/rollback. A fresh handover FROM A
RUNNING SHOW keeps its strict all-or-nothing rollback — there a working
show is genuinely at risk and there is a real from-world to land back on.
But the way back from `released` has no such fallback: abort() there lands
on DARKNESS, not safety, and aborting never saves the light that could not
be reached (it is unreachable either way) — it only darkens the ones that
DID come up. He hit exactly this six times in one night on one WLED whose
mDNS name would not resolve, and twice the morning before on two sconces
that merely answered too slowly. So coming back from released now applies
the SAME policy resume_own_room has applied to a restart since the owner's
2026-08-13 amendment: when the to-side reports a PARTIAL activation (the
stack is up and at least one expected virtual is driving, only some
devices/virtuals could not be confirmed), the take-back COMMITS, names
every skipped light LOUDLY (CRITICAL log, the ownership record's own
history note, and spectra/services/activation_report.py — which feeds the
API, the liveness endpoint, the ownership bar on every page and the
Status page, and keeps rechecking the skipped lights), and leaves every
other device driving. A HARD failure — the stack never came up, or not
one expected virtual is driving — still aborts back to released exactly
as before: committing owner=spectra over a wholly dark stack is the
order-8 defect class, not a partial room. The threshold ("at least one
expected virtual up") is deliberate: no device in this room is
load-bearing for another — the vendored render loop skips an inactive
(unresolved) device's segments per flush and a non-answering DDP target
simply drops packets, so one dark fixture can only dim the room, never
corrupt it (proven on the real pipeline in tests/test_take_back_partial.py).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Protocol

import httpx

from fx import light_ownership
from fx.host import VENDORED_DEVICE_TYPES
from spectra import config
from spectra.services import activation_report

logger = logging.getLogger(__name__)

# Merge-scout §4d: "Allow a few seconds' grace for the Hue session to release
# before the new engine activates Hue-backed virtuals."
HUE_RELEASE_GRACE_S = 5.0
SERVICE_VERIFY_TIMEOUT_S = 30.0
FRESH_VERIFY_TIMEOUT_S = 15.0

# The go-day preparation the readiness gate names in its refusal (the order-8
# correction: this step was once skipped and the room went dark for minutes).
FX_LIVE_SEED_COMMAND = ".venv/bin/python scripts/seed_spectra_fx_live.py --apply"


@dataclass
class ActivationOutcome:
    """What one verify_active() actually found, structured — the bool the
    WriterSide protocol returns is kept for every caller that only needs
    pass/fail; run_handover's from-released path needs the shape behind a
    False to tell a PARTIAL activation (tolerated, committed, reported)
    from a HARD one (still aborted)."""
    ok: bool
    stack_up: bool
    expected_ids: frozenset = field(default_factory=frozenset)
    virtual_gaps: dict = field(default_factory=dict)
    device_gaps: dict = field(default_factory=dict)
    detail: Optional[str] = None

    @property
    def up_ids(self) -> frozenset:
        return self.expected_ids - set(self.virtual_gaps)

    @property
    def partial(self) -> bool:
        """Not verified, but the stack is up and at least one expected
        virtual is driving — a room that is merely dimmer, not dark."""
        return (not self.ok) and self.stack_up and bool(self.up_ids)


class HandoverFailed(RuntimeError):
    """The handover did not land on the target. The record has already been
    landed on a single owner (the from-world) before this raises."""


class HandoverRefused(RuntimeError):
    """The handover did not BEGIN: a rememberable preparation is missing on
    the to-side. Raised before the ownership record moves and before any
    quiesce — the room is untouched and the current owner keeps writing.

    This exists because activation verification cannot catch an empty world:
    live.fresh() is vacuously true with zero active virtuals, so an unseeded
    fx-live config once sailed through the whole handover and left the room
    dark for minutes (the owner's order-8 defect). Preparation is checked
    BEFORE quiescing, not remembered."""


class WriterSide(Protocol):
    """One world's stop/start surface. quiesce/deactivate must release every
    room output (Hue DTLS session, DDP sending); activate must bring them
    back. verify_* consult real state, never the last call's return value.
    readiness_problems runs BEFORE the record moves: it reports every missing
    preparation that would leave this side unable to take the room, so the
    orchestrator can refuse with the current owner still writing."""

    name: str

    async def readiness_problems(self) -> list[str]: ...
    async def quiesce(self) -> None: ...
    async def verify_quiesced(self) -> bool: ...
    async def activate(self) -> None: ...
    async def verify_active(self) -> bool: ...
    async def deactivate(self) -> None: ...


async def _best_effort(step, label: str) -> None:
    try:
        await step()
    except Exception:
        logger.exception("handover: best-effort %s failed", label)


async def run_handover(
    to_world: str,
    sides: dict[str, WriterSide],
    *,
    grace_s: float = HUE_RELEASE_GRACE_S,
    quiet: bool = False,
) -> light_ownership.OwnershipRecord:
    """The two-step switch. Raises HandoverRefused when the to-side's go-day
    preparation is missing — BEFORE the record moves and before any quiesce,
    so the room stays untouched under its current owner. Raises
    OwnershipError if the record refuses to begin (already owner / already in
    flight) and HandoverFailed when a step fails — in which case the record
    has landed back at the from-world and the from-side was restored
    best-effort. Returns the committed record."""
    light_ownership.check_can_begin(to_world)
    problems = await sides[to_world].readiness_problems()
    if problems:
        raise HandoverRefused(
            f"handover to {to_world} refused before quiesce — the room is "
            f"untouched and the current owner keeps writing. Missing "
            f"preparation: " + "; ".join(problems))
    handover = light_ownership.begin_handover(to_world)
    # The way back from the panic release: from_world is "released", not one
    # of the two worlds — there is no side to look up, nothing was writing,
    # and (on activation failure) nothing to restore. released was already
    # the safe landing, so abort() just lands back there.
    from_released = handover.from_world == light_ownership.RELEASED
    from_side = None if from_released else sides[handover.from_world]
    to_side = sides[handover.to_world]
    from_name = light_ownership.RELEASED if from_released else from_side.name
    logger.warning("handover: %s → %s BEGUN (token=%s)",
                   from_name, to_side.name, handover.token)

    # Step 1 — quiesce the current writer and VERIFY it stopped. Vacuously
    # satisfied coming from released: nothing was writing.
    if from_released:
        await asyncio.sleep(grace_s)
    else:
        try:
            await from_side.quiesce()
            if not await from_side.verify_quiesced():
                raise HandoverFailed(
                    f"{from_side.name} still writing after quiesce — "
                    "refusing to start a second writer")
            await asyncio.sleep(grace_s)
        except Exception as exc:
            await _best_effort(from_side.activate, f"restore {from_side.name}")
            light_ownership.abort(handover.token, f"quiesce failed: {exc}")
            raise HandoverFailed(
                f"quiesce failed — landed back at {from_side.name}: {exc}"
            ) from exc

    light_ownership.mark_quiesced(handover.token)

    # Step 2 — activate the new writer and VERIFY it is driving the room.
    partial: Optional[ActivationOutcome] = None
    try:
        await to_side.activate()
        if not await to_side.verify_active():
            # Report gate (the fresh-handover 'nameless refusal' defect):
            # a refusal that cannot say why is believed-not-verified in the
            # reporting layer, the same disease this gate exists to cure.
            # Sides that can name what failed (SpectraSide) expose it here;
            # sides that can't (SpotEffectsSide — a single external service,
            # nothing to name) fall back to the generic message.
            detail = getattr(to_side, "verification_detail", lambda: None)()
            message = f"{to_side.name} activation not verified"
            if detail:
                message += f" — {detail}"
            outcome = getattr(to_side, "activation_outcome", lambda: None)()
            if from_released and outcome is not None and outcome.partial:
                # THE OWNER'S RULING (2026-08-21, module docstring): coming
                # back from released, a PARTIAL activation commits. There
                # is no working show to protect and no from-world but
                # darkness to land on; aborting here would tear down every
                # light that DID come up for the sake of one that is
                # unreachable either way. A HARD failure (stack down, or
                # not one expected virtual driving) takes the raise below
                # exactly as before. A handover FROM a running world never
                # reaches this branch — its strict rollback is unchanged.
                partial = outcome
                logger.critical(
                    "handover: PARTIAL TAKE-BACK from released — committing "
                    "anyway (%d/%d expected virtual(s) driving); every "
                    "other light stays up: %s",
                    len(outcome.up_ids), len(outcome.expected_ids), message)
            else:
                raise HandoverFailed(message)
        # Race-window close (two-writers incident, 2026-08-13 — report gate
        # e4i): re-verify the from-world is STILL quiesced immediately
        # before commit. The record staying HANDING_OVER throughout already
        # denies both worlds' GATED write planes, but a resurrect that
        # bypasses the gate entirely (a systemd unit dependency, an operator
        # `systemctl start`, anything outside this orchestrator) can still
        # land in the verify→commit gap. Catching it here means aborting
        # instead of committing a record that claims single ownership over
        # an outside world that quietly came back.
        if not from_released and not await from_side.verify_quiesced():
            logger.critical(
                "handover: %s resurrected during handover (post-activate, "
                "pre-commit) — aborting instead of committing over a "
                "second writer", from_side.name)
            raise HandoverFailed(
                f"{from_side.name} resurrected before commit — refusing "
                "to commit over a second writer")
    except Exception as exc:
        await _best_effort(to_side.deactivate,
                           f"release partial {to_side.name}")
        if not from_released:
            await _best_effort(from_side.activate, f"restore {from_side.name}")
        light_ownership.abort(handover.token, f"activation failed: {exc}")
        raise HandoverFailed(
            f"activation failed — landed back at {from_name}: {exc}"
        ) from exc

    commit_detail = None
    if partial is not None:
        # Name the skipped lights where he will see them (the report feeds
        # the API/bar/Status page/liveness) AND in the record's own durable
        # history — the one place that survives a restart. Reporting can
        # never be the reason a tolerated take-back fails to commit.
        try:
            report = activation_report.record_from_live(
                activation_report.SOURCE_TAKE_BACK,
                partial.virtual_gaps, partial.device_gaps)
            commit_detail = "PARTIAL — " + report.summary()
        except Exception:
            logger.exception("handover: activation report failed (partial "
                             "take-back still commits)")
            commit_detail = "PARTIAL — " + (partial.detail or
                                            "some lights could not be confirmed")
    record = light_ownership.commit(handover.token, detail=commit_detail)
    logger.warning("handover: %s owns the lights%s", to_side.name,
                   " (PARTIAL — see activation report)" if partial else "")
    if to_world == light_ownership.SPECTRA and quiet:
        # A QUIET TAKE APPLIES NO STORED AMBIENT INTENT. `reconcile_now`
        # exists to land a hold he pressed for while the room was released —
        # and a hold is Hue bulbs lit at ambient colour, which is the one
        # thing a take that must come up dark cannot do. Skipped, not
        # forgotten: the intent stays durable in RoomControlState exactly as
        # it was, and the next ORDINARY take-back or restart applies it.
        logger.warning("handover: QUIET take — the stored ambient intent is "
                       "not applied (a hold is light); it stays stored")
    elif to_world == light_ownership.SPECTRA:
        # THE STORED AMBIENT INTENT (spectra/services/ambient_music_gate.py's
        # "THE RELEASED ROOM"): a press while the room was released reports
        # phase "unavailable" and saves the intent — this is where it is
        # actually applied. Same shape app.py's startup lifespan already
        # uses, so a take-back and a restart land the same way rather than
        # only one of them honouring it. Best-effort and never awaited into
        # the commit's own success: the record has already moved, and a Hue
        # bridge being slow must not turn a good take-back into a failure.
        try:
            from spectra.services import ambient_music_gate
            await ambient_music_gate.reconcile_now(wait=False)
        except Exception:
            logger.exception("handover: could not start the ambient take-back "
                             "reconcile (the take-back itself is committed)")
    return record


# ── Production sides (built and proven on fakes; executed only on the
#    owner's word through the armed API route) ───────────────────────────────

def _ledfx_unit() -> str:
    return os.getenv("SPECTRA_LEDFX_UNIT", "ledfx")


async def _systemctl(*args: str) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        "systemctl", "--user", *args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    out, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
    return proc.returncode, (out or b"").decode().strip()


class SpotEffectsSide:
    """The old stack's outputs = the external LedFX service. Stopping the
    unit releases the Hue DTLS session and stops DDP sending; spot-effects'
    own write plane is already shed at the ownership gate the moment the
    record left `spot-effects`, and its LedFX-restart watchdog is dormant
    for the same reason (the §4d resurrect trap, closed in ledfx_client)."""

    name = light_ownership.SPOT_EFFECTS

    async def readiness_problems(self) -> list[str]:
        """Giving the room back requires a startable LedFX unit. A missing
        unit would only surface AFTER SPECTRA quiesced — minutes of dark
        room — so it is checked here, before anything stops."""
        try:
            rc, out = await _systemctl("cat", _ledfx_unit())
        except FileNotFoundError:
            return ["systemctl not available — cannot start the LedFX "
                    f"service unit '{_ledfx_unit()}' to restore spot-effects"]
        if rc != 0:
            return [f"LedFX service unit '{_ledfx_unit()}' not found "
                    f"(systemctl --user cat rc={rc}) — restoring spot-effects "
                    "would leave the room dark; install the unit or set "
                    "SPECTRA_LEDFX_UNIT"]
        return []

    async def quiesce(self) -> None:
        rc, out = await _systemctl("stop", _ledfx_unit())
        if rc != 0:
            raise RuntimeError(f"systemctl stop {_ledfx_unit()} rc={rc}: {out}")

    async def verify_quiesced(self) -> bool:
        rc, out = await _systemctl("is-active", _ledfx_unit())
        return out in ("inactive", "failed")

    async def activate(self) -> None:
        rc, out = await _systemctl("start", _ledfx_unit())
        if rc != 0:
            raise RuntimeError(f"systemctl start {_ledfx_unit()} rc={rc}: {out}")
        deadline = asyncio.get_event_loop().time() + SERVICE_VERIFY_TIMEOUT_S
        while asyncio.get_event_loop().time() < deadline:
            if await self.verify_active():
                return
            await asyncio.sleep(1.0)
        raise RuntimeError(
            f"{_ledfx_unit()} did not answer /api/info within "
            f"{SERVICE_VERIFY_TIMEOUT_S:.0f}s of start")

    async def verify_active(self) -> bool:
        try:
            async with httpx.AsyncClient(base_url=config.ledfx_url(),
                                         timeout=3.0) as client:
                resp = await client.get("/api/info")
            return resp.status_code == 200
        except Exception:
            return False

    async def deactivate(self) -> None:
        await self.quiesce()


class SpectraSide:
    """The new stack: the live device layer + audio hub (live_host) with the
    engine pointed at the facade. Activation mints its grant — mintable only
    past the record's quiesce gate — so even a miscalled activate() cannot
    start while the old writer holds the room."""

    name = light_ownership.SPECTRA

    def __init__(self, config_dir: Optional[str] = None,
                 open_audio: bool = True, audio_source_factory=None,
                 quiet: bool = False):
        self.config_dir = config_dir or str(config.FX_LIVE_CONFIG_DIR)
        self.open_audio = open_audio
        self.audio_source_factory = audio_source_factory
        #: THE QUIET TAKE (spectra/services/night_take.py). Two things, and
        #: they are the two things that put light in the room on an ordinary
        #: take-back: the stack comes up driving BLACK instead of each
        #: virtual's stored effect (live_host.activate(quiet=True)), and the
        #: ENGINE IS NOT SWITCHED LIVE — the drift conductor, the response
        #: engine and the trigger engine keep writing to the recording
        #: executor, so the show runs on paper and not on his fixtures.
        #: Everything a capture run needs still works: `fx_seam` routes on
        #: the OWNERSHIP RECORD plus `facade.set_host`, never on the engine's
        #: executor, so the room is fully writable and completely dark.
        self.quiet = bool(quiet)
        self._last_failure_detail: Optional[str] = None
        self._last_outcome: Optional[ActivationOutcome] = None

    async def readiness_problems(self) -> list[str]:
        """The order-8 gate: SPECTRA cannot take the room on a missing,
        unreadable, or empty fx-live config — that world activates
        'successfully' with zero virtuals (freshness is vacuously true) and
        the room goes dark. Named preparation, checked, refused pre-quiesce."""
        path = Path(self.config_dir) / "config.json"
        remedy = f"run: {FX_LIVE_SEED_COMMAND}"
        if not path.exists():
            return [f"SPECTRA fx-live config missing ({path}) — the go-day "
                    f"seeding step has not been run; {remedy}"]
        try:
            raw = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            return [f"SPECTRA fx-live config unreadable ({path}: {exc}) — "
                    f"re-seed it; {remedy}"]
        devices = raw.get("devices") or []
        virtuals = raw.get("virtuals") or []
        vendored_ids = {d.get("id") for d in devices
                        if d.get("type") in VENDORED_DEVICE_TYPES}
        usable = [v for v in virtuals
                  if any(seg and seg[0] in vendored_ids
                         for seg in (v.get("segments") or []))]
        if not usable:
            return [f"SPECTRA fx-live config has no usable virtuals "
                    f"({len(devices)} devices, {len(virtuals)} virtuals, 0 "
                    f"backed by a vendored driver type "
                    f"{sorted(VENDORED_DEVICE_TYPES)}) — the room would come "
                    f"up empty-handed; {remedy}"]
        return []

    async def activate(self) -> None:
        from fx import facade
        from spectra.services import engine
        from spectra.services.fx_executor import FacadeExecutor
        from spectra.services.live_host import live

        # A new activation attempt starts from a clean report — whatever
        # the previous stack left dark is no longer a fact about this one.
        activation_report.clear()
        grant = light_ownership.mint_activation_grant(light_ownership.SPECTRA)
        await live.activate(grant, self.config_dir,
                            open_audio=self.open_audio,
                            audio_source_factory=self.audio_source_factory,
                            quiet=self.quiet)
        facade.set_host(live.host)
        if self.quiet:
            # THE SHOW STAYS ON PAPER. `engine.go_live` is what points the
            # drift conductor and the response engine at real lights; a
            # quiet take deliberately never calls it, so the engine keeps
            # its RecordingExecutor and nothing it decides reaches a
            # fixture. `fx_seam` is unaffected (it routes on the ownership
            # record + facade host), which is why the night's own capture
            # writes still land.
            logger.warning("handover: QUIET activation — the stack is up and "
                           "black; the engine stays dark (executor unchanged)")
        else:
            engine.go_live(FacadeExecutor(), grant)
        # The crystal lazy-activation class (report gate e3, folded in as
        # first-class alongside the reconciler, 2026-08-13): give EVERY
        # config-declared virtual its best chance to come up (a Hue DTLS
        # handshake retries for several seconds) before returning. Does NOT
        # raise on what's still missing after the wait — verify_active()
        # below is the single source of truth for "fully up", and callers
        # act on a gap differently: run_handover's activation-failure
        # handling rolls back to the known-good from-world on ANY gap when
        # there IS a working fallback to land on (a handover from a running
        # show); coming back from `released` (no from-world but darkness)
        # and resume_own_room (no from-world at all) instead report gaps
        # loudly and keep whatever DID come up rather than darkening working
        # devices behind one broken link (owner amendment, 2026-08-13: "the
        # crystal must never need a human again"; owner ruling 2026-08-21:
        # "one unreachable device must not be able to keep his entire room
        # dark" — a stranding teardown on either path makes that worse, not
        # better).
        await live.wait_fully_active(timeout_s=FRESH_VERIFY_TIMEOUT_S)

    async def verify_active(self) -> bool:
        """Bool return preserved for the WriterSide protocol and existing
        callers/tests; the named WHY behind a False is captured on the side
        in verification_detail() (report gate: the fresh-handover
        'nameless refusal' defect — resume_own_room already named its gaps
        via activation_gaps()/CRITICAL logging + the liveness endpoint;
        this path had none of that until now), and the full structured
        finding in activation_outcome() — what run_handover's from-released
        path reads to tell a partial activation from a hard one."""
        from spectra.services.live_host import live

        expected = frozenset(live.expected_active_ids)
        if not live.active:
            gaps = live.activation_gaps()
            detail = live.describe_gaps(gaps)
            logger.critical("spectra activation not verified — %s", detail)
            self._last_failure_detail = detail
            self._last_outcome = ActivationOutcome(
                ok=False, stack_up=False, expected_ids=expected,
                virtual_gaps=gaps, detail=detail)
            return False
        gaps = live.activation_gaps()
        if gaps or not live.fresh():
            detail = live.describe_gaps(gaps)
            logger.critical("spectra activation not verified — %s", detail)
            self._last_failure_detail = detail
            # activation_gaps() already names every EXPECTED virtual that
            # is not flushing; `fresh()` alone failing means an active
            # virtual OUTSIDE the expected set went stale — reported as
            # its own "*" entry so the outcome never claims a clean
            # virtual roster it did not check.
            reported = dict(gaps) if gaps else {
                "*": "one or more active virtuals stopped flushing frames"}
            self._last_outcome = ActivationOutcome(
                ok=False, stack_up=True, expected_ids=expected,
                virtual_gaps=reported, detail=detail)
            return False
        device_gaps = await live.device_gaps()
        if device_gaps:
            detail = live.describe_gaps({}, device_gaps)
            logger.critical("spectra activation not verified — %s", detail)
            self._last_failure_detail = detail
            self._last_outcome = ActivationOutcome(
                ok=False, stack_up=True, expected_ids=expected,
                device_gaps=device_gaps, detail=detail)
            return False
        self._last_failure_detail = None
        self._last_outcome = ActivationOutcome(
            ok=True, stack_up=True, expected_ids=expected)
        return True

    def verification_detail(self) -> Optional[str]:
        """Named detail behind the most recent verify_active() False — every
        light that could not rise. None once a verification has passed (or
        before any has run)."""
        return self._last_failure_detail

    def activation_outcome(self) -> Optional[ActivationOutcome]:
        """The structured finding behind the most recent verify_active():
        stack up or not, which expected virtuals are driving, which are
        not, which devices could not be confirmed. None before any
        verification has run."""
        return self._last_outcome

    async def deactivate(self) -> None:
        from fx import facade
        from spectra.services import engine
        from spectra.services.live_host import live

        engine.go_dark()
        facade.set_host(None)
        await live.deactivate()
        # A torn-down stack keeps no opinion about lights it no longer
        # drives (the report self-gates on live.active too — belt and braces).
        activation_report.clear()

    async def quiesce(self) -> None:
        await self.deactivate()

    async def verify_quiesced(self) -> bool:
        from spectra.services.live_host import live
        return not live.active


def production_sides(*, quiet: bool = False) -> dict[str, WriterSide]:
    """The two real writer sides. `quiet` builds the SPECTRA side in its
    quiet mode — the self-taking night's take, and nothing else; every other
    caller gets exactly what it always got."""
    return {
        light_ownership.SPOT_EFFECTS: SpotEffectsSide(),
        light_ownership.SPECTRA: SpectraSide(quiet=quiet),
    }


async def resume_own_room(side: Optional[SpectraSide] = None) -> bool:
    """Process start while the record already says spectra owns — a restart
    of spectra.service mid-reign. Without this the room stayed dark until a
    manual handover cycle (the operational gap proven twice on 2026-08-13);
    now the stack reactivates itself through the SAME guarded path the
    handover uses: SpectraSide.activate() mints its grant (mintable because
    owner=spectra outright — no record transition happens, she already
    owns), brings up the host, and gives every config-declared virtual its
    best chance to come up (live.wait_fully_active — the crystal lazy-
    activation fix) before this returns True.

    A HARD failure — activate() itself raising (grant refused, host.start()
    erroring, no devices at all) — lands exactly where a crashed activation
    always landed: dark-but-owned, record untouched, liveness 503, nothing
    torn half-up. But a SOFT failure — the stack came up and SOME devices
    are painting, one Hue zone or one WLED in a mapper chain isn't (report
    "crystal lazy-activation", owner amendment 2026-08-13: verified
    per-device, never assumed) — must NOT be treated the same way: unlike a
    fresh handover (which has a known-good from-world to fall back to and
    so rolls back on ANY gap via verify_active()), a resume has nothing to
    fall back to but darkness. Tearing down everything over one broken
    link would strand the working majority for the sake of the one
    straggler — worse than the original darkfault, and exactly the
    "needs a human" outcome the owner ruled out. So: report every gap
    LOUDLY (CRITICAL + the liveness endpoint's activation_gaps, already
    wired to unhealthy, + the activation report every surface reads) and
    leave every other device driving. Since 2026-08-21 the way back from
    `released` applies this same policy (module docstring) — "a fresh
    handover … rolls back on ANY gap" above is now true only of a handover
    FROM A RUNNING WORLD, which still has a working show to fall back to.

    Not gated on the SPECTRA_HANDOVER_ARMED latch: the latch guards
    CHANGING hands; the record saying spectra owns is the owner's standing
    word.

    A released room (fx.light_ownership.RELEASED — the panic handle) takes
    the SAME early return as spot-effects owning: this is a plain
    owner != SPECTRA check, so a restart during a released room never
    re-lights it. The owner's press stands across restarts; only the
    guarded handover un-releases the room."""
    from spectra.services.live_host import live

    record = light_ownership.load()
    if record.owner != light_ownership.SPECTRA:
        return False
    side = side or SpectraSide()
    problems = await side.readiness_problems()
    if problems:
        # The order-8 gate applies here too: with no usable fx-live config,
        # activation "succeeds" with zero virtuals (freshness vacuously true)
        # and liveness would claim live over a dark room. Refuse the same way
        # the handover does — dark-but-owned, record untouched, liveness 503.
        for problem in problems:
            logger.error("resume: readiness gate refuses — %s", problem)
        return False
    logger.warning("resume: record says spectra owns — reactivating the "
                   "live stack")
    try:
        await side.activate()
    except Exception:
        logger.exception("resume: activation failed — staying dark-but-owned "
                         "(record untouched; liveness stays 503)")
        await _best_effort(side.deactivate, "release partial resume")
        return False
    gaps = live.activation_gaps()
    device_gaps = await live.device_gaps()
    # The same visible report the tolerant take-back keeps (spectra/
    # services/activation_report.py) — a partial resume used to be a
    # CRITICAL line and nothing he could see in the app.
    activation_report.record_from_live(
        activation_report.SOURCE_RESUME, gaps, device_gaps)
    if gaps or device_gaps:
        logger.critical(
            "resume: PARTIAL ACTIVATION — %d virtual(s) never came up "
            "(%s), %d device(s) unconfirmed (%s); every other device stays "
            "up — see /spectra/api/liveness activation_gaps + activation, "
            "/spectra/api/ownership activation",
            len(gaps), gaps, len(device_gaps), device_gaps)
    else:
        logger.warning(
            "resume: live stack reactivated — spectra drives the whole room")
    return True
