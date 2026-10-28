"""SPECTRA — Sonic's `jukebox` domain (data/jukebox-plan/report.md phase 3
PR 3.4's Sonic follow-up): the Jukebox as it exists today — the host's set
list with jukebox slots, the show's credits settings, the party-size
presets, the price check and the party simulator — reached by voice.

THE JUKEBOX LIVES IN SPOTFX (services/jukebox/, routers/jukebox_router.py),
and SPECTRA may not import it (scripts/check_process_split.py), so every
operation here is an HTTP call to SpotFX's own /api/jukebox routes — the
very routes the Jukebox page uses. Nothing Sonic does can get around a gate
the page has: a start through Sonic is the same Start, refused for the same
reasons (no set playlist, the house asleep, Absorb running, a Spotify
failure), in the same words. lock_console.py's and absorb_console.py's
shape.

EVERY CHANGE ASKS FIRST (firstmate's order for this domain: "Sonic changes
ask first; start/stop a night must refuse unless explicitly confirmed").
A write is two calls: the first validates — a settings change by SpotFX's
own dry run, so he is never asked about a change that would be refused —
and answers `needs_confirmation` with a single-use `confirm_id` and the
question to read him; only the second call, carrying that id after his yes,
acts. The id is bound to the operation, its arguments and the state he was
asked about (his settings; for a stop, WHICH night), so a yes never covers a
question that changed in between, and it expires after CONFIRM_TTL_S.
Starting and stopping a night are always asked — there is no "already
confirmed" flag and no way to skip the question.

The reads (status, settings, the price check, the simulator) act at once:
the simulator is a model night that writes nothing.

What stays off-limits, each named so an audit can tell "considered and
excluded" from "forgotten":
  * the printed BONUS CARDS' codes (making, listing, voiding them) — they
    are for printing on cards, on the Credits tab's Bonus cards card and the
    printable card page; a code read aloud is a code given away;
  * SAVING and DELETING a saved show (§4: "a 'show' is a saved set of
    these") — saving replaces a show of the same name and deleting loses
    one, both by a name heard aloud; they are the Credits tab's Show card.
    Listing and LOADING one (asking first) are Sonic's — and Sonic's load
    leaves the GUEST LINK as it is (below), whatever the show saved;
  * PRINTING THE CARDS (/jukebox/cards, the plan's N2) — the guest Wi-Fi's
    password is typed on that page at print time and never leaves it, so
    there is nothing for a voice to set; and printing is a sheet of paper
    in his hand, not a setting;
  * a guest's own acts on the guest page — joining, the name a phone picks,
    its votes, the songs it adds — are the guests', never the host's to make
    by voice (`jukebox_status` reads how many phones are on the page);
  * the host's controls over a PHONE (approve, block, rename, lock its name;
    PR 2.2; pardon a guest in a time-out, PR 2.3; zero its credits and
    merge two phones into one guest, §4's host buttons) — they act on a person
    standing in his room, by name, and a misheard name would block, rename
    or free the wrong guest; they are the Guests tab's buttons, where each
    phone is shown;
  * the jukebox LINE — adding, removing and moving songs (bumps, play
    next), and keeping a song from skips (PR 3.2), are the guests' turn and
    the host's page, where each song is shown;
  * reordering the SET PLAYLIST — it rewrites his playlist's order in
    Spotify; a drag on the page, where the set is shown song by song;
  * the GUEST LINK (N1, SpotFX's services/jukebox/guest_link.py) —
    switching it on publishes a port of Serenity on the internet through
    Tailscale Funnel each night; that is his own act, after G4, never a
    voice one;
  * linking the set playlist and placing Manual slots — the editor shows
    the set and the slots it makes, song by song, and Manual slots are
    placed by hand on it (Sonic reads which playlist is linked and how many
    hand-placed slots there are; "mode" may be set to auto or jukebox first,
    never to manual, which with no slots placed would give the jukebox none).
"""
from __future__ import annotations

import difflib
import json as _json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

from spectra.services.sonic_ops import SonicOperation

HTTP_TIMEOUT_S = 10.0
# a start resolves the playlist, reads it whole and starts playback, all
# inside SpotFX before it answers; the simulator runs forty model nights.
# Both stay inside the CLI backend's own 60 s forward.
START_TIMEOUT_S = 45.0
SIMULATE_TIMEOUT_S = 45.0
CONFIRM_TTL_S = 300.0
_PENDING_MAX = 50
HOUSE_TZ = "America/New_York"

