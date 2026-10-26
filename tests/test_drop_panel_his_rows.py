"""HIS OWN DROPS ON THE HOME DROPS PANEL (2026-10-26, predrop plan step 1 —
spectra/services/drop_panel.py and services/profile_trigger_edit.py are
the binding statements; the Admiral's answer 6: "it can remove ones i
manually added and disables imported ones").

ON COPIES OF HIS STORES: tests/fixtures/drop_panel_his_rows.json holds two
of his real songs, captured from temp copies (2026-10-25) — their song
profiles, their fired-copy authored rows, their sync-ledger entries and
their drop detections. Pop Off's phase triggers were placed by hand; the
Dopamine profile was written by the AI generator, so every one of its
triggers counts as imported.

Both processes run IN-PROCESS: SPECTRA's drop_panel reaches the root
process's real `routers/profiles.py` over an ASGI transport, and the root
route's whole-song sync runs SPECTRA's own sync planner — the identical
plan_song/apply_plan body `POST /api/triggers/sync-from-profile` runs. No
live access.

  1. Removing his hand-placed drop deletes EXACTLY its row's triggers from
     the profile and the fired copy, and dismisses the detection it stood in
     for; one undo puts all of it back. The route's whole-song sync (the one
     a Timeline save runs) also lands any earlier profile edit that had not
     reached the fired copy — his real Pop Off data has exactly one, a
     non-phase trigger the fired copy still held at 147,240 ms that his
     profile has at 148,338 ms — and nothing else moves.
  2. Removing an imported drop switches its triggers OFF in both copies;
     they survive a re-import under "protect" switched off; switching the
     drop back on brings them and the detection back.
  3. A part switched off on his row: his trigger, and the standing
     detection's same part.
  4. The root route refuses an unknown id and any trigger that is not a
     charge/lull/drop, writing nothing; a stale restore is refused.
  5. Sonic's Remove asks first and acts only on the yes.
"""
from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path

import httpx
import pytest

from spectra import config as scfg
from spectra.services import drop_panel, drop_sequences as ds

FIX = json.loads((Path(__file__).parent / "fixtures" /
                  "drop_panel_his_rows.json").read_text(encoding="utf-8"))
POP_OFF = "spotify:track:4PolqZLqReEqc3yURJtzc4"
DOPAMINE = "spotify:track:7vFKcXQ39f74XNrZmXADIT"
PHASE = ("fixed-charge", "fixed-lull", "fixed-drop")


@pytest.fixture()
def stores(tmp_path, monkeypatch):
    """Both worlds, isolated: the root's song profiles, SPECTRA's fired copy,
    the sync ledger and the drop store — seeded from the fixture."""
    from services import profile_manager, spectra_trigger_sync_client
    from spectra.services import profile_sync_ledger, profile_trigger_sync, trigger_store

    profiles = tmp_path / "profiles"
    profiles.mkdir()
    monkeypatch.setattr(profile_manager, "PROFILES_DIR", profiles)
    monkeypatch.setattr(profile_manager, "_index_built", False)
    profile_manager._uri_to_filename.clear()
    profile_manager._titleartist_to_filename.clear()
    monkeypatch.setattr(scfg, "TRIGGERS_FILE", tmp_path / "triggers.json")
    monkeypatch.setattr(scfg, "PROFILE_SYNC_LEDGER_FILE", tmp_path / "ledger.json")
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")

    fired, ledger, drops = {}, {}, {}
    for uri, song in FIX["songs"].items():
        (profiles / song["profile_filename"]).write_text(
            json.dumps(song["profile"], indent=2, ensure_ascii=True), encoding="utf-8")
        fired[uri] = copy.deepcopy(song["fired_authored"])
        ledger[uri] = dict(song["ledger"])
        drops[uri] = copy.deepcopy(song["drop_sequences"])
    scfg.TRIGGERS_FILE.write_text(json.dumps(fired), encoding="utf-8")
    scfg.PROFILE_SYNC_LEDGER_FILE.write_text(json.dumps(ledger), encoding="utf-8")
    scfg.DROP_SEQUENCES_FILE.write_text(json.dumps(drops), encoding="utf-8")
    ds.reset()

    async def sync_song(uri, triggers, delete_missing=True):
        # SPECTRA's own POST /api/triggers/sync-from-profile body, in-process
        rows = trigger_store._load_raw().get(uri, [])
        known = profile_sync_ledger.for_song(profile_sync_ledger.load(), uri)
        plan = profile_trigger_sync.plan_song(uri, triggers, rows, known,
                                              delete_missing=delete_missing)
        return {"status": "ok", **profile_trigger_sync.apply_plan(plan)}
    monkeypatch.setattr(spectra_trigger_sync_client, "sync_song", sync_song)

    from fastapi import FastAPI
    import routers.profiles as root_profiles
    root = FastAPI()
    root.include_router(root_profiles.router)

    async def http(method, path, *, params=None, json=None):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=root),
                                     base_url="http://root") as client:
            return await client.request(method, path, params=params, json=json)
    monkeypatch.setattr(drop_panel, "http", http)
    return {"profiles": profiles, "root": root}


