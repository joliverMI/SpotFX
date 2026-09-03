"""THE CONTAMINATION WITNESS — the query shape, the three verdicts, and the
sconce mains rule.

No network anywhere in this file: `httpx.MockTransport` stands in for
River's service, exactly as `tests/test_transcription.py` does for the
Whisper bridge. The deploy-time bearer is never read by anything here.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from spectra.services import witness


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _configured(monkeypatch):
    monkeypatch.setenv("SPECTRA_WITNESS_URL", "http://witness.invalid")
    monkeypatch.setenv("SPECTRA_WITNESS_TOKEN", "not-the-real-one")


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ── the wire ───────────────────────────────────────────────────────────────

def test_changes_is_a_bearer_get_with_an_iso_window():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"changes": []})

    async def main():
        async with _client(handler) as client:
            return await witness.fetch_changes(1_700_000_000.0,
                                               1_700_000_060.0, client=client)

    assert _run(main()) == []
    assert seen["path"] == "/witness/changes"
    assert seen["auth"] == "Bearer not-the-real-one"
    assert seen["params"]["start"].startswith("2023-")
    assert seen["params"]["end"].endswith("+00:00")


def test_scope_is_read_and_never_cached_across_calls():
    """River's instruction. A cached scope is a stale belief about what is
    being watched, so every call is a real read."""
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"entities": ["light.a", "light.b"]})

    async def main():
        async with _client(handler) as client:
            first = await witness.fetch_scope(client=client)
            second = await witness.fetch_scope(client=client)
            return first, second

    first, second = _run(main())
    assert first == second == ["light.a", "light.b"]
    assert len(calls) == 2, "the scope was cached between reads"


def test_a_window_past_the_cap_is_refused_before_the_request_goes_out():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={"changes": []})

    async def main():
        async with _client(handler) as client:
            await witness.fetch_changes(0.0, witness.MAX_WINDOW_S + 1.0,
                                        client=client)

    with pytest.raises(witness.WitnessUnavailable) as exc:
        _run(main())
    assert "at most" in str(exc.value)
    assert calls == [], "the over-long query was still sent"


def test_an_unconfigured_host_is_unavailable_not_clean(monkeypatch):
    monkeypatch.delenv("SPECTRA_WITNESS_URL", raising=False)
    assert witness.configured() is False
    verdict = _run(witness.check_window(0.0, 1.0, []))
    assert verdict.status == witness.VERDICT_UNAVAILABLE
    assert verdict.clean is False


def test_an_error_response_never_escapes_as_itself_and_never_logs_the_token():
    def handler(request):
        return httpx.Response(503, text="down")

    async def main():
        async with _client(handler) as client:
            return await witness.check_window(0.0, 60.0, [], client=client)

    verdict = _run(main())
    assert verdict.status == witness.VERDICT_UNAVAILABLE
    assert "503" in verdict.detail
    assert "not-the-real-one" not in verdict.detail


# ── the verdict ────────────────────────────────────────────────────────────

def _rows(*specs):
    return witness.parse_rows({"changes": [
        {"entity_id": e, "at": at} for e, at in specs]})


def test_nothing_in_the_window_is_clean():
    verdict = witness.judge(_rows(), ["strip"], 100.0, 200.0)
    assert verdict.status == witness.VERDICT_CLEAN
    assert verdict.clean


def test_a_foreign_change_inside_the_window_contaminates_and_names_it():
    rows = _rows(("light.hallway", "2023-11-14T22:13:30+00:00"))
    start = rows[0].at_ts - 5
    verdict = witness.judge(rows, ["strip"], start, start + 10)
    assert verdict.status == witness.VERDICT_CONTAMINATED
    assert "light.hallway" in verdict.detail
    assert "discarded and taken again" in verdict.detail
    assert len(verdict.rows) == 1


def test_our_own_fixture_changing_is_never_contamination():
    """A run that lit a strip and then indicted itself for the strip having
    changed would refuse every capture it ever took."""
    rows = _rows(("light.tv_backlight", "2023-11-14T22:13:30+00:00"))
    tokens = witness.own_entities([{"id": "tv-backlight",
                                    "name": "TV Backlight"}])
    start = rows[0].at_ts - 5
    assert witness.judge(rows, tokens, start, start + 10).clean


def test_a_row_outside_the_window_does_not_indict_it():
    rows = _rows(("light.hallway", "2023-11-14T22:13:30+00:00"))
    late = rows[0].at_ts + 600
    assert witness.judge(rows, [], late, late + 10).clean


def test_a_row_with_no_timestamp_is_kept_not_dropped():
    """The safe direction for a contamination check is to notice a change it
    cannot place, never to discard it."""
    rows = witness.parse_rows({"changes": [{"entity_id": "light.hallway"}]})
    assert witness.judge(rows, [], 100.0, 200.0).contaminated


def test_the_entity_match_is_exact_on_the_object_id_not_a_substring():
    tokens = witness.own_entities([{"id": "kitchen", "name": "kitchen"}])
    assert witness.is_ours("light.kitchen", tokens)
    assert not witness.is_ours("light.kitchen_ceiling", tokens)


def test_unavailable_marks_and_makes_no_clean_claim():
    verdict = witness.unavailable(RuntimeError("no route"), 1.0, 2.0)
    assert verdict.status == witness.VERDICT_UNAVAILABLE
    assert verdict.clean is False
    assert verdict.contaminated is False
    assert "KEPT" in verdict.detail
    assert "nothing claims it was clean" in verdict.detail


# ── the sconce mains rule ──────────────────────────────────────────────────

def test_the_mains_check_is_the_first_line_of_a_sconce_diagnostic():
    """His own order. Mains-off looks exactly like a dead controller or a
    lost network, and a line buried three paragraphs down is the hour this
    rule exists to save."""
    said = witness.sconce_diagnostic("the fixture did not answer")
    assert said.startswith("FIRST: check light.dimmer_kitchen_sconce for 0%")
    assert "MAINS SUPPLY" in said
    assert "the fixture did not answer" in said


def test_the_mains_check_says_it_is_a_switch_not_a_scale():
    """The Admiral's correction: it is binary, 0% or 100%. Nothing designs
    against it scaling and nothing records a level per measurement."""
    assert "switch, not a dimmer" in witness.SCONCE_MAINS_FIRST_CHECK
    assert "0% or 100%" in witness.SCONCE_MAINS_FIRST_CHECK


def test_nothing_here_ever_writes_to_home_assistant():
    """The never-touch rule, asserted against the module body rather than
    trusted: this side originates exactly two HA requests and both are
    GETs."""
    import inspect
    source = inspect.getsource(witness)
    for verb in (".post(", ".put(", ".patch(", ".delete("):
        assert verb not in source, f"the witness client contains a {verb}"


def test_a_non_sconce_diagnostic_is_left_exactly_as_it_was():
    assert witness.sconce_diagnostic("boom", sconce_involved=False) == "boom"
    assert witness.mentions_sconce("crystal-mapper blk3") is False
    assert witness.mentions_sconce("sconce-kitchen-left") is True


# ── a 200-shaped error body is UNVERIFIED, never clean ─────────────────────
#
# River's live report: her over-cap answer is an ERROR OBJECT with a 200, and
# a payload with no `changes` key parsed naively reads as zero rows — a
# genuine CLEAN claim, invented by this side. The two guarded paths (the
# client-side window cap, and HTTP >= 400) never fire on it.

def test_a_200_with_an_error_object_is_witness_unavailable_not_clean():
    """RED against the old parse, which returned [] here and let `judge`
    hand back a clean verdict for a window the witness never answered."""
    def handler(request):
        return httpx.Response(200, json={
            "error": "window too large",
            "max_window_s": 7200})

    async def main():
        async with _client(handler) as client:
            return await witness.check_window(1_700_000_000.0,
                                              1_700_000_060.0,
                                              ["light.ours"], client=client)

    verdict = _run(main())
    assert verdict.status == witness.VERDICT_UNAVAILABLE
    assert verdict.clean is False
    assert verdict.contaminated is False


def test_the_absent_key_sentence_names_what_was_received():
    """So a future change to River's service is a READ, not a mystery: the
    sentence carries the keys that arrived and the error marker itself."""
    with pytest.raises(witness.WitnessUnavailable) as caught:
        witness.parse_rows({"error": "window too large", "max_window_s": 7200})
    said = str(caught.value)
    assert "'changes'" in said
    assert "error, max_window_s" in said
    assert "window too large" in said


def test_an_error_marker_beside_real_rows_is_also_unverified():
    with pytest.raises(witness.WitnessUnavailable):
        witness.parse_rows({"changes": [{"entity_id": "light.hall"}],
                            "error": "partial scan"})
    with pytest.raises(witness.WitnessUnavailable):
        witness.parse_rows({"changes": [], "witness": "degraded"})


def test_a_payload_that_is_neither_object_nor_list_is_unverified():
    for payload in (None, "", "ok", 0):
        with pytest.raises(witness.WitnessUnavailable):
            witness.parse_rows(payload)


def test_an_explicit_empty_changes_list_is_a_genuine_clean():
    """The other half, and it must stay: an answered window with nothing in
    it is the ordinary healthy case."""
    assert witness.parse_rows({"changes": []}) == []
    assert witness.parse_rows({"changes": [], "witness": "ok"}) == []
    assert witness.parse_rows([]) == []
    verdict = witness.judge([], ["light.ours"], 1.0, 2.0)
    assert verdict.status == witness.VERDICT_CLEAN
    assert verdict.clean is True


def test_a_bare_list_of_rows_still_parses_as_before():
    rows = witness.parse_rows([{"entity_id": "light.hallway"}])
    assert [r.entity_id for r in rows] == ["light.hallway"]