#: the program settings Sonic changes (ProgramConfig's scalar fields;
#: the playlist and the manual slots are the page's — see the docstring)
PROGRAM_KEYS: tuple[str, ...] = ("mode", "every", "run", "run_out", "commit_lead_s", "next_jumps_set")
MODES: tuple[str, ...] = ("auto", "jukebox_first")
RUN_OUTS: tuple[str, ...] = ("again", "jukebox_only", "end")
PRESETS: tuple[str, ...] = ("small", "medium", "large")
SIM_PROGRAMS: tuple[str, ...] = ("saved", "preset")
SHOW_KEYS: tuple[str, ...] = ("approve_new_phones", "play_mode")
#: the guests' own rules (phase 2.2, top level in SpotFX's ShowConfig): when
#: the night ends and requests close, explicit songs, phones, renames, the
#: word filter — the same one validator a page edit runs
GUEST_RULE_KEYS: tuple[str, ...] = ("night_ends", "last_call_min", "explicit", "explicit_after",
                                    "max_phones", "renames_per_night", "word_filter",
                                    # free play (PR 2.3): the room's skip, bumps,
                                    # play next, the jail's time-out
                                    "free_skip_downs", "free_skip_share", "free_bumps_per_hour",
                                    "free_play_next", "free_jail_songs",
                                    # the board (§4's Board card): the people
                                    # boards are his call and ship off (D1)
                                    "board_on", "board_top_pickers", "board_top_voters",
                                    "board_most_generous", "board_on_tv")

_PROGRAM_LABELS = {
    "mode": "where the jukebox slots go",
    "every": "a jukebox slot after every this many set songs",
    "run": "jukebox slots in a row",
    "run_out": "what happens when the set runs out",
    "commit_lead_s": "seconds before a slot that its song is sent to Spotify",
    "next_jumps_set": "play next may jump the set",
    "approve_new_phones": "new phones need his approval",
    "play_mode": "the guest page's mode (credits, or free play)",
}
_RUN_OUT_WORDS = {"again": "the set plays again", "jukebox_only": "only the jukebox plays",
                  "end": "the night ends"}


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
        return await client.request(method, f"{_base_url()}{path}", params=params, json=json)


#: injectable for tests
http = _http


def _unreachable(exc: Exception) -> dict:
    return {"status": "rejected",
            "reason": f"SpotFX (the root process, where the Jukebox runs) did not answer: {exc}"}


def _detail_sentence(detail: Any) -> str:
    if isinstance(detail, list):
        parts = []
        for d in detail:
            if isinstance(d, dict):
                loc = d.get("loc")
                field = d.get("field") or (loc[-1] if isinstance(loc, (list, tuple)) and loc else None)
                err = d.get("error") or d.get("msg")
                parts.append(f"{field}: {err}" if field else str(err))
            else:
                parts.append(str(d))
        return "; ".join(parts)
    return str(detail)


async def _request(method: str, path: str, *, params: Optional[dict] = None, body: Any = None,
                   timeout: float = HTTP_TIMEOUT_S) -> tuple[Optional[dict], Optional[dict]]:
    """(body, None) or (None, rejection). A 409/422 is SpotFX refusing by
    name: its detail is the reason, said as SpotFX said it."""
    try:
        r = await http(method, path, params=params, json=body, timeout=timeout)
    except Exception as exc:                             # noqa: BLE001
        return None, _unreachable(exc)
    if r.status_code in (409, 422):
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


async def _get(path: str, **kw) -> tuple[Optional[dict], Optional[dict]]:
    return await _request("GET", path, **kw)


# ── asking first ─────────────────────────────────────────────────────────────

@dataclass
class _Ask:
    op: str
    fingerprint: str
    expires: float


_PENDING: dict[str, _Ask] = {}
#: injectable for tests
_clock: Callable[[], float] = time.monotonic


def _fingerprint(op: str, args: dict, state: Any) -> str:
    return _json.dumps({"op": op, "args": args, "state": state}, sort_keys=True, default=str)


def _ask(op: str, fingerprint: str, question: str, **extra: Any) -> dict:
    now = _clock()
    for k in [k for k, a in _PENDING.items() if a.expires <= now]:
        del _PENDING[k]
    while len(_PENDING) >= _PENDING_MAX:
        del _PENDING[next(iter(_PENDING))]
    cid = uuid.uuid4().hex[:12]
    _PENDING[cid] = _Ask(op, fingerprint, now + CONFIRM_TTL_S)
    return {"status": "needs_confirmation", "op": op, "confirm_id": cid, "question": question,
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
                "reason": "that confirmation expired — call it again without a confirm_id and "
                          "ask him again"}
    if a.fingerprint != fingerprint:
        return {"status": "rejected",
                "reason": "something changed since he was asked (the request, his Jukebox "
                          "settings or the night), so his yes no longer covers it — ask him again"}
    return None


def _gate(op: str, args: dict, state: Any, confirm_id: Any, question: str,
          **extra: Any) -> Optional[dict]:
    """None when this call carries his yes to exactly this question;
    otherwise the answer to return (the question, or why the yes is void)."""
    fp = _fingerprint(op, args, state)
    if confirm_id is None:
        return _ask(op, fp, question, **extra)
    return _redeem(op, fp, confirm_id)


# ── words ────────────────────────────────────────────────────────────────────

def _when(ms: Any) -> str:
    try:
        dt = datetime.fromtimestamp(int(ms) / 1000, ZoneInfo(HOUSE_TZ))
    except Exception:                                    # noqa: BLE001
        return "?"
    return dt.strftime("%a %H:%M")


