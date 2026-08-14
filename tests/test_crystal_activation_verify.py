"""The crystal lazy-activation class — offline proof (report gate e3, folded
in as first-class alongside the reconciler by owner order, 2026-08-13/14).

Same discipline as test_handover.py: no live handover, no real device, no
audio hardware (silence_audio only; open_audio=False throughout).

The bug this closes: fx.virtuals.Virtuals.create_from_config only ever LOGS
a warning when a virtual's segments/effect fail to restore (missing device,
schema drift) — it never raises, and nothing upstream compared "what the
persisted config declared" against "what actually came up active." A
virtual excluded from active_virtual_ids() is invisible to the OLD
freshness check (vacuously true), so a handover activate or resume could
report success while part of a mapper chain stayed dark
(data/spectra-crystal-darkfault/, 2026-08-13).

The proofs:
  1. _config_expected_active_ids: pure function over a raw config dict.
  2. A real FxHost, on a config with a working virtual AND a "chain-tail"
     virtual whose segment references a device that was never loaded (the
     chain's missing link) — the vendored create_from_config path silently
     skips it — activation_gaps() names the tail, wait_fully_active() never
     reports success, and SpectraSide.activate() itself does NOT raise (it
     gives the chain its best chance, then returns): verify_active() is the
     single source of truth for "fully up", and it's the CALLER
     (run_handover, via its "activation not verified" HandoverFailed path)
     that turns a gap into a loud failure for a fresh handover. A same-owner
     resume (resume_own_room, tests/test_handover.py) instead reports the
     gap and keeps the rest running — see that module's docstring for why
     the two callers diverge on purpose.
  3. The full chain, when every link DOES load, reports zero gaps —
     activation isn't just pickier, it still succeeds honestly.
  4. The liveness endpoint's `healthy` bit and new `activation_gaps` field
     reflect the same class continuously, not just at handover time.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import headless, light_ownership as lo

_ORIGINAL_OWNERSHIP_FILE = lo.OWNERSHIP_FILE


def _run(coro):
    return asyncio.run(coro)


def _own_file(tmp_path) -> None:
    lo.OWNERSHIP_FILE = tmp_path / "ownership.json"


@pytest.fixture(autouse=True)
def _restore_ownership_file():
    yield
    lo.OWNERSHIP_FILE = _ORIGINAL_OWNERSHIP_FILE


_EFFECT = {"type": "singleColor", "config": {"color": "#000080"}}


def _write_chain_config(config_dir: str, *, break_tail: bool) -> None:
    """A two-link "mapper chain": chain-mapper (a real dummy device) and
    chain-tail, whose segment addresses a device id that was never loaded
    (break_tail=True) — the exact shape create_from_config swallows as a
    warning: 'has no device segments; skipping effect restore'."""
    from fx.consts import CONFIGURATION_VERSION

    os.makedirs(config_dir, exist_ok=True)
    devices = [
        {"id": "chain-real", "type": "dummy",
         "config": {"name": "chain-real", "pixel_count": 16}},
    ]
    if not break_tail:
        devices.append(
            {"id": "chain-tail-device", "type": "dummy",
             "config": {"name": "chain-tail-device", "pixel_count": 16}})
    tail_device_id = "chain-missing-device" if break_tail else "chain-tail-device"
    config = {
        "configuration_version": CONFIGURATION_VERSION,
        "devices": devices,
        "virtuals": [
            {
                "id": "chain-mapper",
                "is_device": "chain-mapper",
                "auto_generated": False,
                "config": {"name": "chain-mapper", "mapping": "span"},
                "segments": [["chain-real", 0, 15, False]],
                "effect": _EFFECT,
            },
            {
                "id": "chain-tail",
                "is_device": "chain-tail",
                "auto_generated": False,
                "config": {"name": "chain-tail", "mapping": "span"},
                "segments": [[tail_device_id, 0, 15, False]],
                "effect": _EFFECT,
            },
        ],
    }
    with open(os.path.join(config_dir, "config.json"), "w") as f:
        json.dump(config, f)


def test_config_expected_active_ids_is_pure():
    from spectra.services.live_host import _config_expected_active_ids

    config = {"virtuals": [
        {"id": "a", "effect": _EFFECT},
        {"id": "b", "effect": _EFFECT, "active": False},   # explicitly paused
        {"id": "c"},                                        # no effect declared
        {"id": "d", "effect": _EFFECT, "active": True},
    ]}
    assert _config_expected_active_ids(config) == {"a", "d"}


def test_broken_chain_link_is_a_loud_activation_failure(tmp_path):
    from spectra.services.handover import SpectraSide
    from spectra.services.live_host import live

    _own_file(tmp_path)
    headless.silence_audio()
    config_dir = tmp_path / "fx-live"
    _write_chain_config(str(config_dir), break_tail=True)
    side = SpectraSide(config_dir=str(config_dir), open_audio=False)

    async def main():
        try:
            lo._save(lo.OwnershipRecord(owner=lo.SPECTRA))
            # activate() itself does NOT raise on a soft (partial) gap — it
            # gives the chain its best chance, then returns; verify_active()
            # is the single source of truth callers act on (run_handover
            # rolls back a fresh handover on this; resume_own_room instead
            # reports and keeps the working half up — see that module's
            # docstring).
            await side.activate()
            assert live.expected_active_ids == {"chain-mapper", "chain-tail"}
            gaps = live.activation_gaps()
            assert "chain-tail" in gaps
            assert "chain-mapper" not in gaps
            assert not await side.verify_active()
            # The working half is genuinely up and painting, not stranded.
            assert live.host.virtuals.get("chain-mapper").active
        finally:
            # Must run on THIS loop: live.deactivate() -> host.shutdown()
            # fires LedFxShutdownEvent via call_soon_threadsafe against the
            # loop captured at FxHost construction. A separate asyncio.run()
            # here would already have closed that loop, raising before the
            # render threads are ever joined — a real hang (non-daemon
            # threads spin forever), not a test artifact.
            if live.active:
                await live.deactivate()

    _run(main())


def test_full_chain_activation_reports_zero_gaps(tmp_path):
    from spectra.services.handover import SpectraSide
    from spectra.services.live_host import live

    _own_file(tmp_path)
    headless.silence_audio()
    config_dir = tmp_path / "fx-live"
    _write_chain_config(str(config_dir), break_tail=False)
    side = SpectraSide(config_dir=str(config_dir), open_audio=False)

    async def main():
        try:
            lo._save(lo.OwnershipRecord(owner=lo.SPECTRA))
            await side.activate()   # must not raise: the whole chain came up
            assert live.expected_active_ids == {"chain-mapper", "chain-tail"}
            assert live.activation_gaps() == {}
            assert await side.verify_active()
            # device_gaps: neither device is WLED, so nothing to confirm —
            # empty, not a false failure on non-WLED hardware.
            assert await live.device_gaps() == {}
        finally:
            if live.active:
                await live.deactivate()

    _run(main())


def test_liveness_endpoint_surfaces_activation_gaps(tmp_path):
    from spectra.services.handover import SpectraSide
    from spectra.services.live_host import live

    _own_file(tmp_path)
    headless.silence_audio()
    config_dir = tmp_path / "fx-live"
    _write_chain_config(str(config_dir), break_tail=True)
    side = SpectraSide(config_dir=str(config_dir), open_audio=False)

    async def main():
        from spectra.api.ownership import get_liveness

        try:
            lo._save(lo.OwnershipRecord(owner=lo.SPECTRA))
            await side.activate()   # does not raise on a soft gap; see above
            resp = await get_liveness()
            body = json.loads(bytes(resp.body))
            assert resp.status_code == 503
            assert not body["healthy"]
            assert "chain-tail" in body["activation_gaps"]
        finally:
            if live.active:
                await live.deactivate()

    _run(main())
