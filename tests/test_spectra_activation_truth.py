"""SPECTRA S3 — the "activation truth" fixes (report gate, 2026-08-14):

  1. The fresh-handover activation-verify path used to return a bare bool
     (spectra/services/handover.py's SpectraSide.verify_active()) — a
     refused take-back could not say WHICH light failed to rise, in the
     journal, the /ownership/handover API's error payload, or the SPECTRA
     UI toast. Fixed by naming every gap (spectra/services/live_host.py's
     describe_gaps()) and threading it through verify_active() →
     verification_detail() → run_handover()'s HandoverFailed message →
     post_handover()'s "error" field.

  2. spectra/services/live_host.py's expected_active_ids used to be EVERY
     virtual fx-live/config.json declares active — that config is seeded
     VERBATIM from the old LedFX world and inherits its dynamic tricks
     (mask/foreground/background layer virtuals, gap-dummy placeholders, a
     full-span "crystal" duplicate of "crystal-mapper", legacy contextual
     rooms the old app drove but SPECTRA's own scene engine never
     addresses) — so the gate could refuse forever on layers that were
     never supposed to rise. Fixed by intersecting the declared set against
     spectra/services/room_topology.py's genuinely_driven_virtual_ids() —
     the SAME ground truth (fx.device_model's imported category topology ∪
     stored scenes' literal virtual targets) scene_compiler.compile_scene()
     itself resolves real fires against.

Same offline discipline as test_crystal_activation_verify.py: no live
handover, no real device, no audio hardware (silence_audio, open_audio=
False throughout). Ground truth is monkeypatched to tmp fixtures so these
tests are hermetic regardless of what storage/device_categories.json or
storage/spectra/scenes.json happen to hold on the machine running them.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import device_model, headless, light_ownership as lo

_ORIGINAL_OWNERSHIP_FILE = lo.OWNERSHIP_FILE


def _run(coro):
    return asyncio.run(coro)


def _own_file(tmp_path) -> None:
    lo.OWNERSHIP_FILE = tmp_path / "ownership.json"


@pytest.fixture(autouse=True)
def _restore_globals():
    yield
    lo.OWNERSHIP_FILE = _ORIGINAL_OWNERSHIP_FILE
    device_model.refresh()


def _set_ground_truth(monkeypatch, tmp_path, *, categories: dict,
                      scenes: dict | None = None) -> None:
    """Point fx.device_model and spectra.config at isolated tmp fixtures so
    genuinely_driven_virtual_ids() never reads this machine's real
    storage/device_categories.json or storage/spectra/scenes.json."""
    from spectra import config as spectra_config

    cat_file = tmp_path / "device_categories.json"
    cat_file.write_text(json.dumps(categories))
    monkeypatch.setattr(device_model, "CATEGORIES_FILE", cat_file)
    device_model.refresh()

    scenes_file = tmp_path / "scenes.json"
    scenes_file.write_text(json.dumps(scenes or {}))
    monkeypatch.setattr(spectra_config, "SCENES_FILE", scenes_file)


_EFFECT = {"type": "singleColor", "config": {"color": "#000080"}}


def _write_layered_config(config_dir: str, *, break_radial: bool) -> None:
    """Four declared-active virtuals:
      - crystal-mapper:      real device, always comes up (genuinely driven)
      - radial-dummy:        real device (genuinely driven); its device is
                              OMITTED when break_radial=True, so it never
                              loads — the "genuinely dark scene-addressed
                              light" case.
      - crystal-mapper-mask: NOT genuinely driven (outside the fixture's
                              device_categories), and its device is always
                              missing so it never loads either — the "stale
                              declared layer" case.
      - dining-hues:         same shape as the mask virtual, standing in for
                              a legacy contextual room.
    """
    from fx.consts import CONFIGURATION_VERSION

    os.makedirs(config_dir, exist_ok=True)
    devices = [
        {"id": "crystal", "type": "dummy",
         "config": {"name": "crystal", "pixel_count": 16}},
    ]
    if not break_radial:
        devices.append(
            {"id": "radial", "type": "dummy",
             "config": {"name": "radial", "pixel_count": 16}})
    radial_device_id = "radial-missing-device" if break_radial else "radial"
    virtuals = [
        {"id": "crystal-mapper", "is_device": "crystal-mapper",
         "auto_generated": False,
         "config": {"name": "crystal-mapper", "mapping": "span"},
         "segments": [["crystal", 0, 15, False]], "effect": _EFFECT},
        {"id": "radial-dummy", "is_device": "radial-dummy",
         "auto_generated": False,
         "config": {"name": "radial-dummy", "mapping": "span"},
         "segments": [[radial_device_id, 0, 15, False]], "effect": _EFFECT},
        {"id": "crystal-mapper-mask", "is_device": "crystal-mapper-mask",
         "auto_generated": False,
         "config": {"name": "crystal-mapper-mask", "mapping": "span"},
         "segments": [["mask-missing-device", 0, 15, False]], "effect": _EFFECT},
        {"id": "dining-hues", "is_device": "dining-hues",
         "auto_generated": False,
         "config": {"name": "dining-hues", "mapping": "span"},
         "segments": [["dining-missing-device", 0, 15, False]], "effect": _EFFECT},
    ]
    config = {
        "configuration_version": CONFIGURATION_VERSION,
        "devices": devices,
        "virtuals": virtuals,
    }
    with open(os.path.join(config_dir, "config.json"), "w") as f:
        json.dump(config, f)


_DRIVEN_CATEGORIES = {
    "matrix": {"id": "matrix", "name": "Matrix",
              "virtuals": ["crystal-mapper", "radial-dummy"]},
}


# ── defect 2: stale declared layers never block verification ────────────────

def test_stale_declared_layers_dont_block_a_working_room(tmp_path, monkeypatch):
    """A config with stale layer declarations (crystal-mapper-mask,
    dining-hues — neither in the driven ground truth, neither ever loads)
    alongside a genuinely-driven, genuinely-working room must verify clean:
    the gate must not be unfalsifiable on virtuals that were never supposed
    to rise."""
    from spectra.services.handover import SpectraSide
    from spectra.services.live_host import live

    _own_file(tmp_path)
    headless.silence_audio()
    _set_ground_truth(monkeypatch, tmp_path, categories=_DRIVEN_CATEGORIES)
    config_dir = tmp_path / "fx-live"
    _write_layered_config(str(config_dir), break_radial=False)
    side = SpectraSide(config_dir=str(config_dir), open_audio=False)

    async def main():
        try:
            lo._save(lo.OwnershipRecord(owner=lo.SPECTRA))
            await side.activate()
            # Only the genuinely-driven ids are expected — the stale layers
            # were declared active in the config but excluded here.
            assert live.expected_active_ids == {"crystal-mapper", "radial-dummy"}
            assert live.activation_gaps() == {}
            assert await side.verify_active()
            assert side.verification_detail() is None
        finally:
            if live.active:
                await live.deactivate()

    _run(main())


# ── defect 1 + 2 combined: a genuinely dark, genuinely-addressed light ──────

def test_genuinely_dark_scene_addressed_light_refuses_by_name(tmp_path, monkeypatch, caplog):
    """radial-dummy IS in the driven ground truth and its device is missing
    — a genuine failure, not a stale layer — so it must refuse, and refuse
    BY NAME: in the journal (CRITICAL), in verification_detail() (what
    run_handover folds into the HandoverFailed message and the API's
    "error" field), while the stale layers (crystal-mapper-mask,
    dining-hues) are correctly never named — they were excluded from
    expected_active_ids in the first place."""
    from spectra.services.handover import SpectraSide
    from spectra.services.live_host import live

    caplog.set_level("CRITICAL", logger="spectra.services.handover")
    _own_file(tmp_path)
    headless.silence_audio()
    _set_ground_truth(monkeypatch, tmp_path, categories=_DRIVEN_CATEGORIES)
    config_dir = tmp_path / "fx-live"
    _write_layered_config(str(config_dir), break_radial=True)
    side = SpectraSide(config_dir=str(config_dir), open_audio=False)

    async def main():
        try:
            lo._save(lo.OwnershipRecord(owner=lo.SPECTRA))
            await side.activate()
            assert live.expected_active_ids == {"crystal-mapper", "radial-dummy"}
            gaps = live.activation_gaps()
            assert set(gaps) == {"radial-dummy"}
            assert not await side.verify_active()
            detail = side.verification_detail()
            assert detail is not None
            assert "radial-dummy" in detail
            assert "crystal-mapper-mask" not in detail
            assert "dining-hues" not in detail
        finally:
            if live.active:
                await live.deactivate()

    _run(main())
    assert any("radial-dummy" in r.message for r in caplog.records
               if r.levelname == "CRITICAL")


# ── defect 1: the named detail reaches run_handover's exception + the API ──

class _AlwaysReadySpotSide:
    """Minimal cooperative from-side — same shape as test_handover.py's
    RecordedSide, kept local so this file doesn't reach across test
    modules."""
    name = lo.SPOT_EFFECTS

    async def readiness_problems(self):
        return []

    async def quiesce(self):
        pass

    async def verify_quiesced(self):
        return True

    async def activate(self):
        pass

    async def verify_active(self):
        return True

    async def deactivate(self):
        pass


def test_fresh_handover_failure_names_the_light_in_the_exception(tmp_path, monkeypatch, caplog):
    """The 'nameless refusal' proof at the orchestrator level: run_handover's
    HandoverFailed — what the API surfaces verbatim in its "error" field —
    must carry the light's name, not just "spectra activation not
    verified"."""
    from spectra.services.handover import HandoverFailed, SpectraSide, run_handover
    from spectra.services.live_host import live

    caplog.set_level("CRITICAL", logger="spectra.services.handover")
    _own_file(tmp_path)
    headless.silence_audio()
    _set_ground_truth(monkeypatch, tmp_path, categories=_DRIVEN_CATEGORIES)
    config_dir = tmp_path / "fx-live"
    _write_layered_config(str(config_dir), break_radial=True)
    sides = {lo.SPOT_EFFECTS: _AlwaysReadySpotSide(),
             lo.SPECTRA: SpectraSide(config_dir=str(config_dir), open_audio=False)}

    async def main():
        try:
            with pytest.raises(HandoverFailed, match="radial-dummy"):
                await run_handover(lo.SPECTRA, sides, grace_s=0)
            assert lo.load().owner == lo.SPOT_EFFECTS
        finally:
            if live.active:
                await live.deactivate()

    _run(main())


