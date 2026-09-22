"""spectra/api/triggers.py::upsert_trigger stamps every human-facing write
source="authored" (generator_key cleared) regardless of what the caller
sent — the ownership-transfer rule front 3 depends on. snap_grid/
snap_moved_ms (spectra/services/beat_snap.py's provenance of a GENERATED
cue's pre-edit position) must be cleared the same way: a human dragging or
editing a generated, beat-snapped trigger builds its saved payload by
spreading the whole existing trigger object (SpectraTriggersCard.tsx,
SpectraTriggerDialog.tsx), so the stale snap fields would otherwise ride
along onto the now-"authored" trigger and describeEvent.ts would report a
beat-snap that never happened for the human's own edit."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    monkeypatch.setattr(scfg, "TRIGGERS_FILE", tmp_path / "triggers.json")
    monkeypatch.setattr(scfg, "SCENES_FILE", tmp_path / "scenes.json")
    monkeypatch.setattr(scfg, "COLOR_SETS_FILE", tmp_path / "color_sets.json")


def test_editing_a_generated_beat_snapped_trigger_clears_its_snap_provenance():
    from fastapi.testclient import TestClient
    from spectra.app import create_app

    client = TestClient(create_app())
    body = {
        "id": "trig-1", "timestamp_ms": 4850, "enabled": True,
        "source": "generated", "generator_key": "section:5000",
        "action": {"kind": "fire_scene_update", "intensity": 0.5},
        "trigger_offset_ms": 0,
        "snap_grid": "librosa", "snap_moved_ms": -150,
    }
    # The frontend's own edit shape: spread the whole existing (generated,
    # snapped) trigger, moving only timestamp_ms — exactly what dragging a
    # generated trigger on the timeline does.
    moved = {**body, "timestamp_ms": 9000}
    r = client.post("/api/triggers?uri=spotify:track:abc", json=moved)
    assert r.status_code == 200

    r = client.get("/api/triggers?uri=spotify:track:abc")
    assert r.status_code == 200
    [stored] = r.json()
    assert stored["source"] == "authored"
    assert stored["generator_key"] is None
    assert stored["snap_grid"] is None
    assert stored["snap_moved_ms"] is None
    assert stored["timestamp_ms"] == 9000