def program_words(cfg: dict) -> str:
    mode = cfg.get("mode")
    if mode == "jukebox_first":
        return "jukebox first: the set plays only when nobody has a song waiting"
    if mode == "manual":
        n = len(cfg.get("manual") or [])
        return f"Manual: {n} hand-placed slot run{'' if n == 1 else 's'}"
    every, run = cfg.get("every", 1), cfg.get("run", 1)
    sets = "every set song" if every == 1 else f"every {every} set songs"
    juke = "a jukebox slot" if run == 1 else f"{run} jukebox slots"
    return f"{juke} after {sets}"


def _value_words(key: str, v: Any) -> str:
    if key == "mode":
        return {"auto": "Auto", "jukebox_first": "jukebox first", "manual": "Manual"}.get(v, str(v))
    if key == "run_out":
        return _RUN_OUT_WORDS.get(v, str(v))
    if isinstance(v, bool):
        return "on" if v else "off"
    return str(v)


def _status_summary(st: dict) -> str:
    n = st.get("night")
    if not st.get("running"):
        if n and n.get("ended_ms"):
            return (f"No night is running. The last one ({n.get('playlist_name') or 'the set'}) "
                    f"ended {_when(n['ended_ms'])}: {n.get('end_detail') or n.get('end_reason')}.")
        return "No night is running."
    now = st.get("now") or {}
    kind = {"set": "a set song", "jukebox": "a jukebox song", "skipping": "being skipped",
            "foreign": "off the set (the Jukebox waits until the set plays again)"}.get(
        now.get("kind"), "")
    line = st.get("line") or []
    waiting = sum(1 for e in line if e.get("state") in ("queued", "committed"))
    parts = [f"A night is running on {n.get('playlist_name') or 'the set'} since "
             f"{_when(n.get('started_ms'))} (started by {n.get('started_by')})."]
    if now.get("title"):
        parts.append(f"Playing: {now['title']}{f' — {kind}' if kind else ''}.")
    parts.append(f"{waiting} song{'' if waiting == 1 else 's'} waiting in the jukebox line; "
                 f"{n.get('played', 0)} played so far ({n.get('jukebox_played', 0)} from the jukebox).")
    g = st.get("guests") or {}
    if g.get("phones"):
        parts.append(f"{g['phones']} phone{'' if g['phones'] == 1 else 's'} on the guest page "
                     f"({g.get('joined', 0)} joined).")
    return " ".join(parts)


# ── reads ────────────────────────────────────────────────────────────────────

async def _settings() -> tuple[Optional[dict], Optional[dict]]:
    cfg, err = await _get("/api/jukebox/config")
    if err:
        return None, err
    show, err = await _get("/api/jukebox/show")
    if err:
        return None, err
    return {"program": cfg, "show": show}, None


async def _op_jukebox_status() -> dict:
    st, err = await _get("/api/jukebox/status", params={"count": 10})
    if err:
        return err
    nxt = [{k: i.get(k) for k in ("kind", "title", "starts_in_ms", "entry_id") if k in i}
           for i in (st.get("next") or [])[:10]]
    return {"status": "ok", "summary": _status_summary(st), "running": bool(st.get("running")),
            "night": st.get("night"), "now": st.get("now"), "next": nxt,
            "line": st.get("line") or [], "warnings": st.get("warnings") or [],
            "spotify_sign_in": st.get("spotify_auth"), "guests": st.get("guests")}


async def _op_get_jukebox_settings() -> dict:
    s, err = await _settings()
    if err:
        return err
    cfg, show = s["program"], s["show"]
    fields = [{k: f.get(k) for k in ("key", "card", "label", "unit", "kind", "min", "max", "default")}
              for f in show.get("fields") or []]
    return {"status": "ok",
            "program": {"playlist": cfg.get("playlist") or None, "words": program_words(cfg),
                        **{k: cfg.get(k) for k in PROGRAM_KEYS},
                        "manual_slot_runs": len(cfg.get("manual") or [])},
            "preset": (show.get("show") or {}).get("preset"),
            "approve_new_phones": (show.get("show") or {}).get("approve_new_phones"),
            "play_mode": (show.get("show") or {}).get("play_mode") or "credits",
            "guest_rules": {k: (show.get("show") or {}).get(k) for k in GUEST_RULE_KEYS},
            "economy": (show.get("show") or {}).get("economy") or {},
            "economy_fields": fields,
            "presets": show.get("presets") or []}


async def _op_jukebox_price_check(guests: int = 15) -> dict:
    pc, err = await _get("/api/jukebox/price-check", params={"guests": int(guests)})
    if err:
        return err
    return {"status": "ok", **pc}


