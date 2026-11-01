"""THE ABSORB DOMAIN — Sonic's reach over Absorb Music (silent, unattended
capture of a linked Spotify playlist on Serenity; data/absorb-music-plan/
report.md §10, phase 5).

The runner lives in the root SpotFX process (`:8000`, services/absorb.py),
which owns the playlist, the house volume and every capture; SPECTRA may not
import it (import discipline, scripts/check_process_split.py). So these
operations go through SpotFX's own routes (routers/absorb_router.py) — the
SAME routes the /absorb page uses — exactly lock_console.py's shape: Sonic and
a human edit through one validator and one store (storage/absorb.json), and
start a window through one door, POST /api/absorb/start, with every refusal
it has (no playlist, music playing, a night or camera run, the silence proof,
River's hard block, the Order 27 gate) answered in its own words. Nothing here
re-implements a gate, and nothing here can skip one.

ASKING FIRST. The page asks before two acts (Start now; force recapture ON),
and Sonic asks before those two and before every other change that newly lets
Absorb act on the house or his playlists without anyone pressing anything:
the schedule newly able to open windows (or opening different ones), the
linked playlist changing while the schedule is on, running while the house
sleeps switched back on, and Recently Captured's cap lowered (the oldest songs
are taken out of it at the next filing). The first call hands back a
`confirm_id` and the question to put to him, and writes nothing; only a second
call carrying that id acts — the analysis domain's plan_id shape. An id is
single-use, expires after CONFIRM_TTL_S, belongs to one operation and one set
of arguments, and is refused if his settings changed after he was asked: he
said yes to the question as asked, not to whatever the room became since. A
config change is validated by the route's own dry run (PUT /config?dry_run=
true) BEFORE the question, so he is never asked about an edit the validator
would refuse. Turning the hidden player's backlog work ON (use_capture_lane,
phase 4 — services/absorb_lane.py on the SpotFX side) asks first too: it lets
Absorb learn songs with nobody pressing anything, though inaudibly and without
touching his playlists. Stop, Skip this song, Retry and the plain numbers act at once,
as on the page: stopping gives the house back, which is never a thing to make
him wait for.

What stays off-limits, deliberately (report §10): editing either playlist's
contents (that is Spotify's own app), and clearing a song's needs_recapture
flag in bulk (one at a time, named, on the page). These settings are READ by
get_absorb_settings and not changed by voice: head_max_ms (his Q1 head bar,
read off a measured cliff — §8.1), order and warm_up (D13/D14, the ordering
that lets a re-capture land its head — §8.5), recently_captured_includes_
skipped (his Q2 answer), resume_after_quiet_min / min_remaining_min /
max_resumes_per_window (his Q4 answer's definition of quiet — §6.1),
silence_recheck_s (the Order 27 gate's re-proof cadence — §6.2) and
captured_playlist_name (a new name makes SpotFX create a new Spotify playlist
at the next filing). Linking a playlist Absorb could not edit (one he follows
but does not own) is refused: every captured song would fail to leave it.

`SETTING_KEYS`, `DAYS` and `HOUSE_TZ` mirror SpotFX's AbsorbConfig fields,
models.absorb.DAYS and absorb_schedule.HOUSE_TZ (asserted in
tests/test_absorb_console.py). Ranges are NOT mirrored: SpotFX refuses an
out-of-range value by name (422) and that sentence is handed back verbatim.
"""
from __future__ import annotations

import json as _json
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

from spectra.services import name_resolve
from spectra.services.sonic_ops import SonicOperation

HTTP_TIMEOUT_S = 10.0
# The start route proves the silence (Home Assistant + every snapserver room)
# and builds the queue (the whole playlist, read from Spotify) before it
# answers; the preview and the playlist list read Spotify too. Every bound
# stays inside the CLI backend's own 60 s forward (settings_mcp_server._call),
# so a slow start reaches him as "it may still have opened", never as the
# forwarder's "did not run". The question before a start only decorates
# itself with the playlist's split, so it gives that read less time.
START_TIMEOUT_S = 50.0
PREVIEW_TIMEOUT_S = 40.0
QUESTION_PREVIEW_TIMEOUT_S = 15.0
CONFIRM_TTL_S = 300.0
_PENDING_MAX = 50

HOUSE_TZ = "America/New_York"
DAYS: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_DAY_LABELS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

#: the AbsorbConfig fields Sonic changes through set_absorb_setting
SETTING_KEYS: tuple[str, ...] = (
    "max_attempts",
    "play_window_size",
    "overrun_grace_min",
    "recently_captured_max",
    "run_while_sleeping",
    "use_capture_lane",
)

_BOOL_KEYS = frozenset({"run_while_sleeping", "use_capture_lane"})

_SETTING_LABELS = {
    "max_attempts": "attempts per song before it is parked",
    "play_window_size": "songs sent to Spotify at a time",
    "overrun_grace_min": "minutes a song may run past the window's end",
    "recently_captured_max": "Recently Captured's cap",
    "run_while_sleeping": "keep going while the house sleeps",
    "use_capture_lane": "learn never-captured songs on the hidden player when nothing else runs",
}

_START_QUESTION = (
    "It turns the house volume to 0 (the capture client is left alone), proves every room "
    "is silent, then plays the playlist on Serenity until the queue is done or you say stop.")

_PLAYLIST_LINK_RE = re.compile(r"(?:spotify:playlist:|open\.spotify\.com/playlist/)([A-Za-z0-9]+)")


# ── the transport ────────────────────────────────────────────────────────────

def _base_url() -> str:
    try:
        from spectra.services import engine
        return engine.bridge.http_url
    except Exception:                                    # noqa: BLE001
        from spectra.services.bridge import default_http_url
        return default_http_url()


async def _http(method: str, path: str, *, params: Optional[dict] = None,
                json: Any = None, timeout: float = HTTP_TIMEOUT_S):
    """One request to the root process. Injectable for tests (no live access
    from tests, ever) — replace `http` with a fake of the same shape."""
    import httpx
    async with httpx.AsyncClient(timeout=timeout) as client:
        return await client.request(method, f"{_base_url()}{path}",
                                    params=params, json=json)