def test_fresh_handover_api_error_payload_names_the_light(tmp_path, monkeypatch):
    """The API surface: POST /ownership/handover's 502 body's "error" field
    must name the light, not just say "activation not verified" — this is
    what spectra/web/src/api/client.ts's errorDetail() reads to build the
    toast RoomOwnershipBar shows on a failed take-back."""
    from spectra.api.ownership import HandoverRequest, post_handover
    from spectra.services import handover as handover_svc
    from spectra.services.handover import SpectraSide
    from spectra.services.live_host import live

    _own_file(tmp_path)
    headless.silence_audio()
    _set_ground_truth(monkeypatch, tmp_path, categories=_DRIVEN_CATEGORIES)
    config_dir = tmp_path / "fx-live"
    _write_layered_config(str(config_dir), break_radial=True)
    monkeypatch.setenv("SPECTRA_HANDOVER_ARMED", "1")
    fake_sides = {lo.SPOT_EFFECTS: _AlwaysReadySpotSide(),
                 lo.SPECTRA: SpectraSide(config_dir=str(config_dir), open_audio=False)}
    monkeypatch.setattr(handover_svc, "production_sides", lambda: fake_sides)

    async def main():
        try:
            resp = await post_handover(HandoverRequest(to=lo.SPECTRA))
            body = json.loads(bytes(resp.body))
            assert resp.status_code == 502
            assert body["result"] == "failed-landed-single-owner"
            assert "radial-dummy" in body["error"]
        finally:
            if live.active:
                await live.deactivate()

    _run(main())