def _profile(stores, uri) -> dict:
    name = FIX["songs"][uri]["profile_filename"]
    return json.loads((stores["profiles"] / name).read_text(encoding="utf-8"))


def _profile_bytes(stores, uri) -> bytes:
    return (stores["profiles"] / FIX["songs"][uri]["profile_filename"]).read_bytes()


def _fired(uri) -> dict:
    from spectra.services import trigger_store
    return {r["id"]: r for r in trigger_store._load_raw().get(uri, [])}


def _drift(uri) -> dict:
    """{trigger id: the profile's row} for every authored trigger the two
    copies disagreed on BEFORE any edit — what any whole-song sync lands."""
    from spectra.services import profile_trigger_sync
    song = FIX["songs"][uri]
    plan = profile_trigger_sync.plan_song(uri, song["profile"]["triggers"],
                                          song["fired_authored"], song["ledger"],
                                          delete_missing=True)
    assert not plan.deletes and not plan.skipped
    return {t.id: t for t in plan.upserts}


def _row(uri, drop_ms):
    v = ds.view(uri)
    return next(r for r in v["yours"] if r["drop"]["timestamp_ms"] == drop_ms)


def _run(coro):
    return asyncio.run(coro)


def _undo(uri, res):
    return _run(drop_panel.restore(uri, res.before, ds.edits_rev(res.after),
                                   drop_panel._reverse(res.profile)))


# ── 1. a hand-placed drop: deleted, exactly, and undone ──────────────────

