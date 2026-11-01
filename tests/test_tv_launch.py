"""`spectra/services/tv_launch.py` — "one tap" (data/tv-display-plan/
plan.html PR 1.6). Every test here injects a fake `call_service`/
`fetch_running` — nothing imports httpx/ha_client for real, nothing
reaches a real Home Assistant or TV, matching the module's own stated
posture."""
from __future__ import annotations

import asyncio

import pytest

from spectra.services import tv_launch


def _go(coro):
    return asyncio.run(coro)


# ── config store ─────────────────────────────────────────────────────────────

def test_a_fresh_config_defaults_to_off_and_the_default_script():
    cfg = tv_launch.load_config()
    assert cfg.auto_open_enabled is False
    assert cfg.script_entity is None
    assert cfg.resolved_script() == tv_launch.DEFAULT_SCRIPT_ENTITY


def test_save_then_load_round_trips():
    cfg = tv_launch.TvLaunchConfig(auto_open_enabled=True, script_entity="script.my_tv")
    tv_launch.save_config(cfg)
    reloaded = tv_launch.load_config()
    assert reloaded.auto_open_enabled is True
    assert reloaded.script_entity == "script.my_tv"
    assert reloaded.resolved_script() == "script.my_tv"


def test_apply_patch_is_a_true_partial_update():
    tv_launch.save_config(tv_launch.TvLaunchConfig(auto_open_enabled=True,
                                                   script_entity="script.my_tv"))
    cfg = tv_launch.apply_patch({"auto_open_enabled": False})
    assert cfg.auto_open_enabled is False
    assert cfg.script_entity == "script.my_tv"          # untouched — not in the patch
    cfg2 = tv_launch.apply_patch({"script_entity": None})
    assert cfg2.script_entity is None                    # explicit clear
    assert cfg2.auto_open_enabled is False                # untouched


def test_apply_patch_treats_the_json_string_false_as_false_never_true_by_truthiness():
    tv_launch.save_config(tv_launch.TvLaunchConfig(auto_open_enabled=True))
    cfg = tv_launch.apply_patch({"auto_open_enabled": "false"})
    assert cfg.auto_open_enabled is False


def test_apply_patch_accepts_the_string_true_case_insensitively():
    cfg = tv_launch.apply_patch({"auto_open_enabled": "TRUE"})
    assert cfg.auto_open_enabled is True


def test_apply_patch_refuses_a_malformed_auto_open_value_rather_than_guessing():
    tv_launch.save_config(tv_launch.TvLaunchConfig(auto_open_enabled=False))
    with pytest.raises(tv_launch.TvLaunchPatchError):
        tv_launch.apply_patch({"auto_open_enabled": "yes"})
    # the refused write must not have landed
    assert tv_launch.load_config().auto_open_enabled is False


def test_an_unreadable_store_reads_as_the_default_and_logs_rather_than_raises(tmp_path, monkeypatch):
    from spectra import config as scfg
    bad = tmp_path / "corrupt.json"
    bad.write_text("not json at all")
    monkeypatch.setattr(scfg, "TV_LAUNCH_FILE", bad)
    cfg = tv_launch.load_config()
    assert cfg.auto_open_enabled is False


# ── put_on_tv() ──────────────────────────────────────────────────────────────

def test_put_on_tv_defaults_to_the_configured_entity():
    calls = []

    async def fake_call_service(domain, service, data):
        calls.append((domain, service, data))
        return "sent"

    result = _go(tv_launch.put_on_tv(call_service=fake_call_service))
    assert calls == [("script", "turn_on", {"entity_id": tv_launch.DEFAULT_SCRIPT_ENTITY})]
    assert result == "sent"


def test_put_on_tv_an_explicit_entity_wins_over_the_configured_one():
    tv_launch.save_config(tv_launch.TvLaunchConfig(script_entity="script.configured"))
    calls = []

    async def fake_call_service(domain, service, data):
        calls.append(data["entity_id"])
        return None

    _go(tv_launch.put_on_tv("script.explicit", call_service=fake_call_service))
    assert calls == ["script.explicit"]


def test_put_on_tv_falls_back_to_the_configured_entity_when_none_given():
    tv_launch.save_config(tv_launch.TvLaunchConfig(script_entity="script.configured"))
    calls = []

    async def fake_call_service(domain, service, data):
        calls.append(data["entity_id"])
        return None

    _go(tv_launch.put_on_tv(call_service=fake_call_service))
    assert calls == ["script.configured"]