#: injectable for tests
http = _http


def _unreachable(exc: Exception) -> dict:
    return {"status": "rejected",
            "reason": f"SpotFX (the root process, where Absorb runs) did not answer: {exc}"}


def _is_timeout(exc: Exception) -> bool:
    try:
        import httpx
        return isinstance(exc, httpx.TimeoutException)
    except Exception:                                    # noqa: BLE001
        return False


async def _get(path: str, *, params: Optional[dict] = None,
               timeout: float = HTTP_TIMEOUT_S) -> tuple[Optional[dict], Optional[dict]]:
    """(body, None) or (None, rejection)."""
    try:
        r = await http("GET", path, params=params, timeout=timeout)
        r.raise_for_status()
        return r.json(), None
    except Exception as exc:                             # noqa: BLE001
        return None, _unreachable(exc)


async def _post(path: str, body: Optional[dict] = None, *,
                timeout: float = HTTP_TIMEOUT_S) -> tuple[Optional[dict], Optional[dict]]:
    try:
        r = await http("POST", path, json=body, timeout=timeout)
        r.raise_for_status()
        return r.json(), None
    except Exception as exc:                             # noqa: BLE001
        return None, _unreachable(exc)


def _detail_sentence(detail: Any) -> str:
    """A 422's `detail` — a string, or pydantic's [{field, error}, ...] — as
    one sentence."""
    if isinstance(detail, list):
        parts = []
        for d in detail:
            if isinstance(d, dict):
                field, err = d.get("field"), d.get("error") or d.get("msg")
                parts.append(f"{field}: {err}" if field else str(err))
            else:
                parts.append(str(d))
        return "; ".join(parts)
    return str(detail)


async def _put_config(patch: dict, *, dry_run: bool) -> tuple[Optional[dict], Optional[dict]]:
    """SpotFX's one validator. (config, None) or (None, rejection)."""
    try:
        r = await http("PUT", "/api/absorb/config", json=patch,
                       params={"dry_run": "true"} if dry_run else None)
    except Exception as exc:                             # noqa: BLE001
        return None, _unreachable(exc)
    if r.status_code == 422:
        try:
            reason = _detail_sentence(r.json().get("detail") or r.text)
        except Exception:                                # noqa: BLE001
            reason = r.text
        return None, {"status": "rejected", "reason": reason}
    try:
        r.raise_for_status()
        return r.json(), None
    except Exception as exc:                             # noqa: BLE001
        return None, _unreachable(exc)


# ── asking first ─────────────────────────────────────────────────────────────

@dataclass
class _Ask:
    op: str
    fingerprint: str
    expires: float


_PENDING: dict[str, _Ask] = {}
#: injectable for tests
_clock: Callable[[], float] = time.monotonic


def _fingerprint(op: str, args: dict, config: dict) -> str:
    return _json.dumps({"op": op, "args": args, "config": config},
                       sort_keys=True, default=str)


def _ask(op: str, fingerprint: str, question: str, **extra: Any) -> dict:
    now = _clock()
    for k in [k for k, a in _PENDING.items() if a.expires <= now]:
        del _PENDING[k]
    while len(_PENDING) >= _PENDING_MAX:
        del _PENDING[next(iter(_PENDING))]
    cid = uuid.uuid4().hex[:12]
    _PENDING[cid] = _Ask(op, fingerprint, now + CONFIRM_TTL_S)
    return {"status": "needs_confirmation", "op": op, "confirm_id": cid,
            "question": question,
            "reason": f"Not done yet — this needs his yes first. {question}",
            "expires_in_s": int(CONFIRM_TTL_S), **extra}


def _redeem(op: str, fingerprint: str, confirm_id: Any) -> Optional[dict]:
    """None when `confirm_id` is the live answer to exactly this question;
    otherwise the rejection. Used up either way."""
    a = _PENDING.pop(confirm_id, None) if isinstance(confirm_id, str) else None
    if a is None or a.op != op:
        return {"status": "rejected",
                "reason": "that confirm_id is not one this operation handed out, or it was "
                          "already used — call it again without one and ask him"}
    if a.expires <= _clock():
        return {"status": "rejected",
                "reason": "that confirmation expired — call it again without a confirm_id "
                          "and ask him again"}
    if a.fingerprint != fingerprint:
        return {"status": "rejected",
                "reason": "something changed since he was asked (the request or his Absorb "
                          "settings), so his yes no longer covers it — ask him again"}
    return None


async def _config_write(op: str, patch: dict, *, confirm_id: Any,
                        question: Callable[[dict, dict], Optional[str]],
                        describe: Callable[[dict, dict], str]) -> dict:
    """Every config edit: read, validate by dry run, ask when `question`
    says so, then write through the same route and report old → new."""
    before, err = await _get("/api/absorb/config")
    if err:
        return err
    after, err = await _put_config(patch, dry_run=True)
    if err:
        return err
    q = question(before, after)
    fp = _fingerprint(op, patch, before)
    if q is not None:
        if confirm_id is None:
            return _ask(op, fp, q, would_change=describe(before, after))
        refusal = _redeem(op, fp, confirm_id)
        if refusal:
            return refusal
    elif isinstance(confirm_id, str):
        _PENDING.pop(confirm_id, None)          # moot now; still single-use
    after, err = await _put_config(patch, dry_run=False)
    if err:
        return err
    keys = sorted(patch)
    return {"status": "applied",
            "old": {k: before.get(k) for k in keys}, "new": {k: after.get(k) for k in keys},
            "summary": describe(before, after)}


# ── words ────────────────────────────────────────────────────────────────────

def _when(ms: Any) -> str:
    """Epoch ms in house time, as "Mon 21:34"."""
    try:
        if not ms:
            return ""
        return datetime.fromtimestamp(int(ms) / 1000, ZoneInfo(HOUSE_TZ)).strftime("%a %H:%M")
    except Exception:                                    # noqa: BLE001
        return ""