async def _op_simulate_jukebox_party(guests: int = 20, program: str = "saved",
                                     nights: int = 20, seed: int = 1) -> dict:
    if program not in SIM_PROGRAMS:
        return {"status": "rejected", "reason": f"program must be one of {', '.join(SIM_PROGRAMS)}"}
    r, err = await _request("POST", "/api/jukebox/simulate", timeout=SIMULATE_TIMEOUT_S,
                            body={"guests": int(guests), "nights": int(nights), "seed": int(seed),
                                  "program": program})
    if err:
        return err
    failed = [c for c in r.get("checks") or [] if c.get("ok") is False]
    summary = (f"{r.get('nights')} model nights at {r.get('guests')} guests, {r.get('program')}"
               f"{'; your credits settings are the tuned ones' if r.get('same_as_tuned') else ''}. "
               + ("Every promise held." if not failed else
                  "Missed: " + "; ".join(f"{c['label']} ({c.get('value')}, wanted {c['target']})"
                                         for c in failed) + "."))
    if failed and not r.get("mix_is_plans"):
        summary += f" The plan's preset for {r.get('guests')} guests is {r.get('plan_preset')}."
    return {"status": "ok", "summary": summary, "guests": r.get("guests"),
            "nights": r.get("nights"), "program": r.get("program"),
            "same_as_tuned": r.get("same_as_tuned"), "plan_preset": r.get("plan_preset"),
            "mix_is_plans": r.get("mix_is_plans"), "checks": r.get("checks") or [],
            "rows": r.get("rows") or [],
            "note": "a model night: guests and songs are the plan's model, the prices are the real "
                    "rules under his saved settings; nothing reached Spotify or the room"}


async def _op_jukebox_night_report(guests: Optional[int] = None) -> dict:
    params = {"guests": int(guests)} if guests else None
    r, err = await _request("GET", "/api/jukebox/report", params=params, timeout=SIMULATE_TIMEOUT_S)
    if err:
        return err
    if r.get("status") != "ok":
        return {"status": "ok", "summary": r.get("summary") or "No night has been played yet."}
    cmp_rows = (r.get("comparison") or {}).get("rows") or []
    return {"status": "ok", "summary": r.get("summary"), "night": r.get("night"),
            "credits": r.get("credits"), "ledger_problems": r.get("integrity") or [],
            "guests": r.get("guests"), "guests_from": r.get("guests_from"),
            "rows": [{k: x.get(k) for k in ("key", "label", "unit", "this_night", "yours", "why")}
                     for x in (cmp_rows or r.get("rows") or [])]}


# ── writes (every one asks first) ────────────────────────────────────────────

async def _op_set_jukebox_setting(key: str, value: Any, confirm_id: Optional[str] = None) -> dict:
    s, err = await _settings()
    if err:
        return err
    cfg, show = s["program"], s["show"]
    econ_keys = {f.get("key") for f in show.get("fields") or []}
    if key in PROGRAM_KEYS:
        if key == "mode" and value not in MODES:
            return {"status": "rejected",
                    "reason": "mode may be set to auto or jukebox_first; Manual slots are placed by "
                              "hand on the Jukebox page (with none placed, Manual would give the "
                              "jukebox no slots)"}
        path, patch = "/api/jukebox/config", {key: value}
        old = cfg.get(key)
    elif key in SHOW_KEYS or key in GUEST_RULE_KEYS:
        path, patch = "/api/jukebox/show", {key: value}
        old = (show.get("show") or {}).get(key)
    elif key in econ_keys:
        path, patch = "/api/jukebox/show", {"economy": {key: value}}
        old = ((show.get("show") or {}).get("economy") or {}).get(key)
    else:
        return {"status": "rejected",
                "reason": f"{key!r} is not a Jukebox setting Sonic changes — call "
                          "get_jukebox_settings for the program keys, approve_new_phones, the "
                          "guest rules and every economy key (the playlist and Manual slots are "
                          "set on the page)"}
    dry, err = await _request("PUT", path, params={"dry_run": "true"}, body=patch)
    if err:
        return err
    new = ((dry.get("config") or {}).get(key) if path.endswith("/config")
           else (dry.get("show") or {}).get(key) if key in SHOW_KEYS or key in GUEST_RULE_KEYS
           else ((dry.get("show") or {}).get("economy") or {}).get(key))
    label = _PROGRAM_LABELS.get(key) or next(
        (f.get("label") for f in (show.get("fields") or []) + (show.get("guest_fields") or [])
         if f.get("key") == key), key)
    if new == old:
        if isinstance(confirm_id, str):
            _PENDING.pop(confirm_id, None)
        return {"status": "unchanged", "summary": f"{label} is already {_value_words(key, old)}."}
    change = f"{label}: {_value_words(key, old)} → {_value_words(key, new)}"
    refusal = _gate("set_jukebox_setting", {"key": key, "value": value}, s, confirm_id,
                    f"Change the Jukebox's {change}?", would_change=change)
    if refusal:
        return refusal
    _, err = await _request("PUT", path, body=patch)
    if err:
        return err
    return {"status": "applied", "old": {key: old}, "new": {key: new}, "summary": change}


