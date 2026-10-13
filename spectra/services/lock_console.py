"""THE LOCK DOMAIN — Sonic's reach over the root lock engine's whole-song
check (the per-song offset watchdog, services/whole_song_check.py in the
SpotFX process).

The check lives in the root SpotFX process (`:8000`), which owns every
song's stored offset; SPECTRA may not import it (import discipline,
scripts/check_process_split.py). So these operations go through the root's
own HTTP route — GET/PUT /api/lock-history/whole-song/settings and GET
/api/lock-history/whole-song — the SAME route the Timing page's Settings
button uses, so Sonic and a human edit through one validator and one store
(storage/settings.json) and cannot disagree about what a legal value is.

`KEYS` mirrors the root's `whole_song_check.SETTINGS` names (asserted equal
in tests/test_lock_console.py). Ranges are NOT mirrored: the root refuses an
out-of-range value by name (422) and that sentence is handed back verbatim.

What stays off-limits, deliberately: running the check by hand (it needs a
play's captured audio, which only exists while the song plays) and editing a
song's stored offset directly (that is the check's and the sweep's job; a
hand-set offset is the Timing page's user-verified path).
"""
from __future__ import annotations

from typing import Any, Optional

from spectra.services.sonic_ops import SonicOperation

HTTP_TIMEOUT_S = 10.0

KEYS: tuple[str, ...] = (
    "xcorr_whole_song_enabled",
    "xcorr_whole_song_min_windows",
    "xcorr_whole_song_min_vote_fraction",
    "xcorr_whole_song_min_r",
    "xcorr_whole_song_min_r_margin",
    "xcorr_whole_song_min_move_ms",
    "xcorr_whole_song_locked_every",
    "xcorr_withhold_resave_min_repeats",
)


def _base_url() -> str:
    try:
        from spectra.services import engine
        return engine.bridge.http_url
    except Exception:                                    # noqa: BLE001
        from spectra.services.bridge import default_http_url
        return default_http_url()


async def _http(method: str, path: str, *, params: Optional[dict] = None,
                json: Any = None):
    """One request to the root process. Injectable for tests (no live access
    from tests, ever) — replace `http` with a fake of the same shape."""
    import httpx
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_S) as client:
        return await client.request(method, f"{_base_url()}{path}",
                                    params=params, json=json)


#: injectable for tests
http = _http


def _unreachable(exc: Exception) -> dict:
    return {"status": "rejected",
            "reason": f"the SpotFX lock engine (root process) did not answer: {exc}"}


async def _op_get_whole_song_check(limit: int = 10, every_check: bool = False) -> dict:
    if isinstance(limit, bool) or not isinstance(limit, int) or not (1 <= limit <= 50):
        return {"status": "rejected", "reason": "limit must be a whole number from 1 to 50"}
    if not isinstance(every_check, bool):
        return {"status": "rejected", "reason": "every_check must be true or false"}
    try:
        s = await http("GET", "/api/lock-history/whole-song/settings")
        s.raise_for_status()
        log = await http("GET", "/api/lock-history/whole-song",
                         params={"limit": limit,
                                 "corrections_only": "false" if every_check else "true"})
        log.raise_for_status()
    except Exception as exc:                             # noqa: BLE001
        return _unreachable(exc)
    body = s.json()
    return {"status": "ok", "settings": body.get("settings"), "spec": body.get("spec"),
            "entries": log.json().get("entries", [])}


async def _op_set_whole_song_check_setting(key: str, value: Any) -> dict:
    if key not in KEYS:
        return {"status": "rejected",
                "reason": f"unknown setting {key!r} — known: {', '.join(KEYS)}"}
    try:
        r = await http("PUT", "/api/lock-history/whole-song/settings", json={key: value})
    except Exception as exc:                             # noqa: BLE001
        return _unreachable(exc)
    if r.status_code == 422:
        try:
            reason = r.json().get("detail") or r.text
        except Exception:                                # noqa: BLE001
            reason = r.text
        return {"status": "rejected", "reason": str(reason)}
    try:
        r.raise_for_status()
    except Exception as exc:                             # noqa: BLE001
        return _unreachable(exc)
    body = r.json()
    before = (body.get("previous") or {}).get(key)
    after = (body.get("settings") or {}).get(key)
    return {"status": "applied", "key": key, "old": before, "new": after,
            "summary": f"{key}: {before} → {after}"}


_INSTR_COMMON = (
    "The whole-song check is the lock engine's per-song offset watchdog: after a "
    "song finishes playing without locking (and every Nth play that did lock), "
    "it votes that play's own audio over the whole song and, when one offset "
    "wins clearly and matches better than the saved one, it corrects the saved "
    "offset so the song is in time from its next play. ")

OPERATIONS: dict[str, SonicOperation] = {
    "get_whole_song_check": SonicOperation(
        name="get_whole_song_check", domain="lock", kind="read",
        summary="Read the whole-song check's settings and its recent corrections "
                "(the lock engine's per-song offset watchdog).",
        instructions=(
            _INSTR_COMMON
            + "Call this before changing a setting, or when he asks what the check "
            "did, which songs it fixed, or why a song was left alone. `entries` "
            "lists corrections (song, old → new offset, windows won, match r); pass "
            "every_check=true to include the checks that left a song alone, each with "
            "its reason. `spec` gives each setting's label, range and meaning — use "
            "the labels when you talk to him, not the key names."),
        input_schema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
                "every_check": {"type": "boolean", "default": False},
            },
            "additionalProperties": False},
        handler=_op_get_whole_song_check),
    "set_whole_song_check_setting": SonicOperation(
        name="set_whole_song_check_setting", domain="lock", kind="write",
        summary="Change one whole-song check setting (on/off, thresholds, how often "
                "locked plays are checked, the re-save withholding).",
        instructions=(
            _INSTR_COMMON
            + "One key per call. xcorr_whole_song_enabled turns the check on/off. "
            "min_vote_fraction is a share 0.5-1.0 (0.70 = 70%); min_r and "
            "min_r_margin are correlation r 0-1; min_move_ms is milliseconds; "
            "locked_every N checks every Nth locked play (0 = never after a lock); "
            "xcorr_withhold_resave_min_repeats stops a play re-saving its offset "
            "after N stronger finds it could not move to (0 = off). An out-of-range "
            "value is refused with the reason — tell him the reason. Changes apply "
            "from the next song that finishes; nothing already saved is undone."),
        input_schema={
            "type": "object",
            "properties": {
                "key": {"type": "string", "enum": list(KEYS)},
                "value": {"type": ["boolean", "number"]},
            },
            "required": ["key", "value"],
            "additionalProperties": False},
        handler=_op_set_whole_song_check_setting),
}