def window_label(w: dict) -> str:
    """One window as the schedule names it ("every day 21:30–00:30") — the
    same words as SpotFX's absorb_schedule.window_label."""
    days = [_DAY_LABELS[i] for i, d in enumerate(DAYS) if d in (w.get("days") or [])]
    every = "every day" if len(days) == 7 else ", ".join(days)
    return f"{every} {w.get('start')}–{w.get('end')}"


def _opens_on_its_own(cfg: dict) -> bool:
    return bool(cfg.get("enabled")) and bool(cfg.get("windows"))


def _windows_key(cfg: dict) -> list:
    return [(sorted(DAYS.index(d) for d in w.get("days") or [] if d in DAYS),
             w.get("start"), w.get("end")) for w in cfg.get("windows") or []]


def _schedule_line(cfg: dict) -> str:
    labels = "; ".join(window_label(w) for w in cfg.get("windows") or [])
    if _opens_on_its_own(cfg):
        return f"on — {labels}"
    if cfg.get("windows"):
        return f"off (windows kept: {labels})"
    return "off, no windows"


def _onoff(v: Any) -> str:
    return "on" if v else "off"


def _run_label(r: dict) -> str:
    w = r.get("window") or {}
    if w.get("label"):
        return f"the {w['label']} window"
    when = _when(r.get("opened_ms") or r.get("started_ms"))
    return f"the window started {when}" if when else "the last window"


def _counts_line(c: dict) -> str:
    c = c or {}
    parts = [f"{c.get('captured', 0)} captured"]
    for key, words in (("skipped", "skipped as already captured"), ("failed", "failed"),
                       ("requeued", "requeued"), ("head_missed", "head missed"),
                       ("parked", "parked")):
        if c.get(key):
            parts.append(f"{c[key]} {words}")
    return ", ".join(parts)


#: a failure or park tag as a few words — the /absorb page's own words
#: (spectra/web/src/absorb/absorbSummary.ts REASONS, asserted equal)
REASON_WORDS: dict[str, str] = {
    "gap": "a gap in the audio",
    "bad_timestamps": "bad timestamps",
    "coverage": "could no longer cover enough of the song",
    "too_short": "too short",
    "governor_drain": "the audio buffer drained",
    "no_capture": "no capture started",
    "no_outcome": "the capture never reported back",
    "no_frames": "no audio arrived",
    "head_missed": "committed without its head",
    "head_unreachable": "its head never arrived",
    "wav_librosa_failed": "analysis failed",
    "anchor_zero": "rolled back (no anchors)",
    "error": "an error",
    "skipped_by_you": "skipped by you",
    "interrupted": "interrupted",
    "left_device": "playback moved off Serenity",
    "failed": "failed",
}


def _reason_words(code: Any) -> str:
    if not code:
        return "unknown"
    return REASON_WORDS.get(str(code), str(code).replace("_", " "))


def _pct(with_head: int, attempted: int) -> Optional[int]:
    return round(100 * with_head / attempted) if attempted else None


def _resolve_playlist_query(query: str, lists: list[dict]) -> tuple[Optional[dict], Optional[dict]]:
    """A playlist he named — by link/URI/id or EXACT name. A close but inexact
    name is refused naming the candidate: the playlist Absorb links is the one
    it takes captured songs out of, so it is never guessed."""
    q = (query or "").strip()
    m = _PLAYLIST_LINK_RE.search(q)
    by_id = {p["id"]: p for p in lists if p.get("id")}
    if m or q in by_id:
        pid = m.group(1) if m else q
        if pid in by_id:
            return by_id[pid], None
        return None, {"status": "rejected",
                      "reason": "that playlist is not in his Spotify library — follow or "
                                "create it there first, or link it on the Absorb page"}
    match, rejection = name_resolve.resolve_name(
        q, [(p["id"], p.get("name") or "") for p in lists], noun="playlist")
    if rejection:
        return None, rejection
    if match.name.strip().lower() != q.lower():
        return None, {"status": "rejected",
                      "reason": f"no playlist is called {query!r} — the closest is "
                                f"{match.name!r}; say that name to link it",
                      "close_matches": [match.name]}
    return by_id[match.id], None


def _playlist_id(link: str) -> str:
    link = (link or "").strip()
    m = _PLAYLIST_LINK_RE.search(link)
    return m.group(1) if m else link


# ── reads ────────────────────────────────────────────────────────────────────

def _status_summary(brief: dict, sched: Optional[dict]) -> str:
    state = brief.get("state") or "idle"
    playlist = brief.get("source_playlist_name") or "the linked playlist"
    if state == "running":
        np_ = brief.get("now_playing") or {}
        now = (f"now on {np_.get('title') or np_.get('uri')} (attempt {np_.get('attempt')})"
               if np_ else f"stage: {brief.get('stage') or 'opening'}")
        line = (f"Absorb is running on “{playlist}” ({brief.get('started_by')}, "
                f"{_when(brief.get('started_ms'))}): {now}; {_counts_line(brief.get('counts'))}; "
                f"{brief.get('queue_len', 0)} left in the queue.")
        if brief.get("silent"):
            line += " The house is silent"
            line += " and the lights are standing down." if brief.get("lights_held") else "."
    elif state == "paused":
        line = (f"Absorb's window on “{playlist}” is paused: "
                f"{brief.get('wait_detail') or brief.get('wait_reason')} It comes back after his "
                f"music has been quiet. So far: {_counts_line(brief.get('counts'))}.")
    elif state == "idle":
        line = "Absorb has never run."
    else:
        verb = "was refused" if state == "refused" else "ended"
        line = (f"Absorb isn't running. The last window ({_when(brief.get('started_ms'))}) "
                f"{verb}: {brief.get('end_detail') or brief.get('end_reason')}")
        if state != "refused":
            line += f" It got {_counts_line(brief.get('counts'))}."
    if brief.get("restore_pending"):
        line += f" The house volume may still be silent: {brief['restore_pending']}."
    if sched is not None:
        if sched.get("active"):
            nxt = (sched.get("next") or {}).get("label")
            line += (f" The schedule is on ({'; '.join(w['label'] for w in sched.get('windows') or [])})"
                     + (f"; next window {nxt}." if nxt else "."))
        else:
            line += " The schedule is off — nothing opens on its own."
    return line


