"""The safe two-step light handover — quiesce the current writer, VERIFY it
stopped, only then activate the other; commit only after the new writer is
verified up. Every failure lands the record at a settled single owner —
never split, never two writers (the Admiral's architecture decision).

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
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional, Protocol

import httpx

from fx import light_ownership
from spectra import config

logger = logging.getLogger(__name__)

# Merge-scout §4d: "Allow a few seconds' grace for the Hue session to release
# before the new engine activates Hue-backed virtuals."
HUE_RELEASE_GRACE_S = 5.0
SERVICE_VERIFY_TIMEOUT_S = 30.0
FRESH_VERIFY_TIMEOUT_S = 15.0


class HandoverFailed(RuntimeError):
    """The handover did not land on the target. The record has already been
    landed on a single owner (the from-world) before this raises."""


class WriterSide(Protocol):
    """One world's stop/start surface. quiesce/deactivate must release every
    room output (Hue DTLS session, DDP sending); activate must bring them
    back. verify_* consult real state, never the last call's return value."""

    name: str

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
) -> light_ownership.OwnershipRecord:
    """The two-step switch. Raises OwnershipError if the record refuses to
    begin (already owner / already in flight) and HandoverFailed when a step
    fails — in which case the record has landed back at the from-world and
    the from-side was restored best-effort. Returns the committed record."""
    handover = light_ownership.begin_handover(to_world)
    from_side = sides[handover.from_world]
    to_side = sides[handover.to_world]
    logger.warning("handover: %s → %s BEGUN (token=%s)",
                   from_side.name, to_side.name, handover.token)

    # Step 1 — quiesce the current writer and VERIFY it stopped.
    try:
        await from_side.quiesce()
        if not await from_side.verify_quiesced():
            raise HandoverFailed(
                f"{from_side.name} still writing after quiesce — refusing to "
                "start a second writer")
        await asyncio.sleep(grace_s)
    except Exception as exc:
        await _best_effort(from_side.activate, f"restore {from_side.name}")
        light_ownership.abort(handover.token, f"quiesce failed: {exc}")
        raise HandoverFailed(
            f"quiesce failed — landed back at {from_side.name}: {exc}"
        ) from exc

    light_ownership.mark_quiesced(handover.token)

    # Step 2 — activate the new writer and VERIFY it is driving the room.
    try:
        await to_side.activate()
        if not await to_side.verify_active():
            raise HandoverFailed(f"{to_side.name} activation not verified")
    except Exception as exc:
        await _best_effort(to_side.deactivate,
                           f"release partial {to_side.name}")
        await _best_effort(from_side.activate, f"restore {from_side.name}")
        light_ownership.abort(handover.token, f"activation failed: {exc}")
        raise HandoverFailed(
            f"activation failed — landed back at {from_side.name}: {exc}"
        ) from exc

    record = light_ownership.commit(handover.token)
    logger.warning("handover: %s owns the lights", to_side.name)
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
                 open_audio: bool = True, audio_source_factory=None):
        self.config_dir = config_dir or str(config.FX_LIVE_CONFIG_DIR)
        self.open_audio = open_audio
        self.audio_source_factory = audio_source_factory

    async def activate(self) -> None:
        from fx import facade
        from spectra.services import engine
        from spectra.services.fx_executor import FacadeExecutor
        from spectra.services.live_host import live

        grant = light_ownership.mint_activation_grant(light_ownership.SPECTRA)
        await live.activate(grant, self.config_dir,
                            open_audio=self.open_audio,
                            audio_source_factory=self.audio_source_factory)
        facade.set_host(live.host)
        engine.go_live(FacadeExecutor(), grant)
        if not await live.wait_fresh(timeout_s=FRESH_VERIFY_TIMEOUT_S):
            raise RuntimeError(
                "live stack up but active virtuals are not flushing frames "
                f"within {FRESH_VERIFY_TIMEOUT_S:.0f}s")

    async def verify_active(self) -> bool:
        from spectra.services.live_host import live
        return live.active and live.fresh()

    async def deactivate(self) -> None:
        from fx import facade
        from spectra.services import engine
        from spectra.services.live_host import live

        engine.go_dark()
        facade.set_host(None)
        await live.deactivate()

    async def quiesce(self) -> None:
        await self.deactivate()

    async def verify_quiesced(self) -> bool:
        from spectra.services.live_host import live
        return not live.active


def production_sides() -> dict[str, WriterSide]:
    return {
        light_ownership.SPOT_EFFECTS: SpotEffectsSide(),
        light_ownership.SPECTRA: SpectraSide(),
    }
