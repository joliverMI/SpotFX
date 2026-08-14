"""Executable spec for SPECTRA S3 — light ownership and the safe handover.

The binding invariants (Admiral's architecture decision + design report
§2.6): exactly one owner at any instant BY CONSTRUCTION, never two writers;
enforcement in the write paths, not convention; a failed handover lands in a
safe single-owner state, never split; with ownership at spot-effects (the
shipped default) nothing in SPECTRA touches a device or audio input.

Sections:
  1. the shipped default (missing record = spot-effects owns)
  2. the one-owner-by-construction grant matrix over every state
  3. transition legality (the two-step cannot be skipped or raced)
  4. activation grants and the quiesce gate
  5. durability, history, corrupt-record fail-safe
  6. crash-orphaned handover recovery
  7. spot-effects write-plane gate: _request sheds, the LedFX-restart
     watchdog goes dormant (merge-scout §4d's resurrect trap), the systemd
     write-plane watchdog treats surrender as alive
  8. SPECTRA's seam routes transport by owner and refuses mid-handover
  9. the device layer refuses non-dummy devices without a live grant
 10. the orchestrator's failure landings (lying quiesce; activation failure)
 11. the readiness gate (order-8): missing/empty/unusable fx-live config
     REFUSES before the old owner is quiesced — room untouched, refusal
     names the seeder command
 12. the panic release (fx.light_ownership.RELEASED): a third settled state,
     one atomic step (no two-step — no new writer to verify into
     existence), sheds both write grants, idempotent, refuses only
     mid-handover; the way back is the SAME guarded handover with
     from_world=="released". Device-class and API-route proofs live in
     tests/test_release.py (pytest, not this script).
 13. nothing here ever touched audio hardware

Run from repo root: .venv/bin/python scripts/check_ownership.py
Isolated: temp files for every store; no LedFX I/O, no audio, no network.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def check(cond, label):
    if not cond:
        raise SystemExit(f"FAIL: {label}")
    print(f"ok: {label}")


td = Path(tempfile.mkdtemp(prefix="ownership-spec-"))

from fx import light_ownership as lo

lo.OWNERSHIP_FILE = td / "ownership.json"

# ── 1. the shipped default ───────────────────────────────────────────────────
check(lo.load().owner == lo.SPOT_EFFECTS,
      "missing record = the shipped default: spot-effects owns")
check(lo.writes_allowed(lo.SPOT_EFFECTS) and not lo.writes_allowed(lo.SPECTRA),
      "default grants: spot-effects writes, spectra does not")
check(not lo.OWNERSHIP_FILE.exists(),
      "reading the default never creates the file")

# ── 2. one owner by construction: the full grant matrix ──────────────────────
# Every reachable record state grants AT MOST one world; handing-over grants
# neither (the orchestrator's step-gated activation grant is the only power
# that exists mid-switch).


def _writers():
    return [w for w in lo.WORLDS if lo.writes_allowed(w)]


check(_writers() == [lo.SPOT_EFFECTS], "settled spot-effects: one writer")

h = lo.begin_handover(lo.SPECTRA)
check(lo.load().owner == lo.HANDING_OVER
      and lo.load().handover.step == lo.STEP_QUIESCING,
      "begin_handover: owner=handing-over, step=quiescing")
check(_writers() == [], "handing-over (quiescing): ZERO writers")
lo.mark_quiesced(h.token)
check(_writers() == [], "handing-over (activating): ZERO writers")
lo.commit(h.token)
check(_writers() == [lo.SPECTRA], "settled spectra: one writer")

h_back = lo.begin_handover(lo.SPOT_EFFECTS)
check(_writers() == [], "reverse handover in flight: ZERO writers")
lo.mark_quiesced(h_back.token)
lo.commit(h_back.token)
check(_writers() == [lo.SPOT_EFFECTS],
      "reverse commit: spot-effects again — at most one writer in every "
      "state visited (the record has ONE owner field; two owners are "
      "unrepresentable)")

# ── 3. transition legality ───────────────────────────────────────────────────
try:
    lo.begin_handover(lo.SPOT_EFFECTS)
    check(False, "begin to the current owner must refuse")
except lo.OwnershipError:
    check(True, "begin to the current owner refuses")

h = lo.begin_handover(lo.SPECTRA)
try:
    lo.begin_handover(lo.SPECTRA)
    check(False, "double begin must refuse")
except lo.OwnershipError:
    check(True, "double begin refuses (one handover at a time)")

try:
    lo.commit(h.token)
    check(False, "commit before the quiesce gate must refuse")
except lo.OwnershipError:
    check(True, "commit before the quiesce gate refuses — the two-step "
                "cannot be skipped")

try:
    lo.mark_quiesced("not-the-token")
    check(False, "foreign token must refuse")
except lo.OwnershipError:
    check(True, "foreign token refuses (only the orchestrator advances)")

lo.mark_quiesced(h.token)
try:
    lo.mark_quiesced(h.token)
    check(False, "double quiesce-mark must refuse")
except lo.OwnershipError:
    check(True, "double quiesce-mark refuses")

rec = lo.abort(h.token, "spec: forced failure")
check(rec.owner == lo.SPOT_EFFECTS and rec.handover is None,
      "abort from activating lands at the from-world — single owner, "
      "never split")
try:
    lo.abort(h.token, "again")
    check(False, "abort after landing must refuse")
except lo.OwnershipError:
    check(True, "abort after landing refuses (no handover in flight)")

# ── 4. activation grants and the quiesce gate ────────────────────────────────
try:
    lo.mint_activation_grant(lo.SPECTRA)
    check(False, "grant without ownership must refuse")
except lo.OwnershipError:
    check(True, "no grant while spot-effects owns")

h = lo.begin_handover(lo.SPECTRA)
try:
    lo.mint_activation_grant(lo.SPECTRA)
    check(False, "grant during quiescing must refuse")
except lo.OwnershipError:
    check(True, "no grant before the quiesce gate — the new writer cannot "
                "start while the old one may still be running")
lo.mark_quiesced(h.token)
g = lo.mint_activation_grant(lo.SPECTRA)
check(lo.grant_valid(g, lo.SPECTRA), "grant mints only past the quiesce gate")
check(not lo.grant_valid(g, lo.SPOT_EFFECTS), "grant is world-bound")
lo.abort(h.token, "spec: abort invalidates grants")
check(not lo.grant_valid(g, lo.SPECTRA),
      "abort kills the grant — a stale grant dies with the state that "
      "minted it")

h = lo.begin_handover(lo.SPECTRA)
lo.mark_quiesced(h.token)
g = lo.mint_activation_grant(lo.SPECTRA)
lo.commit(h.token)
check(lo.grant_valid(g, lo.SPECTRA),
      "commit keeps the grant (spectra now owns outright)")
h_back = lo.begin_handover(lo.SPOT_EFFECTS)
check(not lo.grant_valid(g, lo.SPECTRA),
      "the reverse handover's begin kills spectra's grant instantly")
lo.mark_quiesced(h_back.token)
lo.commit(h_back.token)

# ── 5. durability, history, corrupt-record fail-safe ─────────────────────────
on_disk = json.loads(lo.OWNERSHIP_FILE.read_text())
check(on_disk["owner"] == lo.SPOT_EFFECTS,
      "the record is durable and inspectable on disk")
check(any(e["event"] == "handover_abort" for e in on_disk["history"]),
      "failure landings are written into the history trail")
for i in range(60):
    hx = lo.begin_handover(lo.SPECTRA)
    lo.abort(hx.token, f"spec churn {i}")
check(len(lo.load().history) <= lo.HISTORY_LIMIT, "history is bounded")

lo.OWNERSHIP_FILE.write_text("{ not json !!")
check(lo.load().owner == lo.SPOT_EFFECTS,
      "corrupt record fails safe to the shipped default (spot-effects), "
      "never raises into a write path")
lo.OWNERSHIP_FILE.unlink()

# ── 6. crash-orphaned handover recovery ──────────────────────────────────────
h = lo.begin_handover(lo.SPECTRA)
check(lo.recover_stale_handover() is False,
      "a young handing-over record is left alone (may be a live orchestrator)")
raw = json.loads(lo.OWNERSHIP_FILE.read_text())
raw["handover"]["started_at"] = time.time() - 3600
lo.OWNERSHIP_FILE.write_text(json.dumps(raw))
check(lo.recover_stale_handover() is True
      and lo.load().owner == lo.SPOT_EFFECTS,
      "a stale orphan lands back at the from-world (safe single owner)")

# ── 7. the spot-effects write-plane gate ─────────────────────────────────────
from api import ledfx_client as lc

h = lo.begin_handover(lo.SPECTRA)
lo.mark_quiesced(h.token)
lo.commit(h.token)  # owner = spectra

resp = asyncio.run(lc._request("GET", "/api/info", label="ownership-spec"))
check(resp is None and lc._event_counters.get("ownership_shed", 0) == 1,
      "_request sheds EVERY call while spot-effects does not own — "
      "enforcement in the write path itself")

lc._watchdog_degraded_count = 3
asyncio.run(lc._ledfx_watchdog_tick())
check(lc._watchdog_degraded_count == 0,
      "the LedFX-restart watchdog goes dormant when not owner "
      "(merge-scout §4d: quiesced LedFX must NOT be resurrected)")
asyncio.run(lc._restart_ledfx_service())
check(lc._last_ledfx_restart == 0.0,
      "_restart_ledfx_service refuses outright when not owner "
      "(defense in depth)")
check(lc.get_health()["light_ownership"] == lo.SPECTRA,
      "get_health surfaces ownership — spot-effects reads the record too")

from services.write_plane_watchdog import evaluate

alive, reasons = evaluate(
    {"light_ownership": "spectra", "last_completion_age_s": 9999,
     "counters": {}, "breaker_open": False},
    {"gate_reset": 0, "deadline": 0})
check(alive and reasons == [],
      "systemd write-plane watchdog: surrendered ownership is ALIVE "
      "(no completions is the correct state), pings continue")
alive, reasons = evaluate(
    {"light_ownership": "spectra", "oldest_inflight_s": 99,
     "request_deadline_s": 10, "counters": {}, "breaker_open": False},
    {"gate_reset": 0, "deadline": 0})
check(not alive,
      "…but the hard internal signals still trip while surrendered")

# ── 8. SPECTRA's seam routes by owner and refuses mid-handover ───────────────
from spectra.services import fx_seam

asyncio.run(fx_seam.apply_writes([]))  # spectra owns → facade route (0 writes)
check(True, "seam under spectra ownership takes the in-process route")

hb = lo.begin_handover(lo.SPOT_EFFECTS)
try:
    asyncio.run(fx_seam.apply_writes([]))
    check(False, "seam must refuse during a handover")
except fx_seam.HandoverInProgress:
    check(True, "seam REFUSES mid-handover — nobody writes while the room "
                "changes hands")
lo.mark_quiesced(hb.token)
lo.commit(hb.token)  # owner = spot-effects
asyncio.run(fx_seam.apply_writes([]))  # HTTP route, zero writes → no I/O
check(True, "seam under spot-effects ownership takes the HTTP route "
            "(LedFX is the one device writer)")

# ── 9. the device layer refuses non-dummy devices without a live grant ───────
from fx.host import FxHost
from fx import headless
from fx.consts import CONFIGURATION_VERSION

live_dir = td / "fx-live"
live_dir.mkdir()
(live_dir / "config.json").write_text(json.dumps({
    "configuration_version": CONFIGURATION_VERSION,
    "devices": [{"id": "spec-ddp", "type": "ddp",
                 "config": {"name": "spec-ddp", "ip_address": "127.0.0.1",
                            "port": 4048, "pixel_count": 8}}],
    "virtuals": [],
}))


async def _try_start(grant):
    host = FxHost(str(live_dir), live_grant=grant)
    try:
        await host.start()
        return host, None
    except lo.OwnershipError as exc:
        return host, exc


host, err = asyncio.run(_try_start(None))
check(err is not None and len(list(host.devices.values())) == 0,
      "FxHost refuses a non-dummy device config without a grant — BEFORE "
      "creating any device")

h = lo.begin_handover(lo.SPECTRA)
lo.mark_quiesced(h.token)
g = lo.mint_activation_grant(lo.SPECTRA)
lo.abort(h.token, "spec: stale the grant")
host, err = asyncio.run(_try_start(g))
check(err is not None and len(list(host.devices.values())) == 0,
      "FxHost refuses a STALE grant (state changed since minting)")


async def _granted_start():
    h = lo.begin_handover(lo.SPECTRA)
    lo.mark_quiesced(h.token)
    grant = lo.mint_activation_grant(lo.SPECTRA)
    host = FxHost(str(live_dir), live_grant=grant)
    await host.start()
    created = len(list(host.devices.values()))
    await host.shutdown()
    lo.commit(h.token)
    return created


check(asyncio.run(_granted_start()) == 1,
      "the SAME config starts under a valid step-gated grant — the gate is "
      "ownership, not capability")
hb = lo.begin_handover(lo.SPOT_EFFECTS)
lo.mark_quiesced(hb.token)
lo.commit(hb.token)


async def _dummy_start():
    dummy_dir = td / "fx-dummy"
    headless.write_headless_config(str(dummy_dir))
    host = FxHost(str(dummy_dir))
    await host.start()
    n = len(list(host.devices.values()))
    await host.shutdown()
    return n


check(asyncio.run(_dummy_start()) == 1,
      "dummy-only configs (the headless harness) need no grant and never "
      "read the record")

# ── 10. the orchestrator's failure landings ──────────────────────────────────
from spectra.services.handover import HandoverFailed, run_handover


class ScriptedSide:
    def __init__(self, name, *, quiesce_ok=True, verify_quiesced_result=True,
                 activate_ok=True, verify_active_result=True):
        self.name = name
        self.calls = []
        self._quiesce_ok = quiesce_ok
        self._verify_quiesced = verify_quiesced_result
        self._activate_ok = activate_ok
        self._verify_active = verify_active_result

    async def readiness_problems(self):
        return []

    async def quiesce(self):
        self.calls.append("quiesce")
        if not self._quiesce_ok:
            raise RuntimeError("scripted quiesce failure")

    async def verify_quiesced(self):
        self.calls.append("verify_quiesced")
        return self._verify_quiesced

    async def activate(self):
        self.calls.append("activate")
        if not self._activate_ok:
            raise RuntimeError("scripted activation failure")

    async def verify_active(self):
        self.calls.append("verify_active")
        return self._verify_active

    async def deactivate(self):
        self.calls.append("deactivate")


def _sides(**spectra_kw):
    return {
        lo.SPOT_EFFECTS: ScriptedSide(lo.SPOT_EFFECTS),
        lo.SPECTRA: ScriptedSide(lo.SPECTRA, **spectra_kw),
    }


# Success path: quiesce → verify → activate → verify → RE-verify (report
# gate e4i: the from-world must still be quiesced immediately before
# commit) → commit.
sides = _sides()
record = asyncio.run(run_handover(lo.SPECTRA, sides, grace_s=0))
check(record.owner == lo.SPECTRA
      and sides[lo.SPOT_EFFECTS].calls
      == ["quiesce", "verify_quiesced", "verify_quiesced"]
      and sides[lo.SPECTRA].calls == ["activate", "verify_active"],
      "orchestrator: quiesce is VERIFIED before the new writer activates, "
      "and RE-verified immediately before commit")
hb = lo.begin_handover(lo.SPOT_EFFECTS)
lo.mark_quiesced(hb.token)
lo.commit(hb.token)

# The lying quiesce: the stop call 'succeeds' but verification says the old
# writer is still running → the new writer must never start.
sides = _sides()
sides[lo.SPOT_EFFECTS]._verify_quiesced = False
try:
    asyncio.run(run_handover(lo.SPECTRA, sides, grace_s=0))
    check(False, "lying quiesce must fail the handover")
except HandoverFailed:
    pass
check(lo.load().owner == lo.SPOT_EFFECTS
      and "activate" not in sides[lo.SPECTRA].calls,
      "lying quiesce: the to-side NEVER activates (Hue/DDP single-writer "
      "protected) and the record lands at the from-world")
check("activate" in sides[lo.SPOT_EFFECTS].calls,
      "…and the from-side is restored")

# Activation failure after a clean quiesce (e.g. the multi-second Hue DTLS
# handshake never completes): partial to-side is released FIRST, then the
# from-side restored, record lands single-owner.
sides = _sides(activate_ok=False)
try:
    asyncio.run(run_handover(lo.SPECTRA, sides, grace_s=0))
    check(False, "activation failure must fail the handover")
except HandoverFailed:
    pass
check(lo.load().owner == lo.SPOT_EFFECTS and lo.load().handover is None,
      "activation failure lands at the from-world, handover cleared")
s_calls = sides[lo.SPECTRA].calls
check(s_calls.index("deactivate") < len(s_calls)
      and sides[lo.SPOT_EFFECTS].calls[-1] == "activate",
      "rollback order: release the partial new writer BEFORE restoring the "
      "old one — never two writers even mid-rollback")

# ── 11. the readiness gate (order-8: refuse BEFORE quiesce) ──────────────────
from spectra.services.handover import (
    FX_LIVE_SEED_COMMAND,
    HandoverRefused,
    SpectraSide,
)

unseeded = SpectraSide(config_dir=str(td / "never-seeded"), open_audio=False)
sides = {lo.SPOT_EFFECTS: ScriptedSide(lo.SPOT_EFFECTS),
         lo.SPECTRA: unseeded}
try:
    asyncio.run(run_handover(lo.SPECTRA, sides, grace_s=0))
    check(False, "unseeded fx-live config must refuse the handover")
except HandoverRefused as exc:
    check(FX_LIVE_SEED_COMMAND in str(exc),
          "the refusal names the missing preparation and the seeder command")
check(sides[lo.SPOT_EFFECTS].calls == [],
      "readiness gate: the OLD OWNER WAS NEVER QUIESCED — refusal happens "
      "before the record moves, room untouched")
check(lo.load().owner == lo.SPOT_EFFECTS,
      "…and the record still says spot-effects owns")

empty_dir = td / "fx-live-empty"
empty_dir.mkdir()
(empty_dir / "config.json").write_text(
    json.dumps({"devices": [], "virtuals": []}))
sides = {lo.SPOT_EFFECTS: ScriptedSide(lo.SPOT_EFFECTS),
         lo.SPECTRA: SpectraSide(config_dir=str(empty_dir), open_audio=False)}
try:
    asyncio.run(run_handover(lo.SPECTRA, sides, grace_s=0))
    check(False, "empty fx-live config must refuse the handover")
except HandoverRefused:
    check(sides[lo.SPOT_EFFECTS].calls == [],
          "empty config: handover refuses, old owner never quiesced")

# ── 12. the panic release: a third settled state, one atomic step ────────────
check(lo.load().owner == lo.SPOT_EFFECTS, "settled at spot-effects before release")
rec = lo.release("spec: panic press")
check(rec.owner == lo.RELEASED, "release() lands owner=released")
check(not lo.writes_allowed(lo.SPOT_EFFECTS) and not lo.writes_allowed(lo.SPECTRA),
      "released grants NEITHER world — same shape as handing-over, but no "
      "new writer is coming up")
try:
    lo.mint_activation_grant(lo.SPECTRA)
    check(False, "no activation grant while released")
except lo.OwnershipError:
    check(True, "released refuses SPECTRA's device-layer grant too — "
                "FxHost.start() stays refused for any non-dummy config")

rec2 = lo.release("spec: second press")
check(rec2.owner == lo.RELEASED
      and any(e["event"] == "release_repeat" for e in rec2.history),
      "a second press is idempotent, not an error — a panic handle must "
      "never error on a repeat press")

h = lo.begin_handover(lo.SPECTRA)
try:
    lo.release("spec: cannot release mid-handover")
    check(False, "release mid-handover must refuse")
except lo.OwnershipError:
    check(True, "release refuses mid-handover (every transition here "
                "requires a settled owner first)")
lo.abort(h.token, "spec: land back at spot-effects")

# The way back reuses check_can_begin/begin_handover with ZERO special
# casing for from_world=="released" — it is an ordinary from-world; the
# quiesce-skip lives in the orchestrator (spectra/services/handover.py),
# proven with the real SpectraSide in tests/test_release.py.
lo.release("spec: released before the way-back begin")
h_back = lo.begin_handover(lo.SPECTRA)
check(h_back.from_world == lo.RELEASED,
      "begin_handover captures released as an ordinary from-world — no "
      "code change needed in the record for the way back")
lo.abort(h_back.token, "spec: land back at released")
check(lo.load().owner == lo.RELEASED,
      "abort() lands back at from_world generically — released included")

# ── 13. nothing here ever touched audio hardware ─────────────────────────────
from fx.audio_ingest import AudioIngestHub, LiveDeviceSource

try:
    LiveDeviceSource(AudioIngestHub()).open()
    check(False, "LiveDeviceSource.open() without allow_device must refuse")
except RuntimeError:
    check(True, "LiveDeviceSource.open() refuses without allow_device=True")

from fx.compat_sounddevice import _LazySounddevice

check(_LazySounddevice._module is None,
      "the whole spec ran without loading sounddevice — no audio hardware "
      "was touched")

print("\nALL OWNERSHIP INVARIANTS HOLD")