def _compact_run(r: dict) -> dict:
    hr = r.get("head_rate") or {}
    return {"run_id": r.get("id"), "label": _run_label(r), "state": r.get("state"),
            "started": _when(r.get("started_ms")), "started_by": r.get("started_by"),
            "end_reason": r.get("end_reason"), "end_detail": r.get("end_detail"),
            "playlist": r.get("source_playlist_name"), "counts": r.get("counts"),
            "head_rate": {"attempted": hr.get("attempted", 0),
                          "with_head": hr.get("with_head", 0)}}


async def _op_absorb_status(include_playlist: bool = False) -> dict:
    if not isinstance(include_playlist, bool):
        return {"status": "rejected", "reason": "include_playlist must be true or false"}
    run, err = await _get("/api/absorb/run", params={"history": 5})
    if err:
        return err
    sched, err = await _get("/api/absorb/schedule", params={"outcomes": 5})
    if err:
        return err
    brief = run.get("brief") or {"state": "idle"}
    out: dict = {
        "state": brief.get("state"),
        "running": brief.get("state") in ("running", "paused"),
        "brief": brief,
        "schedule": {
            "on": bool(sched.get("active")), "switched_on": bool(sched.get("enabled")),
            "windows": [w.get("label") for w in sched.get("windows") or []],
            "next": sched.get("next"),
            "recent": [{"label": o.get("label"), "outcome": o.get("outcome"),
                        "detail": o.get("detail")} for o in sched.get("outcomes") or []],
        },
        "earlier": [_compact_run(r) for r in run.get("earlier") or []],
        "summary": _status_summary(brief, sched),
    }
    lane, lerr = await _get("/api/absorb/lane")
    if not lerr:
        job = lane.get("job") or {}
        out["hidden_player"] = {
            "on": bool(lane.get("enabled")), "state": lane.get("state"),
            "why_resting": lane.get("reason") or "",
            "learning_now": (f"{job.get('artist')} — {job.get('title')}" if job.get("artist")
                             else job.get("title")) if job else None,
            "learned_lately": [x.get("title") for x in (lane.get("learned") or [])[-5:]],
            "passed_over": len(lane.get("passed_over") or [])}
    if include_playlist:
        preview, err = await _get("/api/absorb/preview", timeout=PREVIEW_TIMEOUT_S)
        out["playlist"] = preview if preview is not None else {"detail": err["reason"]}
    return out


def _head_line(entry: dict) -> str:
    att, wh = entry["attempted"], entry["with_head"]
    if not att:
        return f"{entry['label']}: no capture committed, so there is no head rate yet"
    line = f"{entry['label']}: {wh} of {att} committed captures landed their head ({entry['rate_pct']}%)"
    modes = []
    for mode, words in (("recapture", "re-captures"), ("fresh", "fresh captures")):
        m = entry["by_mode"].get(mode)
        if m and m["attempted"]:
            modes.append(f"{words} {m['with_head']} of {m['attempted']} ({m['rate_pct']}%)")
    if modes:
        line += " — " + ", ".join(modes)
    return line


async def _op_absorb_head_report(runs: int = 1) -> dict:
    if isinstance(runs, bool) or not isinstance(runs, int) or not (1 <= runs <= 20):
        return {"status": "rejected", "reason": "runs must be a whole number from 1 to 20"}
    body, err = await _get("/api/absorb/run", params={"history": 20})
    if err:
        return err
    every = ([body["run"]] if body.get("run") else []) + list(body.get("earlier") or [])

    def opened(r: dict) -> bool:
        hr, c = r.get("head_rate") or {}, r.get("counts") or {}
        return bool(r.get("opened_ms")) or bool(hr.get("attempted")) or any(c.values())

    picked, not_opened = [], []
    for r in every:
        if opened(r):
            picked.append(r)
            if len(picked) >= runs:
                break
        elif not picked:
            not_opened.append({"label": _run_label(r), "state": r.get("state"),
                               "detail": r.get("end_detail") or r.get("wait_detail")})
    windows = []
    tot = {"attempted": 0, "with_head": 0}
    for r in picked:
        hr = r.get("head_rate") or {}
        by_mode = {m: {"attempted": t.get("attempted", 0), "with_head": t.get("with_head", 0),
                       "rate_pct": _pct(t.get("with_head", 0), t.get("attempted", 0))}
                   for m, t in (hr.get("by_mode") or {}).items()}
        att, wh = hr.get("attempted", 0), hr.get("with_head", 0)
        tot["attempted"] += att
        tot["with_head"] += wh
        windows.append({"run_id": r.get("id"), "label": _run_label(r), "state": r.get("state"),
                        "attempted": att, "with_head": wh, "rate_pct": _pct(wh, att),
                        "by_mode": by_mode,
                        "head_missed": (r.get("counts") or {}).get("head_missed", 0),
                        "captured": (r.get("counts") or {}).get("captured", 0)})
    parts = [f"Newer than that, {n['label']} {'was refused' if n['state'] == 'refused' else 'never opened'}"
             f": {n['detail']}" for n in not_opened]
    if not windows:
        summary = ("Absorb has no window that opened yet, so there is no head rate."
                   + (" " + "; ".join(parts) + "." if parts else ""))
    else:
        summary = "; ".join(_head_line(w) for w in windows) + "."
        if len(windows) > 1:
            pct = _pct(tot["with_head"], tot["attempted"])
            summary += (f" Together: {tot['with_head']} of {tot['attempted']} ({pct}%)."
                        if tot["attempted"] else " Together: no capture committed.")
        if parts:
            summary = "; ".join(parts) + ". " + summary
    return {"windows": windows, "not_opened": not_opened,
            "total": {**tot, "rate_pct": _pct(tot["with_head"], tot["attempted"])},
            "summary": summary}


