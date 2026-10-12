"""A WLED'S MASTER BRIGHTNESS IS HOME ASSISTANT'S — Spectra never sends it.

The Admiral, 2026-10-12 (data/wled-bri-audit/report.md): "Home assistant can
set the WLED global brightness of any of these lights, and spectra doesn't
touch that value." Two independent guards, so the rule fails LOUDLY the day
a code path grows a brightness write back:

  1. AT THE TRANSPORT. `fx.utils.WLED._wled_request` is the one call every
     WLED JSON write in this repo goes through (house_fixtures' power
     writes, night_power, release_realtime). It refuses a json body carrying
     `bri` — top level or on a segment — before anything leaves.
     It refuses "Force max brightness" (`maxbri`, anywhere in a json= or
     data= body) the same way: it stays OFF so Home Assistant's brightness
     keeps scaling the stream (River's acceptance, 2026-10-12).
  2. IN THE SOURCE. A static scan of every Python file that can reach a WLED
     (`spectra/`, `fx/`, the root process's `services/`/`api/`, `scripts/`,
     `main.py`) finds every dict literal with a "bri" key, every
     `x["bri"] = ...` store and every `bri=` keyword. Each one must be a
     named READ-BACK below, with why; a new one fails this test. A test
     double that models a WLED's reply lives under tests/ and is not
     scanned.
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCANNED = ("spectra", "fx", "services", "api", "scripts", "main.py")

#: (path, enclosing function) -> why a "bri" key there is not a write. Keep
#: it short: every entry is something that READS a WLED and names what it
#: read.
READS = {
    ("spectra/services/night_exit.py", "_read_wled"):
        "the honest exit's read-back record of what the fixture reported",
    ("scripts/check_fixture_brightness.py", "_get"):
        "a fake json/state REPLY the check reads get_brightness against",
    ("scripts/check_fixture_brightness.py", "main"):
        "the deliberate `bri` body that proves the transport REFUSES it",
}


# ── 1. the transport ───────────────────────────────────────────────────────

@pytest.mark.parametrize("body", [
    {"bri": 255},
    {"on": True, "bri": 1},
    {"seg": [{"id": 0, "bri": 3}]},
    {"seg": {"bri": 3}},
])
def test_the_transport_refuses_a_brightness_body_before_it_leaves(body):
    from fx.utils import WLED, WLEDBrightnessRefused
    sent = []

    def post(url, timeout=None, **kwargs):          # pragma: no cover
        sent.append(kwargs)

    with pytest.raises(WLEDBrightnessRefused, match="Home Assistant"):
        asyncio.run(WLED._wled_request(post, "10.0.0.9", "json/state",
                                       json=body))
    assert sent == [], "nothing may reach the wire"


@pytest.mark.parametrize("kw", [
    {"json": {"if": {"live": {"maxbri": True}}}},
    {"json": {"if": {"live": {"maxbri": False}}}},
    {"data": {"if": {"live": {"maxbri": False, "timeout": 5}}}},
])
def test_the_transport_refuses_force_max_brightness_however_it_is_sent(kw):
    from fx.utils import WLED, WLEDBrightnessRefused
    sent = []

    def post(url, timeout=None, **kwargs):          # pragma: no cover
        sent.append(kwargs)

    with pytest.raises(WLEDBrightnessRefused, match="maxbri"):
        asyncio.run(WLED._wled_request(post, "10.0.0.9", "json/cfg", **kw))
    assert sent == []


def test_nothing_can_flush_force_max_brightness():
    """The vendored sync-settings flush always carries the `maxbri` it read,
    so it is refused at the transport — and nothing calls it, the setter or
    the sync-mode loop that would."""
    from fx.utils import WLED, WLEDBrightnessRefused
    wled = WLED("10.0.0.9")
    wled.sync_settings = {"if": {"live": {"maxbri": False, "timeout": 2}}}
    wled.force_max_brightness()
    with pytest.raises(WLEDBrightnessRefused):
        asyncio.run(wled.flush_sync_settings())
    callers = []
    for path in _files():
        rel = path.relative_to(REPO).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("force_max_brightness",
                                           "flush_sync_settings",
                                           "set_wleds_sync_mode")):
                callers.append((rel, node.func.attr))
    # the one call left is inside the vendored set_wleds_sync_mode, which
    # nothing calls (and which the transport would refuse anyway)
    assert callers == [("fx/devices/__init__.py", "flush_sync_settings")], callers


def test_a_power_only_body_still_goes_out():
    from types import SimpleNamespace

    from fx.utils import WLED
    sent = []

    def post(url, timeout=None, **kwargs):
        sent.append(kwargs["json"])
        return SimpleNamespace(ok=True)

    for body in ({"on": True}, {"on": False}, {"live": False},
                 {"seg": [{"id": 0, "on": True}]}):
        asyncio.run(WLED._wled_request(post, "10.0.0.9", "json/state",
                                       json=body))
    assert sent == [{"on": True}, {"on": False}, {"live": False},
                    {"seg": [{"id": 0, "on": True}]}]


def test_house_fixtures_own_transport_goes_through_the_guarded_call():
    """The house seam's real default transport (`_post_blocking`) is the
    guarded `_wled_request`, so even a future payload bug there is refused
    at the wire."""
    from fx.utils import WLED, WLEDBrightnessRefused
    from spectra.services import house_fixtures
    with pytest.raises(WLEDBrightnessRefused):
        house_fixtures._post_blocking(WLED("10.0.0.9"), {"on": True, "bri": 34},
                                      0.1)


def test_every_house_power_write_including_retries_is_power_only(monkeypatch):
    """River's acceptance: every power write is exactly {"on": true|false},
    INCLUDING the retries a refused or unconfirmed write gets — driven
    through the house seam's real `_write_confirmed`/`_transition` with a
    fixture that refuses twice, then never confirms."""
    from types import SimpleNamespace

    from spectra.services import house_fixtures as hf
    posts, reads = [], {"n": 0}

    async def post(dev, payload):
        posts.append(dict(payload))
        if len(posts) <= 2:
            raise TimeoutError("refused")              # the first two fail

    async def get_state(dev):
        reads["n"] += 1
        return {"on": not payload_on[0], "bri": 1}     # never confirms

    async def no_sleep(_s):
        return None

    monkeypatch.setattr(hf, "deps", hf.Deps(post=post, get_state=get_state,
                                             sleep=no_sleep))
    monkeypatch.setattr(hf, "_remember_before", _noop_remember)
    monkeypatch.setattr(hf, "_record_power", lambda *a, **k: None)
    monkeypatch.setattr(hf, "_record", lambda *a, **k: None)
    monkeypatch.setattr(hf, "kick", lambda: None)
    dev = SimpleNamespace(id="crystal", type="wled",
                          wled=SimpleNamespace(ip_address="10.0.0.48"))
    payload_on = [True]
    asyncio.run(hf._transition("crystal", dev, hf.TARGET_ON, "test", owned=True))
    payload_on[0] = False
    asyncio.run(hf._transition("crystal", dev, hf.TARGET_OFF, "test", owned=True))
    on_writes = [p for p in posts if "on" in p]
    assert len(on_writes) == 2 * hf.WRITE_ATTEMPTS, "every retry was tried"
    assert all(p in ({"on": True}, {"on": False}) for p in on_writes), posts
    assert all(set(p) <= {"on", "live"} for p in posts), posts
    assert all("bri" not in p for p in posts)


async def _noop_remember(_did, _dev):
    return None


def test_set_brightness_no_longer_exists():
    from fx.utils import WLED
    assert not hasattr(WLED, "set_brightness")


# ── 2. the source ──────────────────────────────────────────────────────────

def _files():
    for root in SCANNED:
        path = REPO / root
        if path.is_file():
            yield path
        elif path.is_dir():
            for p in sorted(path.rglob("*.py")):
                if "node_modules" in p.parts or "__pycache__" in p.parts:
                    continue
                yield p


def _bri_sites(tree: ast.AST):
    """(line, enclosing function, kind) for every "bri" key written."""
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    def enclosing(node):
        while node in parents:
            node = parents[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return node.name
        return "<module>"

    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key in node.keys:
                if isinstance(key, ast.Constant) and key.value == "bri":
                    yield node.lineno, enclosing(node), "dict key"
        elif (isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store)
              and isinstance(node.slice, ast.Constant)
              and node.slice.value == "bri"):
            yield node.lineno, enclosing(node), '["bri"] store'
        elif isinstance(node, ast.keyword) and node.arg == "bri":
            yield getattr(node, "lineno", 0), enclosing(node), "bri= keyword"


def test_no_source_builds_a_brightness_payload_for_a_wled():
    found, seen_reads = [], set()
    for path in _files():
        rel = path.relative_to(REPO).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:                              # pragma: no cover
            continue
        for line, func, kind in _bri_sites(tree):
            if (rel, func) in READS:
                seen_reads.add((rel, func))
                continue
            found.append(f"{rel}:{line} ({func}, {kind})")
    assert not found, (
        "a WLED's brightness is Home Assistant's — Spectra never writes it. "
        "These build a 'bri' payload; if one is only a READ-BACK, name it in "
        f"READS with why: {found}")
    stale = set(READS) - seen_reads
    assert not stale, f"READS names sites that no longer exist: {stale}"
