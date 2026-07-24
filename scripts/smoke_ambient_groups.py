"""
Offline smoke test: per-group Ambient Mode + the off-fade handoff + catch-up.

Verifies services.ambient_mode.set_groups():
  1. want=None holds ALL resolved Hue groups (freeze → REST order per device);
  2. shrinking the set fades the released group on the bridge (dynamics
     payload toward the wake color at ambient_fade_brightness) BEFORE
     unfreezing it, then kicks the wake scene; the kept group stays frozen;
  3. want=set() releases everything (enabled=False committed);
  4. unknown group ids are ignored, not applied;
  5. transition_s per-call override is used and capped at 15 s;
  6. newly-held groups get a dynamics ramp-up, already-held groups re-assert
     instantly (no dynamics);
  7. _wake_fade_color() derives the wake scene's background_color;
  8. catch-up: the pre-wake music effect is captured and tweened back over
     ambient_catchup_s AFTER the wake kick (same effect type), set directly
     when the type differs, and skipped when catchup=0 or no active effect;
  9. stream heal: a released device whose bridge entertainment session is dead
     while its driving virtual is active (bulbs stuck on the ambient white —
     the 2026-07-24 LedFX-restart bug) gets freeze-cycled + wake + catch-up;
     no heal when the driving virtual is intentionally inactive or healthy.

No LedFX / Hue / disk writes: ledfx_client calls, _apply_hue, _wake_kick and
_commit_state are stubbed to recorders (so the real settings.json is never
touched — see smoke_morph_step's store-clobber lesson).

USAGE
  .venv/bin/python scripts/smoke_ambient_groups.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings                    # noqa: E402
import services.ambient_mode as am             # noqa: E402

CFGS = {
    "hue-lights": {"name": "Hue Lights", "ip_address": "1.1.1.1",
                   "username": "k", "entertainment_id": "e1"},
    "dining-hues": {"name": "Dining Hues", "ip_address": "2.2.2.2",
                    "username": "k", "entertainment_id": "e2"},
}

frozen: dict[str, bool] = {}
events: list[tuple] = []          # ordered ('freeze'|'rest'|'wake'|'commit'|'tween'|'direct', ...)
committed: list[list[str]] = []
ORIG_WAKE_COLOR = None            # real _wake_fade_color, saved before stubbing

stream_up: dict[str, bool] = {}   # bridge ip → entertainment session active
hues_virtual_active = True        # driving virtual state for _all_virtuals stub

MUSIC_EFFECT = {"type": "power", "config": {"background_color": "#00ff07", "brightness": 0.75}}
WAKE_SCENE = {"id": "wake-hues", "virtuals": {
    "hues": {"action": "activate", "type": "power",
             "config": {"background_color": "#ffb675", "gradient": "#fd1313"}},
    "hue-lights": {"action": "ignore", "type": "", "config": {}},
}}


def _set(key, val):
    object.__setattr__(settings, key, val)


def _reset():
    frozen.clear()
    events.clear()
    committed.clear()
    stream_up.clear()   # default healthy (True) via .get fallback


def _install_stubs():
    async def fake_resolve():
        return dict(CFGS)
    am._resolve_hue_cfgs = fake_resolve

    async def fake_freeze(did, want):
        frozen[did] = want
        events.append(("freeze", did, want))
        if not want:  # unfreezing re-arms the DTLS session → stream recovers
            stream_up[CFGS[did]["ip_address"]] = True
        return True
    am.ledfx_client.freeze_hue_device = fake_freeze

    async def fake_all_virtuals():
        return {"hues": {"active": hues_virtual_active, "effect": {"type": "power"},
                         "segments": [["hue-lights", 0, 9], ["dining-hues", 0, 6]]}}
    am._all_virtuals = fake_all_virtuals

    async def fake_stream_active(cfg):
        return stream_up.get(cfg["ip_address"], True)
    am._stream_active = fake_stream_active

    async def fake_get_frozen(did):
        return frozen.get(did, False)
    am.ledfx_client.get_hue_frozen = fake_get_frozen

    async def fake_apply(cfg, body=None):
        if body is None:
            body = am._light_payload()
        events.append(("rest", cfg["ip_address"], body))
        return 3
    am._apply_hue = fake_apply

    async def fake_wake():
        events.append(("wake",))
        return {"status": "on"}
    am._wake_kick = fake_wake

    async def fake_commit(want):
        events.append(("commit", sorted(want)))
        committed.append(sorted(want))
    am._commit_state = fake_commit

    global ORIG_WAKE_COLOR
    ORIG_WAKE_COLOR = am._wake_fade_color

    async def fake_wake_color():
        return "#ffb675"
    am._wake_fade_color = fake_wake_color

    # Catch-up plumbing: real _capture_wake_targets/_catchup run against these.
    async def fake_scenes():
        return [WAKE_SCENE]
    am.ledfx_client.get_scenes = fake_scenes

    async def fake_get_virtual(vid):
        return {vid: {"active": True, "effect": dict(MUSIC_EFFECT)}}
    am.ledfx_client.get_virtual = fake_get_virtual

    async def fake_tween(vid, etype, config, transition_ms, easing="linear"):
        events.append(("tween", vid, etype, dict(config), transition_ms))
    am.ledfx_client.set_virtual_effect_tween = fake_tween

    async def fake_direct(vid, etype, config):
        events.append(("direct", vid, etype, dict(config)))
        return True
    am.ledfx_client._set_virtual_effect_direct = fake_direct


async def main() -> int:
    _install_stubs()
    _set("ambient_transition_s", 0.05)   # keep the real sleep tiny
    _set("ambient_fade_brightness", 35)
    _set("ambient_brightness", 100)
    _set("ambient_color_mode", "white")
    _set("ambient_wake_scene", "wake-hues")
    _set("ambient_catchup_s", 5.0)

    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f" — {detail}" if detail else ""))
        ok = ok and cond

    # ── 1) want=None → all groups held, freeze precedes REST per device ─────
    _reset()
    res = await am.set_groups(None)
    check("all groups held", res["ambient_groups"] == ["dining-hues", "hue-lights"])
    check("both frozen", frozen == {"hue-lights": True, "dining-hues": True})
    fz = [i for i, e in enumerate(events) if e[0] == "freeze" and e[2]]
    rs = [i for i, e in enumerate(events) if e[0] == "rest"]
    check("freeze before REST", fz and rs and min(fz) < min(rs))
    check("committed all", committed and committed[-1] == ["dining-hues", "hue-lights"])
    ramps = [e[2] for e in events if e[0] == "rest" and "dynamics" in e[2]]
    check("new groups ramp up", len(ramps) == 2,
          f"{len(ramps)} dynamics payloads")

    # ── 2) shrink to dining only → hue-lights fades, then unfreezes, wake ───
    _reset()
    frozen.update({"hue-lights": True, "dining-hues": True})
    res = await am.set_groups({"dining-hues"})
    check("dining kept", res["ambient_groups"] == ["dining-hues"])
    check("hue-lights released", res["released"] == ["hue-lights"])
    check("dining still frozen", frozen["dining-hues"] is True)
    check("hue-lights unfrozen", frozen["hue-lights"] is False)
    fades = [(i, e) for i, e in enumerate(events)
             if e[0] == "rest" and e[1] == "1.1.1.1" and "dynamics" in e[2]]
    unfz = [i for i, e in enumerate(events) if e == ("freeze", "hue-lights", False)]
    check("fade sent", bool(fades))
    check("fade BEFORE unfreeze", fades and unfz and fades[0][0] < unfz[0])
    if fades:
        body = fades[0][1][2]
        check("fade → wake color", "color" in body and "xy" in body["color"])
        check("fade brightness 35", body["dimming"]["brightness"] == 35.0)
        check("fade duration 50ms", body["dynamics"]["duration"] == 50)
    check("wake kicked after release", ("wake",) in events
          and events.index(("wake",)) > (unfz[0] if unfz else -1))
    tweens = [(i, e) for i, e in enumerate(events) if e[0] == "tween"]
    check("catch-up tween fired", bool(tweens))
    if tweens:
        i, (_k, vid, etype, cfg, ms) = tweens[0]
        check("tween AFTER wake", i > events.index(("wake",)))
        check("tween eases hues back to captured music look",
              vid == "hues" and etype == "power" and cfg == MUSIC_EFFECT["config"])
        check("tween uses ambient_catchup_s", ms == 5000)
    # kept group re-asserts instantly (no dynamics)
    dining_rest = [e for e in events if e[0] == "rest" and e[1] == "2.2.2.2"]
    check("kept group re-asserts w/o ramp",
          dining_rest and all("dynamics" not in e[2] for e in dining_rest))

    # ── 3) want=set() → everything released ─────────────────────────────────
    _reset()
    frozen.update({"hue-lights": True, "dining-hues": True})
    res = await am.set_groups(set())
    check("all released", res["ambient_groups"] == [] and not any(frozen.values()))
    check("committed empty", committed[-1] == [])

    # ── 4) unknown ids ignored ───────────────────────────────────────────────
    _reset()
    res = await am.set_groups({"dining-hues", "porch-rail"})
    check("unknown id dropped", res["ambient_groups"] == ["dining-hues"])
    check("unknown never frozen", "porch-rail" not in frozen)

    # ── 5) transition override + cap ─────────────────────────────────────────
    _reset()
    frozen.update({"hue-lights": True})
    await am.set_groups(set(), transition_s=0.08)
    body = next(e[2] for e in events if e[0] == "rest" and "dynamics" in e[2])
    check("per-call transition used", body["dynamics"]["duration"] == 80)
    _reset()
    frozen.update({"hue-lights": True})
    t0 = asyncio.get_event_loop().time()
    # cap: ask for 999s — must clamp to 15; stub the sleep so the test is fast
    real_sleep = asyncio.sleep
    slept: list[float] = []

    async def fake_sleep(s):
        slept.append(s)
        await real_sleep(0)
    am.asyncio.sleep = fake_sleep
    try:
        await am.set_groups(set(), transition_s=999)
    finally:
        am.asyncio.sleep = real_sleep
    check("transition capped at 15s", slept and max(slept) == 15.0,
          f"slept={slept} ({asyncio.get_event_loop().time() - t0:.2f}s wall)")

    # ── 6) catch-up edge cases ───────────────────────────────────────────────
    # Different effect type → direct set (normal crossfade), no tween.
    _reset()
    frozen.update({"hue-lights": True})
    MUSIC_EFFECT["type"] = "melt"
    await am.set_groups(set())
    check("type mismatch → direct set", any(
        e[0] == "direct" and e[1] == "hues" and e[2] == "melt" for e in events)
        and not any(e[0] == "tween" for e in events))
    MUSIC_EFFECT["type"] = "power"

    # catchup 0 → no ease-back at all.
    _reset()
    frozen.update({"hue-lights": True})
    _set("ambient_catchup_s", 0.0)
    await am.set_groups(set())
    check("catchup=0 skips ease-back",
          not any(e[0] in ("tween", "direct") for e in events))
    _set("ambient_catchup_s", 5.0)

    # Per-call catchup override.
    _reset()
    frozen.update({"hue-lights": True})
    await am.set_groups(set(), catchup_s=2.5)
    ms = next((e[4] for e in events if e[0] == "tween"), None)
    check("per-call catchup_s used", ms == 2500, f"ms={ms}")

    # No active effect on the wake virtual → nothing captured, no ease-back.
    _reset()
    frozen.update({"hue-lights": True})

    async def dark_virtual(vid):
        return {vid: {"active": False, "effect": {}}}
    am.ledfx_client.get_virtual = dark_virtual
    await am.set_groups(set())
    check("no active effect → no ease-back",
          not any(e[0] in ("tween", "direct") for e in events))

    # ── 7) stream heal: dead session on a released device ────────────────────
    global hues_virtual_active
    async def fake_get_virtual2(vid):
        return {vid: {"active": True, "effect": dict(MUSIC_EFFECT)}}
    am.ledfx_client.get_virtual = fake_get_virtual2  # undo dark_virtual stub

    real_sleep2 = asyncio.sleep

    async def fast_sleep(s):
        await real_sleep2(0)
    am.asyncio.sleep = fast_sleep
    try:
        # hue-lights bridge session dead, driving virtual active → heal.
        _reset()
        stream_up["1.1.1.1"] = False
        await am.set_groups(set())
        fz_on = [i for i, e in enumerate(events) if e == ("freeze", "hue-lights", True)]
        fz_off = [i for i, e in enumerate(events) if e == ("freeze", "hue-lights", False)]
        wk = [i for i, e in enumerate(events) if e == ("wake",)]
        check("heal freeze-cycles the stuck device",
              fz_on and fz_off and fz_on[0] < fz_off[0])
        check("heal wake-kicks after the cycle", wk and wk[0] > fz_off[0])
        check("heal eases back via catch-up", any(e[0] == "tween" for e in events))
        check("stream recovered", stream_up.get("1.1.1.1") is True)

        # Driving virtual intentionally inactive (off-scene) → never heal.
        _reset()
        stream_up["1.1.1.1"] = False
        hues_virtual_active = False
        await am.set_groups(set())
        check("no heal when driving virtual inactive",
              not any(e[0] == "freeze" for e in events)
              and ("wake",) not in events)
        hues_virtual_active = True

        # Healthy streams → no heal on a plain no-op reconcile.
        _reset()
        await am.set_groups(set())
        check("no heal when streams healthy",
              not any(e[0] == "freeze" for e in events))
    finally:
        am.asyncio.sleep = real_sleep2

    # ── 8) wake fade color derivation (real impl, stubbed scenes) ────────────
    async def fake_scenes():
        return [{"id": "wake-hues", "virtuals": {
            "hues": {"action": "activate", "type": "power",
                     "config": {"background_color": "#ffb675", "gradient": "#fd1313"}},
            "hue-lights": {"action": "ignore", "type": "", "config": {}},
        }}]
    am.ledfx_client.get_scenes = fake_scenes
    _set("ambient_wake_scene", "wake-hues")
    color = await ORIG_WAKE_COLOR()   # the real derivation, saved pre-stub
    check("wake color derived", color == "#ffb675", repr(color))

    print("\n" + ("ALL PASS" if ok else "FAILURES — see above"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