async def _op_list_absorb_parked() -> dict:
    body, err = await _get("/api/absorb/parked")
    if err:
        return err
    parked = body.get("parked") or []
    if not parked:
        summary = "No song is parked."
    else:
        shown = ", ".join(f"{p.get('title') or p.get('uri')} "
                          f"({_reason_words(p.get('reason') or p.get('last_failure'))}, "
                          f"{p.get('lifetime_attempts', 0)} attempts)" for p in parked[:10])
        summary = (f"{len(parked)} song{'s' if len(parked) != 1 else ''} parked: {shown}"
                   + (f", and {len(parked) - 10} more" if len(parked) > 10 else "") + ".")
    return {"parked": parked, "summary": summary}


async def _op_get_absorb_settings() -> dict:
    cfg, err = await _get("/api/absorb/config")
    if err:
        return err
    return {"settings": cfg,
            "windows": [window_label(w) for w in cfg.get("windows") or []],
            "schedule": _schedule_line(cfg),
            "changeable_by_voice": list(SETTING_KEYS),
            "summary": (f"Linked playlist: {cfg.get('source_playlist_uri') or 'none'}; schedule "
                        f"{_schedule_line(cfg)}; force recapture {_onoff(cfg.get('force_recapture'))}; "
                        f"{cfg.get('max_attempts')} attempts a song; "
                        f"keep going while the house sleeps: {_onoff(cfg.get('run_while_sleeping'))}.")}


# ── his presses ──────────────────────────────────────────────────────────────

async def _op_start_absorb(confirm_id: Optional[str] = None) -> dict:
    run, err = await _get("/api/absorb/run", params={"history": 0})
    if err:
        return err
    brief = run.get("brief") or {}
    if brief.get("state") in ("running", "paused"):
        return {"status": "rejected", "code": "already_running",
                "reason": f"Absorb is already running. {_status_summary(brief, None)}"}
    cfg, err = await _get("/api/absorb/config")
    if err:
        return err
    if not (cfg.get("source_playlist_uri") or "").strip():
        return {"status": "rejected", "code": "no_playlist",
                "reason": "No playlist is linked — link one first (set_absorb_playlist)."}
    fp = _fingerprint("start_absorb", {}, cfg)
    if confirm_id is None:
        preview, _ = await _get("/api/absorb/preview", timeout=QUESTION_PREVIEW_TIMEOUT_S)
        name = ((preview or {}).get("playlist") or {}).get("name") or cfg["source_playlist_uri"]
        question = f"Start Absorb Music now on “{name}”? {_START_QUESTION}"
        counts = (preview or {}).get("counts")
        if counts:
            question += (f" It holds {counts.get('total', 0)} songs: {counts.get('skip', 0)} already "
                         f"captured (filed without playing), {counts.get('fresh', 0)} to capture, "
                         f"{counts.get('recapture', 0)} to re-capture"
                         + (f", {counts['parked']} parked" if counts.get("parked") else "") + ".")
        if cfg.get("force_recapture"):
            question += " Force recapture is ON: every song plays and is captured again."
        return _ask("start_absorb", fp, question, playlist=preview)
    refusal = _redeem("start_absorb", fp, confirm_id)
    if refusal:
        return refusal
    try:
        r = await http("POST", "/api/absorb/start", json={"started_by": "sonic"},
                       timeout=START_TIMEOUT_S)
        r.raise_for_status()
        body = r.json()
    except Exception as exc:                             # noqa: BLE001
        if _is_timeout(exc):
            return {"status": "rejected", "code": "no_answer",
                    "reason": (f"SpotFX did not answer within {int(START_TIMEOUT_S)} s — the window "
                               "may still have opened. Read absorb_status before trying again.")}
        return _unreachable(exc)
    status, brief = body.get("status"), body.get("run") or {}
    detail = body.get("detail") or ""
    if status in ("running", "paused", "waiting"):
        return {"status": "applied", "state": status, "run": brief,
                "summary": f"Absorb started. {_status_summary(brief, None)}"}
    if status == "ended" and body.get("reason") in ("nothing_to_capture", "queue_done"):
        return {"status": "applied", "state": "ended", "run": brief,
                "summary": f"Absorb opened, then ended at once: {detail}"}
    return {"status": "rejected", "code": body.get("reason") or status,
            "reason": detail or f"Absorb did not start ({status}).", "run": brief}


async def _op_stop_absorb() -> dict:
    body, err = await _post("/api/absorb/stop")
    if err:
        return err
    brief = body.get("run") or {}
    if body.get("status") != "ended":
        return {"status": "rejected", "code": "not_running",
                "reason": "Absorb isn't running — there is no window to stop."}
    summary = f"Stopped Absorb. It got {_counts_line(brief.get('counts'))}."
    summary += (f" The house volume may still be silent: {brief['restore_pending']}."
                if brief.get("restore_pending") else " The house volume is given back.")
    return {"status": "applied", "run": brief, "summary": summary}


async def _op_absorb_skip_song() -> dict:
    run, err = await _get("/api/absorb/run", params={"history": 0})
    if err:
        return err
    np_ = (run.get("brief") or {}).get("now_playing") or {}
    body, err = await _post("/api/absorb/skip-song")
    if err:
        return err
    if body.get("status") != "skipped":
        return {"status": "rejected", "code": "nothing_playing",
                "reason": "No Absorb window is playing a song right now."}
    title = np_.get("title") if np_.get("uri") == body.get("skipped_uri") else ""
    return {"status": "applied", "skipped_uri": body.get("skipped_uri"),
            "summary": (f"Skipped {title or body.get('skipped_uri')} — it comes back after the "
                        "next song, and the skip is not counted as an attempt.")}


async def _op_retry_absorb_song(song: str) -> dict:
    if not isinstance(song, str) or not song.strip():
        return {"status": "rejected", "reason": "name the parked song to retry"}
    body, err = await _get("/api/absorb/parked")
    if err:
        return err
    parked = body.get("parked") or []
    match, rejection = name_resolve.resolve_name(
        song.strip(), [(p["uri"], p.get("title") or p["uri"]) for p in parked],
        noun="parked song")
    if rejection:
        return rejection
    done, err = await _post("/api/absorb/retry", {"uri": match.id})
    if err:
        return err
    if not done.get("unparked"):
        return {"status": "rejected", "reason": f"{match.name} is not parked any more."}
    return {"status": "applied", "uri": match.id,
            "summary": (f"Un-parked {match.name} — it is tried again in the next window, or "
                        "straight away if one is running.")}