async def _op_apply_jukebox_preset(preset: str, confirm_id: Optional[str] = None) -> dict:
    if preset not in PRESETS:
        return {"status": "rejected", "reason": f"preset must be one of {', '.join(PRESETS)}"}
    s, err = await _settings()
    if err:
        return err
    info = next((p for p in s["show"].get("presets") or [] if p.get("name") == preset), {})
    prog = program_words({**s["program"], "mode": "auto", "every": 1, "run": 1,
                          **(info.get("program") or {})})
    approval = "new phones will need his approval" if info.get("approve_new_phones") else \
        "new phones join without approval"
    question = (f"Apply the {preset.capitalize()} preset ({info.get('guests', '?')} guests)? The "
                f"program becomes {prog}, and {approval}. The credits prices stay as they are; "
                "hand-placed slots are kept for Manual.")
    refusal = _gate("apply_jukebox_preset", {"preset": preset}, s, confirm_id, question)
    if refusal:
        return refusal
    r, err = await _request("POST", "/api/jukebox/show/preset", body={"preset": preset})
    if err:
        return err
    return {"status": "applied", "summary": f"{preset.capitalize()} preset applied: "
                                            f"{program_words(r.get('config') or {})}."}


def _show_words(row: dict, link: bool = True) -> str:
    return ", ".join(x for x in (
        "credits" if row.get("play_mode") == "credits" else "free play",
        f"{row['preset']} preset" if row.get("preset") else "",
        ("guest link on" if row.get("guest_link") else "guest link off") if link else "") if x)


async def _op_list_jukebox_shows() -> dict:
    r, err = await _get("/api/jukebox/shows")
    if err:
        return err
    rows = r.get("shows") or []
    if r.get("error"):
        return {"status": "rejected", "reason": r["error"]}
    listing = [{"name": x["name"], "about": _show_words(x)} for x in rows]
    summary = (f"{len(rows)} saved show{'' if len(rows) == 1 else 's'}: "
               + "; ".join(f"{x['name']} ({x['about']})" for x in listing) if rows
               else "No shows are saved yet.")
    return {"status": "ok", "current": r.get("current"), "shows": listing,
            "summary": f"{summary} In force now: {r.get('current')}."}


async def _op_load_jukebox_show(name: str, confirm_id: Optional[str] = None) -> dict:
    r, err = await _get("/api/jukebox/shows")
    if err:
        return err
    if r.get("error"):
        return {"status": "rejected", "reason": r["error"]}
    rows = r.get("shows") or []
    row = next((x for x in rows if str(x.get("name", "")).casefold() == str(name).strip().casefold()),
               None)
    if row is None:
        close = difflib.get_close_matches(str(name), [x.get("name", "") for x in rows], n=3, cutoff=0.5)
        hint = f" — the closest: {', '.join(close)}" if close else ""
        return {"status": "rejected",
                "reason": f"there's no saved show called {name!r}{hint}; a show is loaded only "
                          "by its exact name"}
    question = (f"Load the saved show “{row['name']}” ({_show_words(row, link=False)})? Every Jukebox setting "
                "becomes that show's — the set playlist and slots, the guests' rules, the "
                "credits and the board. The guest link stays as it is: switching it is yours, "
                "on the page.")
    refusal = _gate("load_jukebox_show", {"name": row["name"]}, row, confirm_id, question)
    if refusal:
        return refusal
    _, err = await _request("POST", "/api/jukebox/shows/load",
                            body={"name": row["name"], "guest_link": False})
    if err:
        return err
    return {"status": "applied",
            "summary": f"Loaded the show “{row['name']}” ({_show_words(row, link=False)}); the guest link "
                       "was left as it was."}


async def _op_start_jukebox_night(from_song: int = 1, confirm_id: Optional[str] = None) -> dict:
    st, err = await _get("/api/jukebox/status", params={"count": 1})
    if err:
        return err
    if st.get("running"):
        return {"status": "rejected", "reason": "a Jukebox night is already running",
                "summary": _status_summary(st)}
    cfg, err = await _get("/api/jukebox/config")
    if err:
        return err
    if not (cfg.get("playlist") or "").strip():
        return {"status": "rejected",
                "reason": "no set playlist is linked — link one on the Jukebox page first"}
    if int(from_song) < 1:
        return {"status": "rejected", "reason": "from_song counts from 1 (the set's first song)"}
    where = "its first song" if int(from_song) == 1 else f"song {int(from_song)}"
    question = (f"Start a Jukebox night? It plays your set playlist on Spotify, in order, from "
                f"{where}, with {program_words(cfg)} filled from the jukebox line, until you stop "
                "it or the house goes to sleep. Absorb can't run while it does.")
    last = st.get("night") or {}
    refusal = _gate("start_jukebox_night", {"from_song": int(from_song)},
                    {"program": cfg, "last_night": last.get("id")}, confirm_id, question)
    if refusal:
        return refusal
    r, err = await _request("POST", "/api/jukebox/night/start", timeout=START_TIMEOUT_S,
                            body={"play": True, "start_index": int(from_song) - 1,
                                  "started_by": "sonic"})
    if err:
        return err
    if r.get("status") != "running":
        return {"status": "rejected", "reason": r.get("detail") or r.get("reason") or "refused",
                "refusal": r.get("reason")}
    n = r.get("night") or {}
    return {"status": "applied", "night": n,
            "summary": f"The Jukebox night started on {n.get('playlist_name') or 'the set'}."}