# ── the always-running auto-open poller ─────────────────────────────────────

class _Clock:
    def __init__(self):
        self.slept = []

    async def sleep(self, s):
        self.slept.append(s)


def _deps(running_sequence, enabled=True, script_entity=None):
    seq = list(running_sequence)
    calls = []

    async def fetch_running():
        return seq.pop(0)

    async def fake_put_on_tv(entity=None):
        calls.append(entity)
        return "opened"

    def load_cfg():
        return tv_launch.TvLaunchConfig(auto_open_enabled=enabled, script_entity=script_entity)

    clock = _Clock()
    deps = tv_launch.AutoOpenDeps(fetch_running=fetch_running, put_on_tv=fake_put_on_tv,
                                  load_config=load_cfg, sleep=clock.sleep)
    return deps, calls, clock


def test_the_first_poll_never_fires_even_if_already_running():
    """A process restart during an ongoing night must not re-trigger —
    only an edge OBSERVED by this poller counts."""
    deps, calls, clock = _deps([True, True], enabled=True)
    _go(tv_launch.run_auto_open_supervised(deps, iterations=2))
    assert calls == []
    assert clock.slept == [tv_launch.AUTO_OPEN_POLL_S]


def test_a_genuine_rising_edge_fires_exactly_once():
    deps, calls, clock = _deps([False, True, True, True, True], enabled=True)
    _go(tv_launch.run_auto_open_supervised(deps, iterations=5))
    assert calls == [None]                     # fired once, on poll 2's rising edge; never again
                                                # while it just keeps running


def test_two_separate_rising_edges_each_fire():
    deps, calls, clock = _deps([False, True, False, True], enabled=True)
    _go(tv_launch.run_auto_open_supervised(deps, iterations=4))
    assert calls == [None, None]


def test_disabled_never_fires_even_on_a_real_rising_edge():
    deps, calls, clock = _deps([False, True], enabled=False)
    _go(tv_launch.run_auto_open_supervised(deps, iterations=2))
    assert calls == []


def test_a_failed_fetch_does_not_crash_the_loop_and_is_never_treated_as_an_edge_by_itself():
    # poll 1: unknown (None) — observed only; poll 2: unknown again — no
    # edge since last_running is still "falsy"-but-unknown, consistent
    # with treating an unknown->True transition as the one ambiguous case
    # (see module docstring) rather than crashing or skipping.
    deps, calls, clock = _deps([None, None, False], enabled=True)
    _go(tv_launch.run_auto_open_supervised(deps, iterations=3))
    assert calls == []


def test_unknown_to_true_is_treated_as_an_edge_the_conservative_direction():
    deps, calls, clock = _deps([False, None, True], enabled=True)
    _go(tv_launch.run_auto_open_supervised(deps, iterations=3))
    assert calls == [None]


def test_an_exception_in_one_iteration_does_not_kill_the_loop():
    # poll 1: observes False (first poll, never fires anyway); poll 2:
    # the fetch itself raises — caught, logged, and the loop continues;
    # poll 3: a genuine rising edge against the last GOOD reading (False)
    # still fires, proving one bad iteration doesn't corrupt the state
    # the edge detection relies on.
    seq = [False, RuntimeError("boom"), True]
    calls = []

    async def flaky_fetch():
        v = seq.pop(0)
        if isinstance(v, Exception):
            raise v
        return v

    async def fake_put_on_tv(entity=None):
        calls.append(entity)
        return "opened"

    clock = _Clock()
    deps = tv_launch.AutoOpenDeps(fetch_running=flaky_fetch, put_on_tv=fake_put_on_tv,
                                  load_config=lambda: tv_launch.TvLaunchConfig(auto_open_enabled=True),
                                  sleep=clock.sleep)
    _go(tv_launch.run_auto_open_supervised(deps, iterations=3))
    assert calls == [None]
    # the LAST iteration never sleeps (known_buffer.run_poll_supervised's
    # own convention) — iterations=3 sleeps twice, not three times.
    assert len(clock.slept) == 2


def test_cancellation_propagates_rather_than_being_swallowed():
    async def cancels():
        raise asyncio.CancelledError()

    deps = tv_launch.AutoOpenDeps(fetch_running=cancels, load_config=tv_launch.load_config)
    with pytest.raises(asyncio.CancelledError):
        _go(tv_launch.run_auto_open_supervised(deps, iterations=1))