# ── his settings ─────────────────────────────────────────────────────────────

async def _op_set_absorb_force_recapture(on: bool, confirm_id: Optional[str] = None) -> dict:
    if not isinstance(on, bool):
        return {"status": "rejected", "reason": "on must be true or false"}

    def question(before: dict, after: dict) -> Optional[str]:
        if after.get("force_recapture") and not before.get("force_recapture"):
            return ("Turn force recapture on? Every song in the playlist will play and be "
                    "captured again — even the ones that already pass, head and all.")
        return None

    def describe(before: dict, after: dict) -> str:
        b, a = before.get("force_recapture"), after.get("force_recapture")
        if b == a:
            return f"Force recapture was already {_onoff(a)} — nothing changed."
        meaning = (" Every song plays and is captured again, even the ones that pass." if a else
                   " Songs that already pass the bar are filed without playing.")
        return f"Force recapture: {_onoff(b)} → {_onoff(a)}.{meaning}"

    return await _config_write("set_absorb_force_recapture", {"force_recapture": on},
                               confirm_id=confirm_id, question=question, describe=describe)


async def _op_set_absorb_setting(key: str, value: Any, confirm_id: Optional[str] = None) -> dict:
    if key not in SETTING_KEYS:
        return {"status": "rejected",
                "reason": f"unknown setting {key!r} — known: {', '.join(SETTING_KEYS)}"}
    # pydantic would quietly read true as 1 and 1 as true
    if (key in _BOOL_KEYS) != isinstance(value, bool):
        return {"status": "rejected",
                "reason": (f"{key} must be true or false" if key in _BOOL_KEYS
                           else f"{key} must be a whole number")}

    def question(before: dict, after: dict) -> Optional[str]:
        b, a = before.get(key), after.get(key)
        if key == "run_while_sleeping" and a and not b:
            return ("Let Absorb windows keep going after the house goes to sleep? It is the "
                    "Order 27 exception you granted for Absorb only: it rests on the silence "
                    "proof, re-proven every minute, and the window stops if a room can't be "
                    "read or silenced.")
        if key == "use_capture_lane" and a and not b:
            return ("Let the hidden player learn the linked playlist's never-captured songs on its "
                    "own, one at a time, whenever no Absorb window or Jukebox night is running and "
                    "the house is awake? It plays only on Serenity Capture under the second "
                    "account — nothing is heard — and it never changes your playlists; Absorb files "
                    "the songs it learned at its next window.")
        if key == "recently_captured_max" and isinstance(a, int) and isinstance(b, int) and a < b:
            return (f"Lower Recently Captured's cap from {b} to {a}? The next time a song is "
                    f"filed, every song past the newest {a} is taken out of Recently Captured.")
        return None

    def describe(before: dict, after: dict) -> str:
        b, a = before.get(key), after.get(key)
        if isinstance(a, bool):
            b, a = _onoff(b), _onoff(a)
        if b == a:
            return f"{_SETTING_LABELS[key].capitalize()} was already {a} — nothing changed."
        return f"{_SETTING_LABELS[key].capitalize()}: {b} → {a}."

    return await _config_write("set_absorb_setting", {key: value},
                               confirm_id=confirm_id, question=question, describe=describe)


async def _op_set_absorb_window(windows: Optional[list] = None,
                                schedule_on: Optional[bool] = None,
                                confirm_id: Optional[str] = None) -> dict:
    if windows is None and schedule_on is None:
        return {"status": "rejected",
                "reason": "give the windows, or schedule_on, or both"}
    if schedule_on is not None and not isinstance(schedule_on, bool):
        return {"status": "rejected", "reason": "schedule_on must be true or false"}
    if windows is not None and not isinstance(windows, list):
        return {"status": "rejected", "reason": "windows must be a list of {days, start, end}"}
    patch: dict = {}
    if windows is not None:
        patch["windows"] = [dict(w, days=list(DAYS)) if isinstance(w, dict) and "days" not in w
                            else w for w in windows]
    if schedule_on is not None:
        patch["enabled"] = schedule_on

    def question(before: dict, after: dict) -> Optional[str]:
        if not _opens_on_its_own(after):
            return None
        if _opens_on_its_own(before) and _windows_key(before) == _windows_key(after):
            return None
        labels = "; ".join(window_label(w) for w in after.get("windows") or [])
        return (f"Let Absorb open on its own {labels} (house time)? Each window turns the house "
                "volume to 0 (the capture client is left alone), proves every room is silent and "
                "plays the linked playlist on Serenity — nobody has to press anything.")

    def describe(before: dict, after: dict) -> str:
        b, a = _schedule_line(before), _schedule_line(after)
        if b == a:
            return f"The schedule was already {a} — nothing changed."
        return f"Schedule: {b} → {a}."

    return await _config_write("set_absorb_window", patch,
                               confirm_id=confirm_id, question=question, describe=describe)