async def _op_stop_jukebox_night(pause: bool = False, confirm_id: Optional[str] = None) -> dict:
    st, err = await _get("/api/jukebox/status", params={"count": 1})
    if err:
        return err
    if not st.get("running"):
        return {"status": "rejected", "reason": "no Jukebox night is running"}
    n = st.get("night") or {}
    then = ("Spotify is paused" if pause else "the song playing plays on (Spotify carries on with "
            "the playlist by itself)")
    question = (f"Stop the Jukebox night on {n.get('playlist_name') or 'the set'}? No more jukebox "
                f"songs are sent; {then}. A jukebox song already sent to Spotify's queue will "
                "still play.")
    refusal = _gate("stop_jukebox_night", {"pause": bool(pause)}, {"night": n.get("id")},
                    confirm_id, question)
    if refusal:
        return refusal
    r, err = await _request("POST", "/api/jukebox/night/stop", body={"pause": bool(pause)})
    if err:
        return err
    if r.get("status") != "ended":
        return {"status": "rejected", "reason": r.get("detail") or r.get("reason") or "not stopped"}
    return {"status": "applied", "summary": f"The Jukebox night stopped: {r.get('detail')}"}


GIFT_MAX = 20            # the most one gift gives a phone (SpotFX guests.GIFT_MAX)
_EVERYONE = {"everyone", "everybody", "all", "the whole party", "the party"}


async def _op_give_jukebox_credits(to: str, amount: int = 2,
                                   confirm_id: Optional[str] = None) -> dict:
    """The host's gift (report §4: "Everyone +2", "Give…"): credits to every
    phone at tonight's party, or to one guest named EXACTLY (a near miss is
    refused naming the close ones — a misheard name must not gift the wrong
    guest). Asks first, naming who and how much."""
    g, err = await _get("/api/jukebox/guests")
    if err:
        return err
    if not g.get("running"):
        return {"status": "rejected", "reason": "no Jukebox night is running"}
    if g.get("play_mode") != "credits":
        return {"status": "rejected", "reason": "credits are off tonight — the guest page is on "
                                                "free play, where gifts mean nothing"}
    try:
        n = int(amount)
    except (TypeError, ValueError):
        return {"status": "rejected", "reason": f"a gift is 1 to {GIFT_MAX} credits"}
    if not 1 <= n <= GIFT_MAX:
        return {"status": "rejected", "reason": f"a gift is 1 to {GIFT_MAX} credits"}
    party = [p for p in g.get("phones") or []
             if p.get("joined") and p.get("approved") and not p.get("blocked")]
    word = str(to or "").strip()
    if word.casefold() in _EVERYONE:
        if not party:
            return {"status": "rejected", "reason": "nobody has joined tonight yet"}
        target, who = "everyone", (f"everyone at the party ({len(party)} "
                                   f"phone{'' if len(party) == 1 else 's'})")
        state = sorted(p["id"] for p in party)
    else:
        match = [p for p in party if p.get("name", "").casefold() == word.casefold()]
        if len(match) != 1:
            close = difflib.get_close_matches(word, [p.get("name", "") for p in party], n=3,
                                              cutoff=0.5)
            hint = f" — the closest: {', '.join(close)}" if close else ""
            return {"status": "rejected",
                    "reason": f"no guest at tonight's party is named {word!r}{hint}; say the "
                              "name exactly as the Guests tab shows it, or 'everyone'"}
        target, who, state = match[0]["id"], match[0]["name"], [match[0]["id"]]
    question = (f"Give {who} {n} credit{'' if n == 1 else 's'}? Credits are free, only for "
                "tonight, and a gift asks nothing in return.")
    refusal = _gate("give_jukebox_credits", {"to": target, "amount": n}, state, confirm_id,
                    question)
    if refusal:
        return refusal
    r, err = await _request("POST", "/api/jukebox/gift", body={"to": target, "amount": n})
    if err:
        return err
    gift = r.get("gift") or {}
    return {"status": "applied",
            "summary": f"Gave {n} credit{'' if n == 1 else 's'} to {who}.",
            "phones": gift.get("phones")}


# ── declarations ─────────────────────────────────────────────────────────────

_INSTR_COMMON = (
    "The Jukebox plays his set playlist as Spotify's own context and puts jukebox slots between "
    "set songs, filled just in time from the jukebox line. Credits are free party credits with "
    "no money anywhere. ")

_INSTR_CONFIRM = (
    "EVERY change asks first. When the result's status is needs_confirmation NOTHING has "
    "happened yet: read him its `question` in plain words and wait. Only after he says yes, "
    "call this again with the same arguments plus that confirm_id. Never call with a "
    "confirm_id he has not said yes to, and never start or stop a night he did not ask for. ")

_CONFIRM_PROP = {"type": "string",
                 "description": "The confirm_id a needs_confirmation result returned — only "
                                "after he said yes to its question."}