def test_removing_his_hand_placed_drop_deletes_exactly_its_triggers_and_dismisses_its_stand_in(stores):
    row = _row(POP_OFF, 59603)
    assert row["enabled"] and row["detection"] == "drop:59570"
    ids = {row[h]["id"] for h in ("charge", "lull", "drop")}
    before_profile = _profile(stores, POP_OFF)
    before_fired = _fired(POP_OFF)

    res = _run(drop_panel.remove(POP_OFF, row["key"]))

    after_profile = _profile(stores, POP_OFF)
    kept = [t for t in before_profile["triggers"] if t["id"] not in ids]
    assert after_profile["triggers"] == kept                    # exactly its three, nothing else
    assert {k: v for k, v in after_profile.items() if k != "triggers"} == \
        {k: v for k, v in before_profile.items() if k != "triggers"}
    fired = _fired(POP_OFF)
    assert ids.isdisjoint(fired)
    drift = _drift(POP_OFF)
    assert list(drift) == ["3fe44f0d-8699-4e0c-8696-653d32dee5d1"]
    assert set(fired) == set(before_fired) - ids
    for tid, row_now in fired.items():
        if tid in drift:                     # the earlier edit, landed
            assert row_now["timestamp_ms"] == drift[tid].timestamp_ms == 148_338
            assert before_fired[tid]["timestamp_ms"] == 147_240
        else:
            assert row_now == before_fired[tid], tid
    assert {c["did"] for c in res.profile} == {"deleted"} and len(res.profile) == 3
    s = next(x for x in ds.view(POP_OFF)["sequences"] if x["key"] == "drop:59570")
    assert s["state"] == ds.STATE_DISMISSED
    assert all(r["key"] != row["key"] for r in ds.view(POP_OFF)["yours"])
    assert "deleted 3 triggers you placed by hand" in res.said

    _undo(POP_OFF, res)
    assert _profile(stores, POP_OFF) == before_profile           # back where each sat
    undone = _fired(POP_OFF)
    assert set(undone) == set(before_fired)
    # the three come back through the sync, so they are written in its own
    # full shape (fields the migrated rows left out now carry their
    # defaults) — the same trigger, compared as the model reads it
    from spectra.models.trigger import SpectraTrigger
    for t in undone:
        if t in drift:
            continue
        if t in ids:
            assert SpectraTrigger(**undone[t]) == SpectraTrigger(**before_fired[t]), t
        else:
            assert undone[t] == before_fired[t], t
    back = next(x for x in ds.view(POP_OFF)["sequences"] if x["key"] == "drop:59570")
    assert back["state"] == ds.STATE_MATCHES_YOURS
    assert ds.edits(POP_OFF)["overrides"] == {}


def test_the_profile_keeps_its_own_escaping_and_every_untouched_byte_of_meaning(stores):
    raw = _profile_bytes(stores, POP_OFF)
    assert not any(b > 127 for b in raw)                       # an escaped file
    row = _row(POP_OFF, 101020)
    _run(drop_panel.remove(POP_OFF, row["key"]))
    assert not any(b > 127 for b in _profile_bytes(stores, POP_OFF))


# ── 2. an imported drop: switched off, survives a re-import, back on ─────

def test_removing_an_imported_drop_switches_it_off_in_both_copies_and_switch_on_brings_it_back(stores):
    row = _row(DOPAMINE, 47850)
    assert row["detection"] == "drop:47853"
    ids = {row[h]["id"] for h in ("charge", "lull", "drop")}
    before_profile = _profile(stores, DOPAMINE)

    res = _run(drop_panel.remove(DOPAMINE, row["key"]))

    prof = {t["id"]: t for t in _profile(stores, DOPAMINE)["triggers"]}
    assert all(prof[i]["enabled"] is False for i in ids)       # kept, switched off
    assert len(prof) == len(before_profile["triggers"])
    fired = _fired(DOPAMINE)
    assert all(fired[i]["enabled"] is False for i in ids)
    assert {c["did"] for c in res.profile} == {"switched_off"}
    seqs = {s["key"]: s for s in ds.view(DOPAMINE)["sequences"]}
    assert seqs["drop:47853"]["state"] == ds.STATE_DISMISSED
    dimmed = _row(DOPAMINE, 47850)
    assert dimmed["enabled"] is False and dimmed["detection"] == "drop:47853"

    # A RE-IMPORT UNDER "protect" leaves every switched-off one off
    from models.song_profile import MusicTrigger
    from services import trigger_identity as ti
    existing = [MusicTrigger(**t) for t in _profile(stores, DOPAMINE)["triggers"]]
    again = [MusicTrigger(**{**t, "enabled": True}) for t in before_profile["triggers"]]
    merged, counts = ti.merge_imported_triggers(existing, again, policy=ti.PROTECT)
    assert all(not t.enabled for t in merged if t.id in ids)
    assert counts["kept"] == len(before_profile["triggers"]) and counts["added"] == 0

    # the power button: every member back on, the stand-in back
    _run(drop_panel.switch_on(DOPAMINE, row["key"]))
    prof = {t["id"]: t for t in _profile(stores, DOPAMINE)["triggers"]}
    assert all(prof[i]["enabled"] is True for i in ids)
    seqs = {s["key"]: s for s in ds.view(DOPAMINE)["sequences"]}
    assert seqs["drop:47853"]["state"] == ds.STATE_MATCHES_YOURS
    assert ds.edits(DOPAMINE)["overrides"] == {}