# ── ground truth pure function ───────────────────────────────────────────────

def test_genuinely_driven_virtual_ids_unions_categories_and_scene_literals(tmp_path, monkeypatch):
    from spectra.models.scene import SceneDeviceConfig, SceneV2
    from spectra.services import scene_store
    from spectra.services.room_topology import genuinely_driven_virtual_ids

    _set_ground_truth(monkeypatch, tmp_path, categories=_DRIVEN_CATEGORIES)
    assert genuinely_driven_virtual_ids() == {"crystal-mapper", "radial-dummy"}

    scene = SceneV2(id="s1", name="Literal Target",
                    devices=[SceneDeviceConfig(target_kind="virtual",
                                               target="single-color-effect",
                                               effect_type="singleColor")])
    scene_store.save(scene)
    assert genuinely_driven_virtual_ids() == {
        "crystal-mapper", "radial-dummy", "single-color-effect"}


def test_genuinely_driven_virtual_ids_empty_when_no_ground_truth(tmp_path, monkeypatch):
    """No categories, no scenes: the caller (live_host._restrict_to_
    genuinely_driven) must read this as "no restriction available", never
    as "nothing is genuinely driven"."""
    from spectra.services.room_topology import genuinely_driven_virtual_ids

    _set_ground_truth(monkeypatch, tmp_path, categories={})
    assert genuinely_driven_virtual_ids() == set()


