"""SpectraTrigger.trigger_offset_ms (2026-08-21, data/preview-loops-and-
fires-on-the-trigger — his ask: "do events like flares and scene changes
carry an offset value... they need to"). Same field/units/sign convention
as FlareKind.trigger_offset_ms (models/scene.py) — descriptive only today,
no authoring UI, no fire-path read; this file proves only the schema
shape: default 0, bounds match the flare field, and a round-trip through
the human editing API (spectra/api/triggers.py) never drops it."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    monkeypatch.setattr(scfg, "TRIGGERS_FILE", tmp_path / "triggers.json")
    monkeypatch.setattr(scfg, "SCENES_FILE", tmp_path / "scenes.json")
    monkeypatch.setattr(scfg, "COLOR_SETS_FILE", tmp_path / "color_sets.json")


def test_default_is_zero_and_matches_the_flare_kinds_own_bounds():
    from spectra.models.scene import FlareKind, ParamTarget
    from spectra.models.trigger import FireSceneUpdateAction, SpectraTrigger

    trig = SpectraTrigger(timestamp_ms=1000, action=FireSceneUpdateAction(intensity=0.5))
    assert trig.trigger_offset_ms == 0

    flare_field = FlareKind.model_fields["trigger_offset_ms"]
    trig_field = SpectraTrigger.model_fields["trigger_offset_ms"]
    assert flare_field.default == trig_field.default == 0
    flare_ge = next(m.ge for m in flare_field.metadata if hasattr(m, "ge"))
    flare_le = next(m.le for m in flare_field.metadata if hasattr(m, "le"))
    trig_ge = next(m.ge for m in trig_field.metadata if hasattr(m, "ge"))
    trig_le = next(m.le for m in trig_field.metadata if hasattr(m, "le"))
    assert (trig_ge, trig_le) == (flare_ge, flare_le) == (-60_000, 60_000)

    with pytest.raises(Exception):
        SpectraTrigger(timestamp_ms=1000, action=FireSceneUpdateAction(intensity=0.5),
                       trigger_offset_ms=60_001)


def test_upsert_api_round_trips_a_nonzero_offset_unchanged():
    from fastapi.testclient import TestClient
    from spectra.app import create_app

    client = TestClient(create_app())
    body = {
        "id": "trig-1", "timestamp_ms": 5000, "enabled": True,
        "source": "authored", "generator_key": None,
        "action": {"kind": "fire_scene_update", "intensity": 0.5},
        "trigger_offset_ms": -750,
    }
    r = client.post("/api/triggers?uri=spotify:track:abc", json=body)
    assert r.status_code == 200

    r = client.get("/api/triggers?uri=spotify:track:abc")
    assert r.status_code == 200
    [stored] = r.json()
    assert stored["trigger_offset_ms"] == -750
