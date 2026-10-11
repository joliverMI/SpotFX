"""SETS THAT CALL SETS (spectra/services/show_refs.py is the binding
statement): a "Run another set" step runs the called set's steps INLINE at
that point, a reference not a copy, never in a loop, and a missing set is a
named failure. Proven against the real stores and the real executor, with
an order-recording action kind standing in for the room (no live access).
"""
from __future__ import annotations

import asyncio

import pytest

from spectra.models.light_show import ActionSet, SequenceItem, ShowAction, ShowSequence
from spectra.services import show_actions, show_refs, show_store


@pytest.fixture
def order():
    """A `mark` action kind that records the order steps actually run in."""
    seen: list[str] = []

    async def apply(p, ctx):
        seen.append(p["tag"])
        return show_actions.Outcome("applied", f"marked {p['tag']}")
    show_actions.register(show_actions.ActionKind(
        name="mark", label="Mark", group="control",
        params=[show_actions.Param("tag", "text", required=True)],
        help="", restore="", apply=apply, needs_room=False))
    yield seen
    show_actions.ACTION_KINDS.pop("mark", None)


def M(tag):
    return ShowAction(kind="mark", params={"tag": tag})


def CALL(set_id, **kw):
    return ShowAction(kind="call_set", params={"set": set_id}, **kw)


def put(name, actions, sid=None):
    s = ActionSet(name=name, actions=actions, **({"id": sid} if sid else {}))
    return show_store.put_set(s)


def fire_set(sid):
    async def go():
        run = await show_actions.fire_set(sid)
        for r in show_actions._runs:
            if r.task is not None:
                await r.task
        return next(r for r in show_actions._runs if r.id == run["id"]).as_dict()
    return asyncio.run(go())


# ── inline order ───────────────────────────────────────────────────────────

def test_a_call_runs_the_called_sets_steps_inline_in_order(order):
    defaults = put("Defaults", [M("d1"), M("d2")])
    outer = put("Outer", [M("o1"), CALL(defaults.id), M("o2")])
    run = fire_set(outer.id)
    assert order == ["o1", "d1", "d2", "o2"]
    assert [s["label"] for s in run["steps"]] == ["Mark"] * 4
    assert [s["via"] for s in run["steps"]] == [[], ["Defaults"], ["Defaults"], []]
    assert run["state"] == "done"


def test_nested_calls_expand_depth_first(order):
    inner = put("Inner", [M("i")])
    mid = put("Mid", [M("m1"), CALL(inner.id), M("m2")])
    outer = put("Outer", [CALL(mid.id), M("o")])
    run = fire_set(outer.id)
    assert order == ["m1", "i", "m2", "o"]
    assert run["steps"][1]["via"] == ["Mid", "Inner"]


def test_calling_the_same_set_twice_gives_two_distinct_records(order):
    d = put("Defaults", [M("d")])
    outer = put("Outer", [CALL(d.id), CALL(d.id)])
    run = fire_set(outer.id)
    assert order == ["d", "d"]
    ids = [s["action_id"] for s in run["steps"]]
    assert len(set(ids)) == 2


def test_a_pause_inside_a_called_set_pauses_the_caller(order, monkeypatch):
    slept = []

    async def fake_sleep(s):
        slept.append((s, list(order)))
    monkeypatch.setattr(show_actions.asyncio, "sleep", fake_sleep)
    d = put("Defaults", [M("d1"), ShowAction(kind="pause", params={"seconds": 1}), M("d2")])
    outer = put("Outer", [CALL(d.id), M("o")])
    fire_set(outer.id)
    assert order == ["d1", "d2", "o"]
    assert slept == [(1.0, ["d1"])]


def test_room_settings_coalesce_across_the_call_boundary(monkeypatch):
    """Inline means inline: the caller's later setting and the callee's
    settings land in ONE save, the caller's value winning."""
    from spectra.services import room_controls, show_output
    monkeypatch.setattr(show_output, "refusal", lambda: None)
    patches = []

    async def apply_patch(body, **kw):
        patches.append(dict(body))
        return {}
    monkeypatch.setattr(room_controls, "apply_patch", apply_patch)
    d = put("Defaults", [ShowAction(kind="display_mode", params={"mode": "dark"}),
                         ShowAction(kind="scene_change_mode", params={"mode": "full"})])
    outer = put("Outer", [CALL(d.id), ShowAction(kind="display_mode", params={"mode": "light"})])
    run = fire_set(outer.id)
    assert patches == [{"display_mode": "light", "scene_change_mode": "full"}]
    assert all(s["status"] == "applied" for s in run["steps"])
    assert any("step 2 changes display_mode again" in c
               for c in show_actions.conflicts(outer.actions, set_id=outer.id))


def test_edits_to_the_called_set_reach_every_caller(order):
    d = put("Defaults", [M("old")])
    a = put("A", [CALL(d.id)])
    b = put("B", [CALL(d.id)])
    put("Defaults", [M("new")], sid=d.id)
    fire_set(a.id)
    fire_set(b.id)
    assert order == ["new", "new"]


def test_a_switched_off_call_is_skipped_whole(order):
    d = put("Defaults", [M("d")])
    outer = put("Outer", [CALL(d.id, enabled=False), M("o")])
    run = fire_set(outer.id)
    assert order == ["o"]
    assert run["steps"][0]["status"] == "skipped"
    assert run["steps"][0]["label"] == "Run “Defaults”"


# ── cycles ─────────────────────────────────────────────────────────────────

def test_a_set_cannot_call_itself():
    s = put("Loop", [])
    with pytest.raises(show_refs.SetReferenceCycle, match="cannot call itself"):
        put("Loop", [CALL(s.id)], sid=s.id)
    assert show_store.get_set(s.id).actions == []