def test_a_stable_import_id_counts_as_imported_and_a_re_import_finds_it_off(stores):
    """A drop carrying the stable analysed-import id is imported even in a
    profile no import flag marks, and a re-import of the same mark under
    "protect" finds it by that id and leaves it switched off."""
    from models.song_profile import MusicTrigger
    from services import profile_trigger_edit as pte, trigger_identity as ti
    prof = copy.deepcopy(FIX["songs"][POP_OFF]["profile"])
    stable = ti.stable_trigger_id("fixed-drop", 150_000)
    prof["triggers"].append({"id": stable, "timestamp_ms": 150_000, "event_id": "fixed-drop",
                             "labels": [], "enabled": True, "intensity": 0.8})
    assert pte.imported_reason(prof["triggers"][-1], prof) == pte.REASON_ANALYSED_ID
    changes = pte.apply(prof, pte.Edit(remove=[stable]))
    assert [c["did"] for c in changes] == ["switched_off"]
    existing = [MusicTrigger(**t) for t in prof["triggers"]]
    fresh = ti.build_imported_triggers([{"event_id": "fixed-drop", "timestamp_ms": 150_000}])
    merged, counts = ti.merge_imported_triggers(existing, fresh, policy=ti.PROTECT)
    hit = [t for t in merged if t.id == stable]
    assert len(hit) == 1 and hit[0].enabled is False and counts["added"] == 0


# ── 3. one part of his row ───────────────────────────────────────────────

def test_switching_his_lull_off_deletes_it_and_silences_the_stand_ins_lull(stores):
    row = _row(POP_OFF, 59603)
    lull_id = row["lull"]["id"]
    res = _run(drop_panel.set_parts(POP_OFF, row["key"], {"lull": "off"}))
    assert lull_id not in {t["id"] for t in _profile(stores, POP_OFF)["triggers"]}
    assert lull_id not in _fired(POP_OFF)
    det = next(s for s in ds.view(POP_OFF)["sequences"] if s["key"] == "drop:59570")
    assert det["parts"]["lull"] == "off"
    assert [c["did"] for c in res.profile] == ["deleted"]
    _undo(POP_OFF, res)
    assert lull_id in {t["id"] for t in _profile(stores, POP_OFF)["triggers"]}
    det = next(s for s in ds.view(POP_OFF)["sequences"] if s["key"] == "drop:59570")
    assert det["parts"]["lull"] != "off"


def test_switching_his_imported_drop_off_and_on_again_by_its_part(stores):
    row = _row(DOPAMINE, 100950)
    _run(drop_panel.set_parts(DOPAMINE, row["key"], {"drop": "off"}))
    assert _row(DOPAMINE, 100950)["enabled"] is False
    _run(drop_panel.set_parts(DOPAMINE, row["key"], {"drop": "on"}))
    assert _row(DOPAMINE, 100950)["enabled"] is True
    assert ds.edits(DOPAMINE)["overrides"] == {}


# ── 4. the root route's refusals ─────────────────────────────────────────

def _post(stores, body):
    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=stores["root"]),
                                     base_url="http://root") as c:
            return await c.post("/api/profiles/triggers/edit", json=body)
    return asyncio.run(go())


