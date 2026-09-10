"""spectra/services/analysis_reader.py's uri -> stem index is READ on the
event-loop thread every tick (bridge.intensity() through section_energy_at)
and REBUILT from a worker thread by the test bed's corpus listing
(stem_index() under asyncio.to_thread). A rebuild must never expose a
partial index: a reader holding a uri that is genuinely on disk must never
miss — a miss makes it run a full rebuild of its own on the loop thread,
the stall the off-loop listing exists to remove."""
from __future__ import annotations

import json
import threading
import time

import pytest


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from spectra import config as scfg
    from spectra.services import analysis_reader
    monkeypatch.setattr(scfg, "AUDIO_SHAPES_DIR", tmp_path / "audio_shapes")
    scfg.AUDIO_SHAPES_DIR.mkdir(parents=True)
    analysis_reader._shape_index = {}
    analysis_reader._index_built = False


def _seed(scfg, n: int) -> list[str]:
    uris = []
    for i in range(n):
        uri = f"spotify:track:idx{i:04d}"
        (scfg.AUDIO_SHAPES_DIR / f"Song {i:04d}.json").write_text(
            json.dumps({"spotify_uri": uri}), encoding="utf-8")
        uris.append(uri)
    return uris


def test_stem_index_is_complete_and_holds_across_a_later_rebuild():
    from spectra import config as scfg
    from spectra.services import analysis_reader
    uris = _seed(scfg, 50)

    snapshot = analysis_reader.stem_index()
    assert set(snapshot) == set(uris)
    assert snapshot[uris[7]] == "Song 0007"

    (scfg.AUDIO_SHAPES_DIR / "Late.json").write_text(
        json.dumps({"spotify_uri": "spotify:track:late"}), encoding="utf-8")
    assert analysis_reader.stem_for_uri("spotify:track:late") == "Late"
    assert "spotify:track:late" not in snapshot
    assert set(snapshot) == set(uris)
    assert "spotify:track:late" in analysis_reader.stem_index()


def test_a_reader_never_misses_while_a_worker_thread_rebuilds(monkeypatch):
    """The event-loop reader's own contract: a uri that is on disk resolves
    on every single call, and the reader never has to rebuild for itself,
    however many times a worker rebuilds underneath it."""
    from spectra import config as scfg
    from spectra.services import analysis_reader
    uris = _seed(scfg, 200)
    watched = uris[-1]
    analysis_reader.stem_index()

    rebuilds_by_thread: dict[int, int] = {}
    real_build = analysis_reader._build_index

    def _counting_build():
        ident = threading.get_ident()
        rebuilds_by_thread[ident] = rebuilds_by_thread.get(ident, 0) + 1
        return real_build()
    monkeypatch.setattr(analysis_reader, "_build_index", _counting_build)

    stop = threading.Event()
    worker_rebuilds = 0

    def _worker():
        nonlocal worker_rebuilds
        while not stop.is_set():
            analysis_reader.stem_index()
            worker_rebuilds += 1

    worker = threading.Thread(target=_worker)
    worker.start()
    reader_ident = threading.get_ident()
    misses = 0
    reads = 0
    deadline = time.monotonic() + 10.0
    try:
        while worker_rebuilds < 20 and time.monotonic() < deadline:
            if analysis_reader.stem_for_uri(watched) != "Song 0199":
                misses += 1
            reads += 1
            time.sleep(0)
    finally:
        stop.set()
        worker.join()

    assert worker_rebuilds >= 5
    assert reads > 1000
    assert misses == 0
    assert rebuilds_by_thread.get(reader_ident, 0) == 0