def test_an_indirect_cycle_is_refused_and_named():
    a = put("A", [])
    b = put("B", [CALL(a.id)])
    c = put("C", [CALL(b.id)])
    with pytest.raises(show_refs.SetReferenceCycle) as exc:
        put("A", [CALL(c.id)], sid=a.id)
    assert "“A” → “C” → “B” → “A”" in str(exc.value)
    assert show_store.get_set(a.id).actions == []


def test_a_diamond_is_not_a_cycle(order):
    d = put("D", [M("d")])
    b = put("B", [CALL(d.id)])
    c = put("C", [CALL(d.id)])
    a = put("A", [CALL(b.id), CALL(c.id)])
    fire_set(a.id)
    assert order == ["d", "d"]


def test_a_cycle_that_reached_the_file_fails_by_name_and_never_recurses(order):
    """A hand-edited file can hold a loop the save refused; the run must
    still terminate and say why."""
    a = put("A", [M("a")])
    b = put("B", [CALL(a.id), M("b")])
    lib = show_store.load_library()
    lib.sets[0].actions.append(CALL(b.id))
    show_store.save_library(lib)
    run = fire_set(a.id)
    assert order == ["a", "b"]
    bad = [s for s in run["steps"] if s["status"] == "failed"]
    assert len(bad) == 1 and "loop" in bad[0]["detail"]
    assert any("call itself" in p for p in show_actions.validate_set(
        show_store.get_set(a.id).actions, set_id=a.id))


def test_the_api_refuses_a_cycle_with_409():
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    c = TestClient(create_app())
    a = c.post("/api/light-show/sets", json={"name": "A", "actions": []}).json()
    b = c.post("/api/light-show/sets", json={
        "name": "B", "actions": [{"kind": "call_set", "params": {"set": a["id"]}}]}).json()
    r = c.post("/api/light-show/sets", json={
        "id": a["id"], "name": "A", "actions": [{"kind": "call_set", "params": {"set": b["id"]}}]})
    assert r.status_code == 409 and r.json()["reason"] == "cycle"
    assert "call itself" in r.json()["detail"]


# ── missing sets and delete warnings ───────────────────────────────────────

def test_a_call_to_a_deleted_set_fails_by_name(order):
    d = put("Defaults", [M("d")])
    outer = put("Outer", [CALL(d.id), M("o")])
    show_store.delete_set(d.id)
    run = fire_set(outer.id)
    assert order == ["o"]
    assert run["steps"][0]["status"] == "failed"
    assert "no longer exists" in run["steps"][0]["detail"]
    assert run["state"] == "partial"
    assert any("no longer exists" in p for p in show_actions.validate_set(outer.actions, set_id=outer.id))


def test_deleting_a_used_set_warns_until_forced():
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    c = TestClient(create_app())
    d = put("Defaults", [])
    put("Party", [CALL(d.id)])
    show_store.put_sequence(ShowSequence(name="Evening", items=[SequenceItem(kind="set", set_id=d.id)]))
    r = c.delete(f"/api/light-show/sets/{d.id}")
    assert r.status_code == 409 and r.json()["reason"] == "in_use"
    assert [u["name"] for u in r.json()["used_by"]] == ["Party"]
    assert [u["name"] for u in r.json()["used_in_sequences"]] == ["Evening"]
    assert show_store.get_set(d.id) is not None
    r = c.delete(f"/api/light-show/sets/{d.id}?force=true")
    assert r.status_code == 200 and show_store.get_set(d.id) is None
    # an unused set deletes with no warning
    lone = put("Lone", [])
    assert c.delete(f"/api/light-show/sets/{lone.id}").status_code == 200


def test_the_listing_carries_calls_and_used_by():
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    d = put("Defaults", [])
    a = put("A", [CALL(d.id)])
    sets = {s["name"]: s for s in TestClient(create_app()).get("/api/light-show/sets").json()["sets"]}
    assert sets["A"]["calls"] == [{"id": d.id, "name": "Defaults", "missing": False}]
    assert sets["Defaults"]["used_by"] == [{"id": a.id, "name": "A"}]
    assert "call_set" in {k["kind"] for k in show_actions.catalogue()["kinds"]}


def test_preview_lists_the_called_steps_under_their_call():
    d = put("Defaults", [ShowAction(kind="pause", params={"seconds": 2})])
    call = CALL(d.id)
    rows = show_actions.preview([call], set_id="x")
    assert rows[0]["top_id"] == call.id and rows[0]["via"] == ["Defaults"]
    assert rows[0]["change"] == "wait 2 s"


def test_an_arm_finishes_a_fade_inside_a_called_set_on_the_mark():
    from spectra.models.light_show import ShowArm
    from spectra.services import show_arms
    d = put("Defaults", [ShowAction(kind="level", params={
        "target": {"kind": "everything"}, "level": 0.5, "fade_in_ms": 1200})])
    outer = put("Outer", [CALL(d.id)])
    assert show_arms.lead_ms(ShowArm(set_id=outer.id, on="high")) == 1200


def test_sonic_reads_the_references():
    from spectra.services import show_console
    d = put("Defaults", [ShowAction(kind="pause", params={"seconds": 1})])
    put("A", [CALL(d.id), ShowAction(kind="pause", params={"seconds": 1})])
    sets = {s["name"]: s for s in show_console._op_list_show_sets()["sets"]}
    assert sets["A"]["calls"] == ["Defaults"] and sets["A"]["runs_steps"] == 2
    assert sets["Defaults"]["used_by"] == ["A"]