async def _op_set_absorb_playlist(playlist: str, confirm_id: Optional[str] = None) -> dict:
    if not isinstance(playlist, str) or not playlist.strip():
        return {"status": "rejected", "reason": "name the playlist to absorb from"}
    body, err = await _get("/api/absorb/playlists", timeout=PREVIEW_TIMEOUT_S)
    if err:
        return err
    lists = body.get("playlists")
    if lists is None:
        return {"status": "rejected",
                "reason": body.get("detail") or "his Spotify playlists couldn't be read"}
    chosen, rejection = _resolve_playlist_query(playlist, lists)
    if rejection:
        return rejection
    if not chosen.get("editable"):
        return {"status": "rejected",
                "reason": (f"“{chosen.get('name')}” is a playlist he follows but does not own, so "
                           "Absorb could not move captured songs out of it — make a copy of it "
                           "he owns, and link that.")}
    names = {p["id"]: p.get("name") or "" for p in lists}

    def name_of(cfg: dict) -> str:
        pid = _playlist_id(cfg.get("source_playlist_uri") or "")
        return names.get(pid) or (cfg.get("source_playlist_uri") or "") or "none"

    def question(before: dict, after: dict) -> Optional[str]:
        if not _opens_on_its_own(before):
            return None
        if _playlist_id(before.get("source_playlist_uri") or "") == chosen["id"]:
            return None
        labels = "; ".join(window_label(w) for w in before.get("windows") or [])
        return (f"Link “{chosen.get('name')}” as Absorb's playlist? The schedule is on ({labels}), "
                f"so the next window plays it with the house silent and moves each captured song "
                f"out of “{chosen.get('name')}” and into Recently Captured.")

    def describe(before: dict, after: dict) -> str:
        if _playlist_id(before.get("source_playlist_uri") or "") == chosen["id"]:
            return f"“{chosen.get('name')}” was already the linked playlist — nothing changed."
        return (f"Linked playlist: “{name_of(before)}” → “{chosen.get('name')}” "
                f"({chosen.get('tracks', 0)} songs).")

    return await _config_write("set_absorb_playlist", {"source_playlist_uri": chosen["uri"]},
                               confirm_id=confirm_id, question=question, describe=describe)


# ── declarations ─────────────────────────────────────────────────────────────

_INSTR_COMMON = (
    "Absorb Music plays a linked Spotify playlist on Serenity with the house volume at 0 so "
    "SpotFX captures every song's audio shape (the recording every timing feature is built "
    "on). It files songs that are already captured without playing them, captures the ones "
    "with no shape, re-captures the ones whose shape is missing its head, and moves each "
    "captured song out of the playlist and on top of \"Recently Captured\". ")

_INSTR_CONFIRM = (
    "When the result's status is needs_confirmation NOTHING has happened yet: read him its "
    "`question` in plain words and wait. Only after he says yes, call this again with the same "
    "arguments plus that confirm_id. Never call with a confirm_id he has not said yes to. ")

_CONFIRM_PROP = {"type": "string",
                 "description": "The confirm_id a needs_confirmation result returned — only "
                                "after he said yes to its question."}