def test_the_route_refuses_an_unknown_id_and_any_non_phase_trigger_writing_nothing(stores):
    before = _profile_bytes(stores, POP_OFF)
    r = _post(stores, {"uri": POP_OFF, "remove": ["no-such-trigger"]})
    assert r.status_code == 404 and "no-such-trigger" in r.json()["detail"]
    flare = next(t for t in FIX["songs"][POP_OFF]["profile"]["triggers"]
                 if t["event_id"] not in PHASE)
    r = _post(stores, {"uri": POP_OFF, "delete": [flare["id"]]})
    assert r.status_code == 422 and flare["event_id"] in r.json()["detail"]
    # a phase trigger alongside it does not slip through either
    drop = next(t for t in FIX["songs"][POP_OFF]["profile"]["triggers"]
                if t["event_id"] == "fixed-drop")
    r = _post(stores, {"uri": POP_OFF, "disable": [drop["id"], flare["id"]]})
    assert r.status_code == 422
    assert _profile_bytes(stores, POP_OFF) == before


def test_a_stale_restore_is_refused(stores):
    row = _row(POP_OFF, 59603)
    res = _run(drop_panel.remove(POP_OFF, row["key"]))
    records = drop_panel._reverse(res.profile)
    records[0]["from"] = {**(records[0]["from"] or {}), "id": records[0]["id"],
                          "event_id": "fixed-drop", "timestamp_ms": 1}
    r = _post(stores, {"uri": POP_OFF, "restore": records})
    assert r.status_code in (409, 422)


def test_the_route_answers_who_placed_each_trigger(stores):
    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=stores["root"]),
                                     base_url="http://root") as c:
            return (await c.get("/api/profiles/triggers/provenance", params={"uri": POP_OFF}),
                    await c.get("/api/profiles/triggers/provenance", params={"uri": DOPAMINE}))
    pop, dop = asyncio.run(go())
    assert {t["remove_would"] for t in pop.json()["triggers"]} == {"delete"}
    assert {t["remove_would"] for t in dop.json()["triggers"]} == {"disable"}
    assert {t["why"] for t in dop.json()["triggers"]} == {"ai_generated"}


# ── 5. Sonic asks first ──────────────────────────────────────────────────

def test_sonics_remove_asks_first_and_acts_only_on_the_yes(stores):
    from spectra.services import drop_console
    before = _profile_bytes(stores, POP_OFF)
    ask = _run(drop_console._op_remove(your_drop_s=59.6, uri=POP_OFF))
    assert ask["status"] == "needs_confirmation"
    assert "delete your drop at 59.6 s (you placed it by hand)" in ask["question"]
    assert "dismiss the detection" in ask["question"]
    assert _profile_bytes(stores, POP_OFF) == before            # nothing yet
    wrong = _run(drop_console._op_remove(your_drop_s=59.6, uri=POP_OFF, confirm_id="nope"))
    assert wrong["status"] == "rejected"
    ask = _run(drop_console._op_remove(your_drop_s=59.6, uri=POP_OFF))
    done = _run(drop_console._op_remove(your_drop_s=59.6, uri=POP_OFF,
                                        confirm_id=ask["confirm_id"]))
    assert done["status"] == "applied"
    assert all(r["drop"]["timestamp_ms"] != 59603 for r in ds.view(POP_OFF)["yours"])
    # Sonic's own undo puts both stores back
    undone = _run(drop_console._op_undo(uri=POP_OFF))
    assert undone["status"] == "applied"
    assert json.loads(_profile_bytes(stores, POP_OFF)) == json.loads(before)


def test_sonic_reaches_his_drop_through_the_detection_standing_in_for_it(stores):
    from spectra.services import drop_console
    listing = _run(drop_console._op_list(uri=DOPAMINE))
    mine = next(y for y in listing["yours"] if y["drop_s"] == 47.85)
    number = mine["stands_for"][0]
    ask = _run(drop_console._op_set_part(part="lull", on=False, sequence=number, uri=DOPAMINE))
    assert ask["status"] == "needs_confirmation"
    assert "switch off your lull" in ask["question"]


# ── 6. a drop born on SPECTRA's own trigger card ─────────────────────────

CARD_CHARGE = "c0ffee00-0000-4000-8000-00000000c4a6"
CARD_DROP = "c0ffee00-0000-4000-8000-00000000d40b"


