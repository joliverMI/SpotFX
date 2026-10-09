"""Scene-change arms (Light Show sets armed on "next scene change", and a
Show Sequence's "wait N scene changes") must still release while Force
Scene holds the room (2026-10-09, his report: "i have a show set armed to
fire on next scene change, but it seems to keep 'reseting'. It keeps
saying Scene change at least: xx. But [nothing] happens and it resets that
timer.").

Root cause: Force Scene's redirect (scene_sequencer.fire_scene_by_id)
reasserts the SAME pinned scene on every automatic pick, so the scene
object engine.on_scene_fired saw never changed — show_arms.on_scene_change
compared the pinned scene against itself and never saw a "real" change,
even though fire_scene_by_id's own dwell.note_fired() call (the thing that
was resetting the "Scene change at least" readout) ran on every one of
those re-fires. His ruling, verbatim: "do 1" — the arm still releases at
the moment a scene change would have happened; the room keeps wearing the
pinned scene.

Fix: scene_sequencer.fire_scene_by_id now captures the scene id a caller
actually asked for, BEFORE Force Scene substitutes the pinned scene, and
threads it through scene_compiler.fire_scene -> engine.on_scene_fired as
requested_scene_id — the id show_arms.on_scene_change now compares against
the previous scene, instead of the (unchanging, pinned) one that actually
fired.

Runs the real pipeline (fire_scene_by_id -> scene_compiler.fire_scene ->
engine.on_scene_fired -> show_arms.on_scene_change/show_actions.fire),
against the `room` fixture's fake live host (fx_seam writes go nowhere
real). No live access.
"""
from __future__ import annotations

import asyncio

import pytest

from spectra.models.light_show import ActionSet, ShowAction
from spectra.models.scene import SceneV2
from spectra.services import room_controls as rc
from spectra.services import scene_store, show_arms, show_sequence, show_store
from spectra.services.engine import conductor
from spectra.services.scene_sequencer import fire_scene_by_id
from tests.test_light_show import A, Registry, room  # noqa: F401  (fixture)


@pytest.fixture(autouse=True)
def _isolated_room_color(tmp_path, monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "ROOM_COLOR_FILE", tmp_path / "room_color.json")


def _run(coro):
    return asyncio.run(coro)


async def _settle(n=20):
    for _ in range(n):
        await asyncio.sleep(0)


def _scene(name):
    s = SceneV2(name=name)
    scene_store.save(s)
    return s


def _set(name="Blackout"):
    return show_store.put_set(ActionSet(name=name, actions=[
        A("device_state", target={"kind": "category", "id": "Strips"},
          state="dark", fade_ms=0)]))


def test_armed_set_fires_at_the_suppressed_scene_change_moment(room):
    pinned = _scene("Pinned")
    other = _scene("Other")

    # Establish the room's showing scene as `pinned`, Force Scene still off.
    async def establish():
        await fire_scene_by_id(pinned.id, intensity=0.5)
        await _settle()
    _run(establish())
    assert conductor.scene.id == pinned.id

    rc.save_room_controls(rc.RoomControlState(
        force_scene_enabled=True, force_scene_scene_id=pinned.id))

    s = _set()
    arm = show_arms.arm(set_id=s.id, on="scene_change")

    # An automatic pick wants `other` — Force Scene redirects it to `pinned`.
    async def go():
        await fire_scene_by_id(other.id, intensity=0.6)
        await _settle()
    _run(go())

    assert conductor.scene.id == pinned.id, \
        "the scene itself must stay pinned — never other.id"

    fired = next(a for a in show_store.state().arms if a.id == arm.id)
    assert fired.status == "fired" and fired.fire_count == 1, \
        "the arm must release at the moment the scene change would have happened"