OPERATIONS: dict[str, SonicOperation] = {
    "jukebox_status": SonicOperation(
        name="jukebox_status", domain="jukebox", kind="read",
        summary="Is a Jukebox night running, what is playing, what is in the line, and any "
                "warning (the Spotify sign-in's age among them).",
        instructions=(
            _INSTR_COMMON
            + "Use for 'is the jukebox on?', 'what's playing?', 'how long is the line?'. "
            "`summary` is the sentence to say; `warnings` must be read to him when present."),
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=_op_jukebox_status),
    "get_jukebox_settings": SonicOperation(
        name="get_jukebox_settings", domain="jukebox", kind="read",
        summary="The Jukebox's settings: the program (where the slots go), the preset, phone "
                "approval and every credits setting with its range.",
        instructions=(
            _INSTR_COMMON
            + "Call before set_jukebox_setting to learn the key names: the program keys (mode, "
            "every, run, run_out, commit_lead_s, next_jumps_set), approve_new_phones, and every "
            "economy key in "
            "`economy_fields` (each with its label, unit and range)."),
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=_op_get_jukebox_settings),
    "jukebox_price_check": SonicOperation(
        name="jukebox_price_check", domain="jukebox", kind="read",
        summary="What adding, skipping, play next, bumps and jail cost under the current "
                "settings, for a room of a given size.",
        instructions=(
            _INSTR_COMMON
            + "Use for 'how much is a skip with 20 people?'. Skip and jail follow the room size; "
            "the add price follows the wait."),
        input_schema={"type": "object",
                      "properties": {"guests": {"type": "integer", "minimum": 1, "maximum": 100,
                                                "default": 15}},
                      "additionalProperties": False},
        handler=_op_jukebox_price_check),
    "simulate_jukebox_party": SonicOperation(
        name="simulate_jukebox_party", domain="jukebox", kind="read",
        summary="Play model party nights under his saved credits settings and report how they "
                "went beside the tuned settings — the party simulator.",
        instructions=(
            _INSTR_COMMON
            + "A model night: the plan's model of guests and songs with the REAL price rules "
            "under his saved settings; it writes nothing and reaches neither Spotify nor the "
            "room. program='saved' plays his program; 'preset' plays the plan's preset for the "
            "party size. `summary` says which of the plan's promises held; `rows` are the "
            "numbers (yours beside tuned). To WATCH a night, the Jukebox page's Simulate tab "
            "plays one back."),
        input_schema={"type": "object",
                      "properties": {
                          "guests": {"type": "integer", "minimum": 2, "maximum": 40, "default": 20},
                          "program": {"type": "string", "enum": list(SIM_PROGRAMS), "default": "saved"},
                          "nights": {"type": "integer", "minimum": 1, "maximum": 40, "default": 20},
                          "seed": {"type": "integer", "minimum": 1, "maximum": 1000000, "default": 1}},
                      "additionalProperties": False},
        handler=_op_simulate_jukebox_party),
    "jukebox_night_report": SonicOperation(
        name="jukebox_night_report", domain="jukebox", kind="read",
        summary="How the latest Jukebox night went: what played, the line, the credits, and "
                "each measure beside the model's nights at the party size.",
        instructions=(
            _INSTR_COMMON
            + "Use for 'how did last night go?'. `summary` is the sentence to say. Without "
            "guests the party size comes from the night's ledger (the guests who used credits); "
            "pass guests to compare at another size. A row whose this_night is null was not "
            "measured — say why (its `why`), never call it zero. `ledger_problems` must be read "
            "to him when present."),
        input_schema={"type": "object",
                      "properties": {"guests": {"type": "integer", "minimum": 2, "maximum": 40}},
                      "additionalProperties": False},
        handler=_op_jukebox_night_report),
    "set_jukebox_setting": SonicOperation(
        name="set_jukebox_setting", domain="jukebox", kind="write",
        summary="Change one Jukebox setting — a program setting, phone approval, a guest rule "
                "(last call, explicit songs, phones, renames), a free-play rule (the room's "
                "skip, bumps, the jail) or one credits setting (asks him first).",
        instructions=(
            _INSTR_COMMON + _INSTR_CONFIRM
            + "Keys: mode (auto | jukebox_first — never manual, which is placed on the page), "
            "every (1-5), run (1-3), run_out (again | jukebox_only | end), commit_lead_s "
            "(15-90), next_jumps_set (true/false: a song played next plays straight after the "
            "song playing, ahead of the next set song), approve_new_phones (true/false), play_mode (credits | free — the guest "
            "page's mode: credits turns on prices, the Shop and the credits chip), the guest "
            "rules — night_ends and "
            "explicit_after (\"HH:MM\", house time), last_call_min (0-60), explicit (no | extra "
            "| after), max_phones (5-100), renames_per_night (0-10), word_filter (true/false) — "
            "the free-play rules — free_skip_downs (2-10 ▼ to skip a song), free_skip_share "
            "(50-90, the percent of the votes that must be ▼), free_bumps_per_hour (0-10), "
            "free_play_next (host | off), free_jail_songs (0-15 songs a jailed guest's songs "
            "sit out; 0 = no jail) — the board — board_on (the guests' Board tab, \"Tonight's "
            "top songs\"), board_top_pickers / board_top_voters / board_most_generous (the "
            "people boards, off by default: ranking people is the plan's §2.2 flag, so say so "
            "when he turns one on), board_on_tv (the full-screen board page for his TV) — "
            "or any economy key from get_jukebox_settings. SpotFX validates first; an "
            "out-of-range value is refused with its reason before he is asked."),
        input_schema={"type": "object",
                      "properties": {"key": {"type": "string"},
                                     "value": {"type": ["number", "integer", "boolean", "string"]},
                                     "confirm_id": _CONFIRM_PROP},
                      "required": ["key", "value"], "additionalProperties": False},
        handler=_op_set_jukebox_setting),
    "apply_jukebox_preset": SonicOperation(
        name="apply_jukebox_preset", domain="jukebox", kind="write",
        summary="Apply a party-size preset — small, medium or large — which sets the program "
                "(asks him first).",
        instructions=(
            _INSTR_COMMON + _INSTR_CONFIRM
            + "Small (4-8 guests): every other song. Medium (9-16): two jukebox songs per set "
            "song. Large (17-30): jukebox first, and new phones need his approval. The prices "
            "do not change."),
        input_schema={"type": "object",
                      "properties": {"preset": {"type": "string", "enum": list(PRESETS)},
                                     "confirm_id": _CONFIRM_PROP},
                      "required": ["preset"], "additionalProperties": False},
        handler=_op_apply_jukebox_preset),
    "list_jukebox_shows": SonicOperation(
        name="list_jukebox_shows", domain="jukebox", kind="read",
        summary="List his saved Jukebox shows (each a whole set of Jukebox settings, saved "
                "under a name) and which one is in force.",
        instructions=_INSTR_COMMON + "Reads only.",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=_op_list_jukebox_shows),
    "load_jukebox_show": SonicOperation(
        name="load_jukebox_show", domain="jukebox", kind="write",
        summary="Load one of his saved shows by its exact name — every Jukebox setting becomes "
                "that show's (asks him first).",
        instructions=(
            _INSTR_COMMON + _INSTR_CONFIRM
            + "Call list_jukebox_shows first; a name that isn't exactly a saved show's (case "
            "aside) is refused, naming the closest. During a night, a show with a different set "
            "playlist is refused until the night ends, and nothing changes."),
        input_schema={"type": "object",
                      "properties": {"name": {"type": "string"}, "confirm_id": _CONFIRM_PROP},
                      "required": ["name"], "additionalProperties": False},
        handler=_op_load_jukebox_show),
    "start_jukebox_night": SonicOperation(
        name="start_jukebox_night", domain="jukebox", kind="write",
        summary="Start a Jukebox night on the linked set playlist (always asks him first).",
        instructions=(
            _INSTR_COMMON + _INSTR_CONFIRM
            + "Only when he asks to start the jukebox. It is the page's own Start: it plays the "
            "set on Spotify, so every refusal it has (no playlist, the house asleep, Absorb "
            "running, Spotify failing) comes back as `reason` — say it. from_song counts from "
            "1."),
        input_schema={"type": "object",
                      "properties": {"from_song": {"type": "integer", "minimum": 1, "default": 1},
                                     "confirm_id": _CONFIRM_PROP},
                      "additionalProperties": False},
        handler=_op_start_jukebox_night),
    "stop_jukebox_night": SonicOperation(
        name="stop_jukebox_night", domain="jukebox", kind="write",
        summary="Stop the running Jukebox night (always asks him first).",
        instructions=(
            _INSTR_COMMON + _INSTR_CONFIRM
            + "pause=true also pauses Spotify; otherwise the music plays on without the "
            "jukebox. A yes covers only the night he was asked about."),
        input_schema={"type": "object",
                      "properties": {"pause": {"type": "boolean", "default": False},
                                     "confirm_id": _CONFIRM_PROP},
                      "additionalProperties": False},
        handler=_op_stop_jukebox_night),
    "give_jukebox_credits": SonicOperation(
        name="give_jukebox_credits", domain="jukebox", kind="write",
        summary="Give credits to everyone at tonight's party, or to one guest by name — the "
                "host's gift (credits mode); always asks first.",
        instructions=(
            _INSTR_COMMON + _INSTR_CONFIRM
            + "`to` is 'everyone' or a guest's name EXACTLY as the Guests tab shows it (a near "
            "miss is refused with the closest names — never guess which guest he meant). "
            f"`amount` is 1-{GIFT_MAX} (2 is the plan's \"Everyone +2\"). Only in credits mode "
            "and while a night runs. A gift is a gift: never offer credits in exchange for "
            "anything."),
        input_schema={"type": "object",
                      "properties": {"to": {"type": "string"},
                                     "amount": {"type": "integer", "minimum": 1,
                                                "maximum": GIFT_MAX},
                                     "confirm_id": _CONFIRM_PROP},
                      "required": ["to"], "additionalProperties": False},
        handler=_op_give_jukebox_credits),
}