OPERATIONS: dict[str, SonicOperation] = {
    "absorb_status": SonicOperation(
        name="absorb_status", domain="absorb", kind="read",
        summary="Is Absorb Music running, what is it doing, what did the last windows get, "
                "and when does the schedule open next.",
        instructions=(
            _INSTR_COMMON
            + "Use for 'is absorb running?', 'how many did it get last night?', 'why didn't "
            "it run?'. `summary` is the sentence to say; `brief` is the live (or last) window "
            "(state running/paused/ended/refused/idle, counts: captured, skipped = already "
            "captured, failed, requeued, head_missed, parked); `earlier` the windows before it; "
            "`schedule.recent` what the schedule did with each evening (opened / waiting / "
            "refused, with why). Pass include_playlist=true to also read the linked playlist's "
            "split (already captured / to capture / to re-capture) — slower, it reads the whole "
            "playlist from Spotify."),
        input_schema={
            "type": "object",
            "properties": {"include_playlist": {"type": "boolean", "default": False}},
            "additionalProperties": False},
        handler=_op_absorb_status),
    "absorb_head_report": SonicOperation(
        name="absorb_head_report", domain="absorb", kind="read",
        summary="How many of the captures that committed landed their head — last night's "
                "window, or the last few.",
        instructions=(
            _INSTR_COMMON
            + "Use for 'how many got their heads last night?'. A capture only counts once it "
            "committed; it has its head when its shape starts within the first second of the "
            "song. The re-capture rate is the number that says how many evenings the backlog "
            "still needs. runs=1 (the default) is the latest window that opened; a newer one "
            "that was refused or never opened is named in `not_opened` and in the summary. "
            "Pass runs=7 for 'this week'. A window with no committed capture has NO head rate "
            "— say so, never call it 0%."),
        input_schema={
            "type": "object",
            "properties": {"runs": {"type": "integer", "minimum": 1, "maximum": 20, "default": 1}},
            "additionalProperties": False},
        handler=_op_absorb_head_report),
    "start_absorb": SonicOperation(
        name="start_absorb", domain="absorb", kind="write",
        summary="Start an Absorb window now on the linked playlist (asks him first).",
        instructions=(
            _INSTR_COMMON + _INSTR_CONFIRM
            + "This is the same Start as the Absorb page and goes through SpotFX's own start "
            "route, so every refusal it has applies and comes back as `reason` — music already "
            "playing, no playlist linked, a night or camera run, the silence proof failing, "
            "River's hard block, the sleeping-house rule. Tell him the reason; never retry "
            "around it. A window started here is recorded as started by Sonic."),
        input_schema={
            "type": "object",
            "properties": {"confirm_id": _CONFIRM_PROP},
            "additionalProperties": False},
        handler=_op_start_absorb),
    "stop_absorb": SonicOperation(
        name="stop_absorb", domain="absorb", kind="write",
        summary="Stop the Absorb window now and give the house back.",
        instructions=(
            _INSTR_COMMON
            + "Ends the window at once — scheduled or started by hand — exactly like the "
            "page's Stop: playback pauses (never his own music), the house volume is put back "
            "and read back, the lights come back. No confirmation: stopping is the safe way. "
            "The summary says whether the house volume is back."),
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=_op_stop_absorb),
    "absorb_skip_song": SonicOperation(
        name="absorb_skip_song", domain="absorb", kind="write",
        summary="Skip the song Absorb is playing; it comes back after the next one.",
        instructions=(
            _INSTR_COMMON
            + "Moves on now. The song goes back in the queue after the next one and the skip is "
            "not counted as a failed attempt."),
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=_op_absorb_skip_song),
    "list_absorb_parked": SonicOperation(
        name="list_absorb_parked", domain="absorb", kind="read",
        summary="Which songs Absorb is stuck on (parked after too many failed attempts).",
        instructions=(
            _INSTR_COMMON
            + "A parked song stays in the playlist and is left out of later windows until he "
            "retries it. `reason`/`last_failure` are tags (head_unreachable = its head never "
            "arrived); `summary` already says them in plain words — use those."),
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=_op_list_absorb_parked),
    "retry_absorb_song": SonicOperation(
        name="retry_absorb_song", domain="absorb", kind="write",
        summary="Un-park one parked song so Absorb tries it again.",
        instructions=(
            _INSTR_COMMON
            + "One song at a time, by its title (or spotify:track: URI) from "
            "list_absorb_parked. It is tried again at the next window, or straight away if one "
            "is running. A name that matches no parked song, or two of them, is refused with "
            "the candidates — ask him which."),
        input_schema={
            "type": "object",
            "properties": {"song": {"type": "string"}},
            "required": ["song"],
            "additionalProperties": False},
        handler=_op_retry_absorb_song),
    "get_absorb_settings": SonicOperation(
        name="get_absorb_settings", domain="absorb", kind="read",
        summary="Read Absorb's settings: linked playlist, schedule, force recapture, attempts, "
                "and the rest.",
        instructions=(
            _INSTR_COMMON
            + "Call before changing anything. `changeable_by_voice` lists what "
            "set_absorb_setting takes; the playlist, schedule and force recapture have their "
            "own operations. The rest (the head bar head_max_ms, order, warm_up, the quiet "
            "rules, the silence re-proof cadence, Recently Captured's name) are his plan's "
            "decisions — readable here, not changed by voice."),
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=_op_get_absorb_settings),
    "set_absorb_setting": SonicOperation(
        name="set_absorb_setting", domain="absorb", kind="write",
        summary="Change one of Absorb's numbers (attempts, songs sent at a time, overrun grace, "
                "Recently Captured's cap), whether it keeps going while the house sleeps, or "
                "whether the hidden player learns the backlog when nothing else runs.",
        instructions=(
            _INSTR_COMMON + _INSTR_CONFIRM
            + "One key per call. max_attempts = attempts per song in one window before it is "
            "parked; play_window_size = songs sent to Spotify at a time; overrun_grace_min = "
            "minutes a song may run past a scheduled window's end and still be finished; "
            "recently_captured_max = how many songs Recently Captured keeps (lowering it asks "
            "first — the oldest are taken out); run_while_sleeping = true/false (turning it "
            "back on asks first); use_capture_lane = true/false (the hidden player Serenity "
            "Capture learns the playlist's never-captured songs inaudibly whenever no window or "
            "Jukebox night runs and the house is awake — and only while the second Spotify "
            "account's switch on the Settings page is on, which only he changes; turning it "
            "on asks first). An "
            "out-of-range value is refused with SpotFX's own reason — tell him the reason."),
        input_schema={
            "type": "object",
            "properties": {
                "key": {"type": "string", "enum": list(SETTING_KEYS)},
                "value": {"type": ["boolean", "integer"]},
                "confirm_id": _CONFIRM_PROP,
            },
            "required": ["key", "value"],
            "additionalProperties": False},
        handler=_op_set_absorb_setting),
    "set_absorb_force_recapture": SonicOperation(
        name="set_absorb_force_recapture", domain="absorb", kind="write",
        summary="Turn Absorb's force recapture tag on or off (on asks first).",
        instructions=(
            _INSTR_COMMON + _INSTR_CONFIRM
            + "Off by default. A normal window already re-captures every song missing its head, "
            "so ON means 're-capture even the ones that pass': every song plays and is captured "
            "again, nothing is skipped. Turning it on asks first (the page asks too); off "
            "applies at once."),
        input_schema={
            "type": "object",
            "properties": {"on": {"type": "boolean"}, "confirm_id": _CONFIRM_PROP},
            "required": ["on"],
            "additionalProperties": False},
        handler=_op_set_absorb_force_recapture),
    "set_absorb_window": SonicOperation(
        name="set_absorb_window", domain="absorb", kind="write",
        summary="Set Absorb's evening schedule — its windows (days, start, end in house time) "
                "and/or switch the schedule on or off.",
        instructions=(
            _INSTR_COMMON + _INSTR_CONFIRM
            + "`windows` REPLACES the whole list (read get_absorb_settings first to add one "
            "beside the others; [] clears them). Each is {days, start, end}: days from "
            "mon..sun (omit for every day; they name the evening it STARTS on), start/end "
            "HH:MM 24-hour New York time; an end before the start runs past midnight. A window "
            "opens on its own only while the schedule is on: for 'absorb every night from nine "
            "thirty to half past midnight' send windows=[{start:'21:30', end:'00:30'}] and "
            "schedule_on=true. Anything that newly lets windows open on their own asks first; "
            "switching the schedule off applies at once (a window already open is not stopped "
            "— use stop_absorb). An impossible window is refused with SpotFX's own reason."),
        input_schema={
            "type": "object",
            "properties": {
                "windows": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "days": {"type": "array", "items": {"type": "string",
                                                                "enum": list(DAYS)}},
                            "start": {"type": "string", "description": "HH:MM, house time"},
                            "end": {"type": "string", "description": "HH:MM, house time"},
                        },
                        "required": ["start", "end"],
                        "additionalProperties": False}},
                "schedule_on": {"type": "boolean"},
                "confirm_id": _CONFIRM_PROP,
            },
            "additionalProperties": False},
        handler=_op_set_absorb_window),
    "set_absorb_playlist": SonicOperation(
        name="set_absorb_playlist", domain="absorb", kind="write",
        summary="Link the Spotify playlist Absorb captures from, by its name.",
        instructions=(
            _INSTR_COMMON + _INSTR_CONFIRM
            + "Give the playlist's name exactly as it is in his Spotify library (or paste its "
            "link). A close but inexact name is refused naming the closest one — ask him "
            "whether he meant it, never link it on a guess: Absorb takes captured songs OUT of "
            "this playlist. A playlist he follows but doesn't own is refused (Absorb couldn't "
            "edit it). While the schedule is on, changing the playlist asks first."),
        input_schema={
            "type": "object",
            "properties": {"playlist": {"type": "string"}, "confirm_id": _CONFIRM_PROP},
            "required": ["playlist"],
            "additionalProperties": False},
        handler=_op_set_absorb_playlist),
}