def test_without_force_scene_behaviour_is_unchanged(room):
    from spectra.services import dwell

    first = _scene("First")
    second = _scene("Second")

    async def establish():
        await fire_scene_by_id(first.id, intensity=0.5)
        await _settle()
    _run(establish())
    assert conductor.scene.id == first.id

    s = _set()
    arm = show_arms.arm(set_id=s.id, on="scene_change")

    # Unrelated to Force Scene: the previous fire's own minimum dwell —
    # reset it so this probes the (unchanged) scene-change path alone,
    # same convention test_room_controls.py's own Force Scene tests use.
    dwell.reset()

    async def go():
        await fire_scene_by_id(second.id, intensity=0.6)
        await _settle()
    _run(go())

    assert conductor.scene.id == second.id, \
        "with no pin, the room really does change to the requested scene"
    fired = next(a for a in show_store.state().arms if a.id == arm.id)
    assert fired.status == "fired" and fired.fire_count == 1


def test_a_forced_refire_of_the_same_scene_never_falsely_releases_the_arm(room):
    """Requesting exactly the pinned scene — no suppressed change at all —
    must not release the arm a second time."""
    pinned = _scene("Pinned")

    async def establish():
        await fire_scene_by_id(pinned.id, intensity=0.5)
        await _settle()
    _run(establish())

    rc.save_room_controls(rc.RoomControlState(
        force_scene_enabled=True, force_scene_scene_id=pinned.id))

    s = _set()
    arm = show_arms.arm(set_id=s.id, on="scene_change")

    async def go():
        # The caller happens to ask for the pinned scene itself — nothing
        # was ever going to change.
        await fire_scene_by_id(pinned.id, intensity=0.5)
        await _settle()
    _run(go())

    still_armed = next(a for a in show_arms.active_arms() if a.id == arm.id)
    assert still_armed.fire_count == 0


def test_sequence_wait_counts_a_force_scene_suppressed_change(room, monkeypatch):
    """A Show Sequence's "wait N scene changes" item must also count the
    suppressed moment, not just a hand-made arm."""
    pinned = _scene("Pinned")
    other = _scene("Other")

    from spectra.models.light_show import SequenceItem, SequenceWait, ShowSequence
    from spectra.services import show_actions

    fired_sets: list[str] = []

    async def fake_fire_set(set_id, *, source="button"):
        s = show_store.find_set(set_id)
        fired_sets.append(s.name)
        return {"id": "run-1", "state": "done"}
    monkeypatch.setattr(show_actions, "fire_set", fake_fire_set)
    monkeypatch.setattr(show_arms, "current_uri", lambda: "spotify:track:one")
    monkeypatch.setattr(show_arms, "is_playing", lambda: True)

    seq_set = show_store.put_set(ActionSet(name="A", actions=[
        A("pause", seconds=1)]))
    followup = show_store.put_set(ActionSet(name="B", actions=[
        A("pause", seconds=1)]))
    seq = show_store.put_sequence(ShowSequence(name="Seq", items=[
        SequenceItem(kind="set", set_id=seq_set.id, arm="instant"),
        SequenceItem(kind="wait", wait=SequenceWait(kind="trigger_count",
                                                     trigger="scene_change", count=1)),
        SequenceItem(kind="set", set_id=followup.id, arm="instant"),
    ]))

    async def establish():
        await fire_scene_by_id(pinned.id, intensity=0.5)
        await _settle()
    _run(establish())

    rc.save_room_controls(rc.RoomControlState(
        force_scene_enabled=True, force_scene_scene_id=pinned.id))

    async def go():
        show_sequence.start(seq.id)
        await _settle()
        assert fired_sets == ["A"]
        assert show_sequence.run().index == 1
        # The suppressed request for `other` must count for the wait even
        # though the room keeps wearing `pinned`.
        await fire_scene_by_id(other.id, intensity=0.6)
        await _settle()
    _run(go())

    assert conductor.scene.id == pinned.id, "scene stayed pinned"
    assert fired_sets == ["A", "B"], \
        "the Wait must have counted the suppressed scene change"