def _card_born_drop(at_ms=136000, offset_ms=0):
    """A charge + drop of his placed on SPECTRA's trigger card: in the fired
    copy only — no profile row, no ledger entry (profile_sync_ledger.py's
    card-born population). No detection sits near it on Pop Off."""
    from spectra.models.trigger import SpectraTrigger
    from spectra.services import trigger_store

    def row(tid, cls, ms):
        return SpectraTrigger.model_validate({
            "id": tid, "timestamp_ms": ms, "enabled": True, "source": "authored",
            "action": {"kind": "fire_response", "event_class": cls, "intensity": 0.8},
            "trigger_offset_ms": offset_ms})
    trigger_store.apply_batch(POP_OFF, [row(CARD_CHARGE, "charge", at_ms - 6000),
                                        row(CARD_DROP, "drop", at_ms)], [])


def test_a_card_born_drop_is_named_placed_by_hand_on_the_panels_provenance(stores):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import spectra.api.drop_sequences as api
    _card_born_drop()
    app = FastAPI()
    app.include_router(api.router)
    body = TestClient(app).get("/api/drop-sequences/provenance",
                               params={"uri": POP_OFF}).json()
    by_id = {t["id"]: t for t in body["triggers"]}
    for tid in (CARD_CHARGE, CARD_DROP):
        assert by_id[tid]["why"] == "spectra_card"
        assert by_id[tid]["remove_would"] == "delete"
    # the profile's own rows are still the root's answer, each once
    assert len(by_id) == len(body["triggers"])
    assert any(t["why"] == "by_hand" for t in body["triggers"])


def test_removing_a_card_born_drop_deletes_it_from_the_fired_copy_and_undo_puts_it_back(stores):
    _card_born_drop()
    fired_before = _fired(POP_OFF)
    profile_before = _profile_bytes(stores, POP_OFF)
    edits_before = ds.edits(POP_OFF)
    row = _row(POP_OFF, 136000)
    assert row["charge"]["id"] == CARD_CHARGE and row["drop"]["id"] == CARD_DROP
    res = _run(drop_panel.remove(POP_OFF, row["key"]))
    assert {c["id"] for c in res.profile} == {CARD_CHARGE, CARD_DROP}
    assert {c["store"] for c in res.profile} == {drop_panel.FIRED}
    assert {c["did"] for c in res.profile} == {"deleted"}
    assert "deleted 2 triggers you placed by hand" in res.said
    fired = _fired(POP_OFF)
    assert CARD_CHARGE not in fired and CARD_DROP not in fired
    # exactly those two: every other fired row, his profile and his drop
    # edits are untouched (no root call was needed, so no whole-song sync)
    assert {k: v for k, v in fired_before.items()
            if k not in (CARD_CHARGE, CARD_DROP)} == fired
    assert _profile_bytes(stores, POP_OFF) == profile_before
    assert ds.edits(POP_OFF)["rev"] == edits_before["rev"]
    _undo(POP_OFF, res)
    assert _fired(POP_OFF) == fired_before
    assert _row(POP_OFF, 136000)["drop"]["id"] == CARD_DROP


def test_a_card_born_undo_refuses_a_row_that_changed_since(stores):
    from spectra.services import trigger_store
    _card_born_drop()
    row = _row(POP_OFF, 136000)
    res = _run(drop_panel.set_parts(POP_OFF, row["key"], {"charge": "off"}))
    assert [c["did"] for c in res.profile] == ["deleted"]
    # someone puts a different charge back under the same id meanwhile
    _card_born_drop()
    with pytest.raises(ds.EditConflict):
        _undo(POP_OFF, res)
    assert trigger_store.get(POP_OFF, CARD_CHARGE) is not None