def test_restrict_falls_back_to_declared_set_with_no_ground_truth(tmp_path, monkeypatch):
    from spectra.services.live_host import _restrict_to_genuinely_driven

    _set_ground_truth(monkeypatch, tmp_path, categories={})
    declared = {"crystal-mapper", "crystal-mapper-mask", "dining-hues"}
    assert _restrict_to_genuinely_driven(declared) == declared


# ── live-evidence follow-up (2026-08-14): id-to-stamp mapping under the
#    REAL five-virtual name shape, on a real FxHost/Virtuals singleton
#    lifecycle (not a synthetic "chain-*" fixture) ───────────────────────────

_REAL_FIVE = ["crystal-mapper", "radial-dummy", "tv-mapper",
             "single-color-effect", "hues"]


def _write_real_shaped_config(config_dir: str) -> None:
    """One dummy device per production virtual name, device id == virtual
    id (the write_headless_config convention) — every one comes up clean.
    Exists to rule out a naming-convention-specific (hyphens, dedup) key
    mismatch in Virtual.id / host.virtuals / FrameFreshness.marks for the
    EXACT ids production uses, as opposed to the existing crystal-
    activation-verify fixture's synthetic "chain-*" names."""
    from fx.consts import CONFIGURATION_VERSION

    os.makedirs(config_dir, exist_ok=True)
    devices = [{"id": vid, "type": "dummy",
               "config": {"name": vid, "pixel_count": 16}}
              for vid in _REAL_FIVE]
    virtuals = [
        {"id": vid, "is_device": vid, "auto_generated": False,
         "config": {"name": vid, "mapping": "span"},
         "segments": [[vid, 0, 15, False]], "effect": _EFFECT}
        for vid in _REAL_FIVE
    ]
    config = {"configuration_version": CONFIGURATION_VERSION,
             "devices": devices, "virtuals": virtuals}
    with open(os.path.join(config_dir, "config.json"), "w") as f:
        json.dump(config, f)


def test_real_five_virtual_ids_map_cleanly_through_activation_and_freshness(
        tmp_path, monkeypatch):
    """Direct proof against the live-evidence report (2026-08-14): with the
    EXACT production virtual names, Virtual.id (fx/virtuals.py's Virtuals.
    create() dedup-on-collision + host.virtuals dict keys) and the
    VIRTUAL_UPDATE-fed freshness stamps (event.virtual_id) land under
    IDENTICAL keys to expected_active_ids — no hyphen/dedup mismatch. A
    working activation reports zero gaps and every expected id is a live,
    fresh entry in the freshness map by its OWN name, not a "-1"-suffixed
    dedup alias."""
    from spectra.services.handover import SpectraSide
    from spectra.services.live_host import STALE_AFTER_S, live

    _own_file(tmp_path)
    headless.silence_audio()
    _set_ground_truth(monkeypatch, tmp_path, categories={
        "matrix": {"id": "matrix", "name": "Matrix", "virtuals": _REAL_FIVE}})
    config_dir = tmp_path / "fx-live"
    _write_real_shaped_config(str(config_dir))
    side = SpectraSide(config_dir=str(config_dir), open_audio=False)

    async def main():
        try:
            lo._save(lo.OwnershipRecord(owner=lo.SPECTRA))
            await side.activate()
            assert live.expected_active_ids == set(_REAL_FIVE)
            assert live.activation_gaps() == {}
            assert live.fresh()
            ages = live.freshness.ages()
            for vid in _REAL_FIVE:
                # Every id resolves BY ITS OWN NAME — not renamed by the
                # Virtuals registry's dedup-on-collision (setattr(obj,
                # "_id", id) in fx/virtuals.py's Virtuals.create()), and
                # host.virtuals.get(vid) returns the SAME object whose
                # render thread fed this exact key into FrameFreshness.
                assert live.host.virtuals.get(vid) is not None, vid
                assert live.host.virtuals.get(vid).id == vid, vid
                assert vid in ages, vid
                assert ages[vid] < STALE_AFTER_S, vid
            assert await side.verify_active()
        finally:
            if live.active:
                await live.deactivate()

    _run(main())
