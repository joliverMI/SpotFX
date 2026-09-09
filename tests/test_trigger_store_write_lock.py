"""spectra/services/trigger_store.py — writers of the fired trigger copy
are serialised. The store is written from the event loop (POST/DELETE
/api/triggers) and from asyncio.to_thread workers (midsong_generator,
testbed_promote) at once; every mutation is a full load -> edit -> save of
one file, so two unserialised writers interleaving lose whichever landed
first. These tests put two writers inside that window on purpose and
assert nothing is lost."""
from __future__ import annotations

import threading

import pytest


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "TRIGGERS_FILE", tmp_path / "triggers.json")


URI = "spotify:track:writelock1"


def _trigger(timestamp_ms: int, **kw):
    from spectra.models.trigger import SpectraTrigger
    return SpectraTrigger(timestamp_ms=timestamp_ms,
                          action={"kind": "fire_response", "event_class": "flare"}, **kw)


def _meet_at_every_read(monkeypatch, parties=2, timeout_s=0.3):
    from spectra.services import trigger_store
    gate = threading.Barrier(parties)
    real_load = trigger_store._load_raw

    def slow_load():
        data = real_load()
        try:
            gate.wait(timeout=timeout_s)
        except threading.BrokenBarrierError:
            pass
        return data
    monkeypatch.setattr(trigger_store, "_load_raw", slow_load)


def _run_all(*targets):
    threads = [threading.Thread(target=t) for t in targets]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=10)
    assert not any(th.is_alive() for th in threads)


def test_concurrent_upserts_on_one_song_never_lose_a_write(monkeypatch):
    """The lost-update shape: a promotion's worker thread has loaded the
    file while the Timeline page's own POST lands on the loop; without the
    lock the worker's save replaces the file with its stale snapshot and
    the hand-placed trigger vanishes."""
    from spectra.services import trigger_store
    _meet_at_every_read(monkeypatch)
    a, b = _trigger(1000), _trigger(2000)
    _run_all(lambda: trigger_store.upsert(URI, a), lambda: trigger_store.upsert(URI, b))
    assert sorted(t.id for t in trigger_store.list_for_song(URI)) == sorted([a.id, b.id])


def test_concurrent_batch_and_delete_compose_instead_of_clobbering(monkeypatch):
    """apply_batch (the profile->fired sync, off-loop) beside delete (the
    authoring DELETE, on-loop): the survivor set is what both intended."""
    from spectra.services import trigger_store
    keep, gone = _trigger(1000), _trigger(2000)
    trigger_store.upsert(URI, keep)
    trigger_store.upsert(URI, gone)
    _meet_at_every_read(monkeypatch)
    new = _trigger(3000)
    _run_all(lambda: trigger_store.apply_batch(URI, [new], []),
             lambda: trigger_store.delete(URI, gone.id))
    assert sorted(t.id for t in trigger_store.list_for_song(URI)) == sorted([keep.id, new.id])


def test_reads_are_not_serialised_behind_a_writer():
    """The lock scope is the write's own load+save only: a reader on the
    event loop must not queue behind a worker holding the lock."""
    from spectra.services import trigger_store
    trigger_store.upsert(URI, _trigger(1000))
    seen: list = []
    with trigger_store.write_lock:
        reader = threading.Thread(
            target=lambda: seen.append(len(trigger_store.list_for_song(URI))))
        reader.start()
        reader.join(timeout=2)
        assert not reader.is_alive()
    assert seen == [1]
