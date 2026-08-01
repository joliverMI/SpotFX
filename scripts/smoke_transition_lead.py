"""Offline smoke: phased-transition lead computation in the planner.

Builds real MusicEvent/MorphStepAction objects against a fake LedFX virtual
cache and checks _entry_transition_lead_ms / _anchor_morph_steps for:
  * bus path: lead = anchor_frac × the virtual's transition_time
  * transition_mode "None" → no lead
  * particle↔particle switches → no lead
  * scene-override path: lead = anchor_frac × max ramp_ms
  * delayed sequence children never produce a lead
Run: .venv/bin/python scripts/smoke_transition_lead.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.state import state  # noqa: E402
from models.music_event import (  # noqa: E402
    AspectValue, MorphScope, MorphStepAction, MorphTarget, MusicEvent,
)
from services.trigger_engine import TriggerEngine, _PlanEntry  # noqa: E402


def _cache(vid: str, cur_type: str, t_time: float, mode: str = "Add") -> None:
    state.ledfx_virtual_cache[vid] = {
        "effect": {"type": cur_type, "config": {}},
        "config": {"transition_time": t_time, "transition_mode": mode},
    }


def _switch_step(vid: str, new_type: str, ramp_ms=None) -> MorphStepAction:
    return MorphStepAction(
        ramp_ms=ramp_ms,
        targets=[MorphTarget(
            scope=MorphScope(virtual_ids=[vid]),
            aspect="effect",
            absolute_value=AspectValue(effect_type=new_type),
        )],
    )


def _entry(event: MusicEvent, action=None, is_root=True) -> _PlanEntry:
    return _PlanEntry(
        fire_at_ms=10_000, event=event, preselected_action=action,
        is_root=is_root,
    )


def main() -> int:
    engine = TriggerEngine()
    failures = []

    # resolve_scope drops vids not imported into device categories — use a real one
    from services import effect_params as _ep
    imported = _ep.get_all_virtual_ids()
    if not imported:
        print("no imported virtuals in config/effect_params.json — cannot test")
        return 1
    global VID
    VID = imported[0]
    print(f"using imported virtual: {VID}")

    def check(name, got, want):
        ok = got == want
        print(f"{'PASS' if ok else 'FAIL'}  {name}: lead={got} (want {want})")
        if not ok:
            failures.append(name)

    # 1) bus path: radial → blackhole on a 1.5 s crossfade → 0.45 × 1500 = 675
    _cache(VID, "radial", 1.5)
    ev = MusicEvent(id="e1", name="t", event_type="single")
    a = _switch_step(VID, "blackhole")
    check("radial→blackhole bus 1.5s", engine._entry_transition_lead_ms(_entry(ev, a)), 675)

    # 2) transition_mode None → no crossfade → no lead
    _cache(VID, "radial", 1.5, mode="None")
    check("mode=None", engine._entry_transition_lead_ms(_entry(ev, a)), 0)

    # 3) particle → particle: instant adoption, no lead
    _cache(VID, "blackhole", 1.5)
    a2 = _switch_step(VID, "orbits")
    check("blackhole→orbits", engine._entry_transition_lead_ms(_entry(ev, a2)), 0)

    # 4) pacman → fireworks, 2 s crossfade → 900
    _cache(VID, "pacman", 2.0)
    a3 = _switch_step(VID, "fireworks")
    check("pacman→fireworks bus 2s", engine._entry_transition_lead_ms(_entry(ev, a3)), 900)

    # 5) scene-override: crossfade = max ramp (1200) not the virtual config
    _cache(VID, "orbits", 9.9)
    ev_so = MusicEvent(
        id="e2", name="t", event_type="single", scene_override=True,
        actions=[_switch_step(VID, "radial", ramp_ms=1200)],
    )
    e = _entry(ev_so, ev_so.actions[0])
    check("orbits→radial scene-override ramp 1200",
          engine._entry_transition_lead_ms(e), 540)

    # 6) same switch in a DELAYED sequence child must not shift the entry
    from models.music_event import SequenceChild, SequenceGroupAction
    ev_seq = MusicEvent(id="e3", name="t", event_type="single")
    grp = SequenceGroupAction(
        timing="ms",
        children=[SequenceChild(delay_ms=800, actions=[_switch_step(VID, "radial")])],
    )
    check("delayed seq child", engine._entry_transition_lead_ms(_entry(ev_seq, grp)), 0)

    # ── scene groups ────────────────────────────────────────────────────
    import services.trigger_engine as te
    from models.music_event import EventRefAction, SceneGroupMember

    # Fake event store: a setter composite behind a ref, two scene_update
    # members, and the group itself.
    setter = MusicEvent(
        id="setter1", name="Radial Setter", event_type="composite",
        root=SequenceGroupAction(  # placeholder, replaced below if parallel exists
            timing="ms",
            children=[SequenceChild(delay_ms=0, actions=[_switch_step(VID, "radial")])],
        ),
    )
    from models.music_event import MorphLane
    m_a = MusicEvent(
        id="member-a", name="Scene A", event_type="scene_update",
        morph_lanes=[MorphLane(name="First", alternatives=[
            EventRefAction(event_id="setter1")])],
    )
    m_b = MusicEvent(id="member-b", name="Scene B", event_type="scene_update")
    group = MusicEvent(
        id="grp1", name="Test Group", event_type="scene_group",
        scene_group_mode="cycle",
        scene_group_members=[SceneGroupMember(event_id="member-a"),
                             SceneGroupMember(event_id="member-b")],
    )
    fake_store = {e.id: e for e in (setter, m_a, m_b, group)}
    real_get_event = te.get_event
    te.get_event = lambda eid: fake_store.get(eid) or real_get_event(eid)
    try:
        # 7) peek is pure: same result twice, cursors untouched
        p1 = engine._peek_scene_group_fire(group)
        p2 = engine._peek_scene_group_fire(group)
        ok = (p1 and p2 and p1["member_id"] == p2["member_id"] == "member-a"
              and engine._scene_cursor.get("grp1") is None)
        print(f"{'PASS' if ok else 'FAIL'}  peek pure + deterministic: {p1 and p1['member_id']}")
        if not ok:
            failures.append("peek pure")

        # 8) lead flows through a scene_group entry via the peeked member's
        #    First-lane event_ref → composite switch (the real library shape)
        _cache(VID, "blackhole", 1.5)
        picked = m_a.morph_lanes[0].alternatives[0]
        e_grp = _PlanEntry(
            fire_at_ms=10_000, event=group, is_root=True,
            preselected_scene_picks=[(0, picked)],
            scene_group_pick=p1,
        )
        check("scene_group ref'd setter blackhole→radial",
              engine._entry_transition_lead_ms(e_grp), 675)

        # 9) commit honors the peek exactly (fire-time path's cursor write)
        engine._commit_scene_group_cursor("grp1", p1["idx"], p1["dir"], p1["prev_cur"])
        ok = engine._scene_cursor.get("grp1") == p1["idx"]
        print(f"{'PASS' if ok else 'FAIL'}  commit writes peeked cursor idx={p1['idx']}")
        if not ok:
            failures.append("commit cursor")

        # 10) select == peek+commit: next select picks member-b (cycle)
        nxt = engine._select_scene_group_member(group)
        ok = nxt is not None and nxt.id == "member-b" and engine._scene_cursor.get("grp1") == 1
        print(f"{'PASS' if ok else 'FAIL'}  select after commit cycles to member-b")
        if not ok:
            failures.append("select cycles")
    finally:
        te.get_event = real_get_event

    print("---")
    if failures:
        print(f"{len(failures)} FAILED: {failures}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
