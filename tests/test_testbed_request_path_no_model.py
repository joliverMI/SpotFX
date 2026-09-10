"""beat_this is an OPTIONAL, OFFLINE-ONLY dependency: the report's own
constraint is that no engine is ever re-run inside a request path (several
of them take 80-560s a song), and this one additionally pulls torch.

The proof has to be about what the SERVING process actually loads, so it
runs in a FRESH INTERPRETER (the light-mode cold-start precedent): a warm
pytest process has already imported half the repo via earlier-collected
test modules, and `scripts/testbed_precompute.py`'s own test imports
spectra.services.testbed_beatthis directly — either would make an
in-process sys.modules assertion pass or fail for reasons that have
nothing to do with the request path.

It exercises EVERY testbed route (including the two that name beat_this as
their engine and the promote route that writes) against the real app
wiring, then asserts the model module never entered sys.modules. It goes
red the moment any handler imports it, lazily or otherwise.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap

DRIVER = textwrap.dedent('''
    import json, sys, tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp())
    from spectra import config as scfg
    scfg.TRIGGERS_FILE = tmp / "triggers.json"
    scfg.PROFILES_DIR = tmp / "profiles"
    scfg.SCENES_FILE = tmp / "scenes.json"
    scfg.COLOR_SETS_FILE = tmp / "color_sets.json"
    scfg.AUDIO_SHAPES_DIR = tmp / "audio_shapes"
    scfg.TESTBED_DIR = tmp / "testbed"
    scfg.TESTBED_AUDIO_DIR = tmp / "testbed" / "audio"
    scfg.TESTBED_ANALYSIS_DIR = tmp / "testbed" / "analysis"
    scfg.TESTBED_PINNED_FILE = tmp / "testbed" / "pinned_audio.json"
    scfg.TESTBED_PROMOTIONS_FILE = tmp / "testbed" / "promotions.json"
    scfg.TESTBED_PROMOTED_IDS_FILE = tmp / "testbed" / "promoted_ids.json"
    scfg.FIRE_HISTORY_FILE = tmp / "fire_history.json"
    scfg.SHOW_LOG_FILE = tmp / "show_log.json"
    (tmp / "profiles").mkdir()
    scfg.AUDIO_SHAPES_DIR.mkdir(parents=True)

    URI = "spotify:track:noModelInRequestPath"
    stem = "Artist - Song"
    (scfg.AUDIO_SHAPES_DIR / (stem + ".json")).write_text(
        json.dumps({"spotify_uri": URI}), encoding="utf-8")
    (scfg.AUDIO_SHAPES_DIR / (stem + ".librosa.json")).write_text(json.dumps({
        "spotify_uri": URI,
        "sections": [{"start_ms": 0, "end_ms": 10000, "label": "intro"},
                     {"start_ms": 10000, "end_ms": 30000, "label": "drop"}],
        "beats": [{"ms": 10050, "is_downbeat": True}],
    }), encoding="utf-8")

    # A beat_this precompute IS present -- reading a cached engine's marks
    # must not drag the model in either.
    from spectra.services import testbed_cache
    testbed_cache.save("beat_this", URI, "test", [
        {"time_ms": 10000, "kind": "downbeat", "label": None, "score": 0.9},
        {"time_ms": 10500, "kind": "beat", "label": None, "score": 0.8},
    ])

    from spectra.models.trigger import SpectraTrigger
    from spectra.services import trigger_store
    trigger_store.upsert(URI, SpectraTrigger(timestamp_ms=10100,
                                             action={"kind": "fire_scene"}))

    from fastapi.testclient import TestClient
    from spectra.app import create_app
    c = TestClient(create_app())

    calls = [
        ("GET", "/api/testbed/songs"),
        ("GET", "/api/testbed/marks?uri=" + URI),
        ("GET", "/api/testbed/waveform?uri=" + URI),
        ("GET", "/api/testbed/engines?uri=" + URI),
        ("GET", "/api/testbed/engine-marks?uri=%s&engine=beat_this&mark_kind=downbeat" % URI),
        ("GET", "/api/testbed/engine-marks?uri=%s&engine=librosa&mark_kind=section_boundary" % URI),
        ("GET", "/api/testbed/compare?uri=%s&engine=beat_this&mark_kind=downbeat" % URI),
        ("GET", "/api/testbed/compare?uri=%s&engine=librosa&mark_kind=section_boundary" % URI),
        ("GET", "/api/testbed/audio/status?uri=" + URI),
        ("GET", "/api/testbed/promotions"),
    ]
    statuses = {}
    for method, path in calls:
        r = c.request(method, path)
        statuses[path] = r.status_code

    r = c.post("/api/testbed/promote", json={
        "uri": URI, "timestamp_ms": 12345,
        "action": {"kind": "fire_response", "event_class": "flare"},
        "source_engine": "beat_this", "source_mark_kind": "downbeat",
        "confirmed": True,
    })
    statuses["POST /promote"] = r.status_code

    print(json.dumps({
        "statuses": statuses,
        "beat_this_imported": "beat_this" in sys.modules,
        "torch_imported": "torch" in sys.modules,
        "adapter_imported": "spectra.services.testbed_beatthis" in sys.modules,
    }))
''')


def _run_driver() -> dict:
    proc = subprocess.run([sys.executable, "-c", DRIVER],
                          capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_no_testbed_route_pulls_the_beat_this_model_into_the_serving_process():
    out = _run_driver()
    # Every route actually answered -- an assertion about imports is
    # worthless if the requests all 404'd.
    assert out["statuses"]["POST /promote"] == 200, out["statuses"]
    assert set(out["statuses"].values()) == {200}, out["statuses"]

    assert not out["beat_this_imported"], (
        "a testbed request handler imported the beat_this model -- it is an "
        "optional, offline-only dependency and the request path must never "
        "reach it")
    assert not out["torch_imported"], (
        "a testbed request handler pulled torch into the serving process")
    assert not out["adapter_imported"], (
        "spectra.services.testbed_beatthis (the model adapter) was imported "
        "by a request handler; only scripts/testbed_precompute.py may")
