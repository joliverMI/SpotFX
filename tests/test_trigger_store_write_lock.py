"""spectra/services/trigger_store.py — writers of the fired trigger copy
are serialised, AND none of them waits for that lock on the event loop.
Every mutation is a full load -> edit -> save of one file, so two
unserialised writers interleaving lose whichever landed first; and the
promotion's critical section spans two whole-file parses plus a rewrite,
so a route that took the lock from the loop would park the trigger tick,
the bridge poll and every WS broadcast behind it. These tests put two
writers inside that window on purpose, and drive the real HTTP routes to
prove where they run."""
from __future__ import annotations

import asyncio
import json
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


def _ran_on_loop() -> bool:
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


def _client():
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    return TestClient(create_app())


def test_authoring_routes_never_touch_the_store_on_the_event_loop(monkeypatch):
    """POST/DELETE /api/triggers each take write_lock across a full
    read+rewrite. Run on the loop, one Timeline save waits out whatever
    off-loop writer (the generator, a test-bed promotion) currently holds
    it — with the trigger engine's 200ms tick stalled behind it."""
    from spectra.services import trigger_store
    where: dict[str, bool] = {}
    real_upsert, real_delete = trigger_store.upsert, trigger_store.delete

    def _upsert(uri, trigger):
        where["upsert"] = _ran_on_loop()
        return real_upsert(uri, trigger)

    def _delete(uri, trigger_id):
        where["delete"] = _ran_on_loop()
        return real_delete(uri, trigger_id)

    monkeypatch.setattr(trigger_store, "upsert", _upsert)
    monkeypatch.setattr(trigger_store, "delete", _delete)

    client = _client()
    placed = client.post(f"/api/triggers?uri={URI}", json=json.loads(
        _trigger(1000).model_dump_json()))
    assert placed.status_code == 200
    assert client.delete(
        f"/api/triggers/{placed.json()['id']}?uri={URI}").status_code == 200

    assert where == {"upsert": False, "delete": False}
    assert trigger_store.list_for_song(URI) == []


def test_a_held_write_lock_does_not_stall_the_authoring_route_s_loop(monkeypatch):
    """The consequence, measured rather than argued: with the lock held by
    a worker (a promotion mid-critical-section), the event loop the POST is
    served on stays free to run other work."""
    from spectra.services import trigger_store
    released = threading.Event()
    ticked = threading.Event()

    def _hold():
        with trigger_store.write_lock:
            ticked.wait(timeout=5)
        released.set()

    holder = threading.Thread(target=_hold)
    holder.start()
    try:
        client = _client()
        # The route's own worker thread will block on the lock; the loop
        # must still be able to serve an unrelated request meanwhile.
        result: dict = {}

        def _save():
            result["status"] = client.post(
                f"/api/triggers?uri={URI}",
                json=json.loads(_trigger(2000).model_dump_json())).status_code

        saver = threading.Thread(target=_save)
        saver.start()
        assert client.get(f"/api/triggers?uri={URI}").status_code == 200
        ticked.set()
        saver.join(timeout=10)
        assert not saver.is_alive()
        assert result["status"] == 200
    finally:
        ticked.set()
        holder.join(timeout=5)
    assert released.is_set()
    assert len(trigger_store.list_for_song(URI)) == 1