def test_a_dragged_drop_moves_its_stored_time_by_its_own_offset_less(stores):
    """The handle sits at the moment a trigger FIRES — its stored time plus
    its own trigger_offset_ms. Dragging it to a moment stores that moment
    less the offset, so it fires exactly where it was dropped."""
    from spectra.services import trigger_store
    _card_born_drop(at_ms=136000, offset_ms=-250)
    row = _row(POP_OFF, 135750)
    assert row["drop"]["offset_ms"] == -250
    _run(drop_panel.move_handles(POP_OFF, row["key"], {"drop": 137000}))
    t = trigger_store.get(POP_OFF, CARD_DROP)
    assert t.timestamp_ms == 137250 and t.trigger_offset_ms == -250
    assert _row(POP_OFF, 137000)["drop"]["id"] == CARD_DROP


def test_his_profile_drop_with_an_offset_moves_in_his_profile_by_the_offset_less(stores):
    from spectra.services import trigger_store
    row = _row(POP_OFF, 59603)
    tid = row["drop"]["id"]
    t = trigger_store.get(POP_OFF, tid)
    # an offset authored on SPECTRA's own card (the sync carries it over)
    trigger_store.upsert(POP_OFF, t.model_copy(update={"trigger_offset_ms": 120}))
    row = _row(POP_OFF, 59723)
    _run(drop_panel.move_handles(POP_OFF, row["key"], {"drop": 60000}))
    prof = next(x for x in _profile(stores, POP_OFF)["triggers"] if x["id"] == tid)
    assert prof["timestamp_ms"] == 59880
    t = trigger_store.get(POP_OFF, tid)
    assert (t.timestamp_ms, t.trigger_offset_ms) == (59880, 120)
    assert _row(POP_OFF, 60000)["drop"]["id"] == tid


def test_sonic_names_a_card_born_drop_as_placed_by_hand_and_removes_it(stores):
    from spectra.services import drop_console, trigger_store
    _card_born_drop()
    ask = _run(drop_console._op_remove(your_drop_s=136.0, uri=POP_OFF))
    assert ask["status"] == "needs_confirmation"
    assert "delete your charge at 130.0 s (you placed it by hand)" in ask["question"]
    assert "delete your drop at 136.0 s (you placed it by hand)" in ask["question"]
    done = _run(drop_console._op_remove(your_drop_s=136.0, uri=POP_OFF,
                                        confirm_id=ask["confirm_id"]))
    assert done["status"] == "applied"
    assert trigger_store.get(POP_OFF, CARD_DROP) is None
    assert _run(drop_console._op_undo(uri=POP_OFF))["status"] == "applied"
    assert trigger_store.get(POP_OFF, CARD_DROP) is not None


def test_sonic_never_guesses_a_trigger_it_cannot_place(stores):
    """A row member neither the profile nor the card-born reading names
    gets the general rule in Sonic's question — never "imported"."""
    from spectra.services import drop_console
    row = _row(POP_OFF, 59603)
    words = drop_console._what_happens(row, {"triggers": []}, ("drop",))
    assert words == ["take out your drop at 59.6 s (deleted if you placed it by hand, "
                     "switched off if it was imported)"]


def test_a_sync_that_did_not_land_is_said_never_a_silent_half(stores, monkeypatch):
    """The root route writes his profile, then runs the whole-song sync. When
    that sync does not land, the profile changed but the copy the room fires
    from did not — the panel's words say so instead of claiming it done."""
    from services import spectra_trigger_sync_client

    async def unreachable(uri, triggers, delete_missing=True):
        return {"status": "unreachable", "detail": "SPECTRA did not answer"}
    monkeypatch.setattr(spectra_trigger_sync_client, "sync_song", unreachable)
    row = _row(POP_OFF, 59603)
    res = _run(drop_panel.remove(POP_OFF, row["key"]))
    assert all(c.get("unsynced") == "unreachable" for c in res.profile)
    assert "has not caught up (sync: unreachable)" in res.said
    # the profile half did land; the fired copy still holds the trigger
    assert all(t["id"] != row["drop"]["id"] for t in _profile(stores, POP_OFF)["triggers"])
    assert row["drop"]["id"] in _fired(POP_OFF)
