"""THE CONTAMINATION WITNESS — a read-only client for River's deployed
house-state witness, used to ask "did anything else in the house change
light while we were photographing?"

THE MEASUREMENT THIS PROTECTS. A footprint is `lit - dark` in one camera's
own byte scale. Everything in this instrument that refuses — the exposure
lock, the firmware-brightness guard, the pose token — exists because a
difference measured across a changed condition is not a footprint, it is a
number that looks like one. A HOUSE LIGHT COMING ON MID-CAPTURE IS EXACTLY
THAT CONDITION, and until now nothing on this side could see it: SPECTRA
knows what SPECTRA wrote and nothing about the rest of the room.

River's witness service records every state AND attribute-level change for
the house's light scope. This module asks it, per capture window, what
changed. Nothing here writes to Home Assistant, ever — see THE SCONCE MAINS
RULE below, which is the same rule stated as a hard prohibition.

────────────────────────────────────────────────────────────────────────────
THE CONTRACT (River's, deployed and proven — SPECTRA CONFORMS, it does not
renegotiate it, the same posture `spectra/services/transcription.py` takes
with the local Whisper bridge)
────────────────────────────────────────────────────────────────────────────

    GET  {SPECTRA_WITNESS_URL}/witness/changes?start=<iso8601>&end=<iso8601>
    GET  {SPECTRA_WITNESS_URL}/witness/scope
    Authorization: Bearer {SPECTRA_WITNESS_TOKEN}

`changes` returns every change row in the window; `scope` is the LIVE entity
scope. The window is capped at `MAX_WINDOW_S` (7200s) per query, which this
module enforces before the request goes out rather than leaving the other
side's rejection to surface as a confusing generic error —
`transcription.BRIDGE_MAX_AUDIO_BYTES`' own discipline.

THE SCOPE IS NEVER CACHED ACROSS RUNS, by River's instruction and for a
reason this codebase already owns: a cached scope is a stale belief about
what is being watched, and a subtraction performed against a stale scope
silently stops indicting whatever was added to the house since. It is read
once per run.

BOTH SECRETS COME FROM THE ENVIRONMENT ONLY, read at call time. The
deploy-time secret lives outside this repository entirely and is never read
into code, into a log line, or into a run record. Nothing in this module
logs a token, and the tests use fakes.

────────────────────────────────────────────────────────────────────────────
THE VERDICT, AND WHY THERE ARE THREE OF THEM
────────────────────────────────────────────────────────────────────────────

    clean                  the witness answered and nothing outside our own
                           fixtures changed inside this capture's window
    contaminated(rows)     something did — the capture is DISCARDED and
                           RE-TAKEN, and the rows say what
    witness_unavailable    the witness could not be asked

THE THIRD ONE MARKS, IT NEVER DISCARDS AND NEVER KILLS A RUN. River's
instruction, and it is the right way round: a witness outage is a fact about
the witness, not about the room. The capture is KEPT, stamped
`witness_unavailable`, and NO CLEAN CLAIM IS MADE for it — and it is named
in the exit report, so "we could not check" never reads as "we checked and
it was fine". That is the same distinction `night_exit` draws between DARK
and UNKNOWN, and the same one `fixture_brightness` draws between `read` and
`unreadable`. There are three states here for the same reason there are
three there.

OUR OWN FIXTURES ARE SUBTRACTED FIRST. A run that lit a strip and then
indicted itself for the strip having changed would refuse every capture it
ever took. The subtraction is against the run's OWN exported fixture
entities (`night_run.fixtures_export`'s first list), which is the same list
River's morning backstop is built against — one definition, not two.

────────────────────────────────────────────────────────────────────────────
TIMING — NO ADDED SETTLE, EVER
────────────────────────────────────────────────────────────────────────────

River's instruction, and it is load-bearing: THE DARK TIME STAYS FLAT. This
module adds no wait to any capture. The per-window query fires IMMEDIATELY
after a capture window closes (an HTTP round trip that overlaps the next
capture's own settle rather than extending anything), and a SETTLED
whole-run sweep at the end re-asks for the run's entire span, so a row that
arrived late still indicts the capture it overlaps and that capture is
re-taken then. Two queries, neither of which the room waits on.

────────────────────────────────────────────────────────────────────────────
THE SCONCE MAINS RULE (Admiral-binding, both fleets)
────────────────────────────────────────────────────────────────────────────

`light.dimmer_kitchen_sconce` is the kitchen sconces' MAINS SUPPLY. NO RUN
PATH MAY EVER TURN IT OFF OR LOWER IT — not the lights-on-if-necessary step,
not any restore, not anything. This side does not drive Home Assistant
entities AT ALL, from any module, and that is how it stays: the only HA
traffic this codebase originates is the two READ requests above.

IT IS BINARY — 0% or 100%, a switch, with no scale factor (the Admiral's own
correction, superseding an earlier level-recording idea). So nothing here
records its level per measurement and nothing is designed against it
scaling; it is an ordinary scope entity, and an accidental write to it
indicts overlapped captures exactly like any other row.

WHAT 0% MEANS IS THE POINT: mains off, BOTH sconces dead, and
indistinguishable from a dead controller or a lost network from anywhere
inside this app. `SCONCE_MAINS_FIRST_CHECK` is the named first line of the
diagnostic for exactly that, by his own order — it eats an hour unchecked.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

#: River's own bound on one query. Enforced HERE, before the request goes
#: out, rather than leaving her rejection to surface as a generic error.
MAX_WINDOW_S = 7200.0

VERDICT_CLEAN = "clean"
VERDICT_CONTAMINATED = "contaminated"
VERDICT_UNAVAILABLE = "witness_unavailable"

#: The HA entity that is the kitchen sconces' MAINS SUPPLY. Named here so
#: there is ONE place in this codebase that knows the string, and so a grep
#: for it lands on the rule rather than on a call site.
SCONCE_MAINS_ENTITY = "light.dimmer_kitchen_sconce"

#: THE NAMED FIRST CHECK, his own order. When a sconce will not answer —
#: an activation gap, a capture refusal, a dead device probe — this is the
#: FIRST line of the diagnostic, before anything about controllers or
#: networks, because mains-off looks exactly like both of those and costs an
#: hour when it is not checked first.
SCONCE_MAINS_FIRST_CHECK = (
    f"FIRST: check {SCONCE_MAINS_ENTITY} for 0% — it is the kitchen sconces' "
    f"MAINS SUPPLY and it is a switch, not a dimmer (0% or 100%). At 0% both "
    f"sconces are dead and it looks exactly like a dead controller or a lost "
    f"network. Nothing in SPECTRA can turn it on, and nothing in SPECTRA "
    f"ever turns it off — check it in Home Assistant.")


def sconce_diagnostic(problem: str, *, sconce_involved: bool = True) -> str:
    """A sconce problem, with the mains check FIRST. Never appended after
    the technical detail: the whole value of the rule is the ORDER, and a
    line buried under three paragraphs about controllers is the hour this
    exists to save."""
    if not sconce_involved:
        return problem
    return f"{SCONCE_MAINS_FIRST_CHECK}\n\n{problem}"


#: How a sconce is recognised in a fixture, carrier or emitter name. A
#: HEURISTIC, biased on purpose: prefixing the mains check onto something
#: that is not a sconce costs one extra line of a diagnostic; omitting it
#: from one that is costs the hour this rule exists to save.
SCONCE_TOKENS = ("sconce",)


def mentions_sconce(*texts: str) -> bool:
    joined = " ".join(str(t or "") for t in texts).lower()
    return any(token in joined for token in SCONCE_TOKENS)


def witness_url() -> str:
    """Base URL of River's witness service. Read at call time so rotating
    or repointing it is an environment edit and a restart, never a stale
    module global — `config.night_run_token()`'s own posture."""
    return os.getenv("SPECTRA_WITNESS_URL", "").rstrip("/")


def witness_token() -> str:
    """The bearer, from the environment ONLY. Never logged, never recorded,
    never read from a file by this code."""
    return os.getenv("SPECTRA_WITNESS_TOKEN", "")


def configured() -> bool:
    return bool(witness_url() and witness_token())


def iso(ts: float) -> str:
    """A UTC ISO-8601 instant, which is what the wire takes."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


class WitnessUnavailable(Exception):
    """The witness could not be asked, or did not answer usefully. NEVER
    fatal to a run — the caller marks and carries on. Its message is the
    sentence recorded against the capture."""


@dataclass
class ChangeRow:
    """One state or attribute-level change the witness saw. Kept as the
    fields this side actually reasons about plus the row VERBATIM, so a
    record can be argued from later without this module having had to
    predict which field would matter."""
    entity_id: str
    at: str = ""
    at_ts: float = 0.0
    what: str = ""
    raw: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"entity_id": self.entity_id, "at": self.at,
                "at_ts": self.at_ts, "what": self.what, "raw": dict(self.raw)}


def _parse_ts(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except ValueError:
        return 0.0


def parse_rows(payload: Any) -> list[ChangeRow]:
    """The wire's rows -> `ChangeRow`s, tolerantly. A row shape this side
    does not recognise is still KEPT (with whatever entity id it carries),
    because the safe direction for a contamination check is to notice a
    change it cannot fully describe, never to drop it."""
    rows = payload.get("changes") if isinstance(payload, dict) else payload
    out: list[ChangeRow] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        at = str(row.get("at") or row.get("last_changed")
                 or row.get("last_updated") or row.get("time_fired") or "")
        out.append(ChangeRow(
            entity_id=str(row.get("entity_id") or row.get("entity") or ""),
            at=at, at_ts=_parse_ts(at),
            what=str(row.get("what") or row.get("attribute")
                     or row.get("change") or ""),
            raw=dict(row)))
    return out


async def fetch_changes(start_ts: float, end_ts: float, *,
                        client: Optional[Any] = None) -> list[ChangeRow]:
    """Every change row in [start, end]. Raises `WitnessUnavailable` for
    every expected failure — unconfigured, unreachable, refused, malformed —
    so a caller has exactly one thing to catch and one thing to record.

    The window cap is checked BEFORE the request: a caller asking for more
    than River accepts gets a sentence rather than her error."""
    if end_ts < start_ts:
        start_ts, end_ts = end_ts, start_ts
    if (end_ts - start_ts) > MAX_WINDOW_S:
        raise WitnessUnavailable(
            f"the witness accepts a window of at most "
            f"{MAX_WINDOW_S / 3600:.0f} hours and this one is "
            f"{(end_ts - start_ts) / 3600:.1f} — ask for it in pieces")
    base, token = witness_url(), witness_token()
    if not base or not token:
        raise WitnessUnavailable(
            "the contamination witness is not configured on this host "
            "(SPECTRA_WITNESS_URL / SPECTRA_WITNESS_TOKEN), so nothing can "
            "say whether the house changed light during this capture")
    return parse_rows(await _get(
        base, "/witness/changes", token,
        params={"start": iso(start_ts), "end": iso(end_ts)}, client=client))


async def fetch_scope(*, client: Optional[Any] = None) -> list[str]:
    """The LIVE entity scope. READ ONCE PER RUN AND NEVER CACHED ACROSS
    RUNS — River's instruction: a stale scope silently stops indicting
    whatever the house gained since it was read."""
    base, token = witness_url(), witness_token()
    if not base or not token:
        raise WitnessUnavailable(
            "the contamination witness is not configured on this host "
            "(SPECTRA_WITNESS_URL / SPECTRA_WITNESS_TOKEN)")
    payload = await _get(base, "/witness/scope", token, client=client)
    entities = (payload.get("entities") or payload.get("scope")
                if isinstance(payload, dict) else payload)
    return sorted({str(e) for e in (entities or []) if e})


async def _get(base: str, path: str, token: str, *,
               params: Optional[dict] = None,
               client: Optional[Any] = None) -> Any:
    """One authenticated GET. Never logs the token, and never lets an
    httpx/transport exception escape as itself — a caller of this module
    catches `WitnessUnavailable` and nothing else."""
    import httpx

    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=httpx.Timeout(connect=3.0, read=6.0,
                                                         write=4.0, pool=1.0))
    try:
        resp = await client.get(f"{base}{path}", params=params,
                                headers={"Authorization": f"Bearer {token}"})
        if resp.status_code >= 400:
            raise WitnessUnavailable(
                f"the witness answered {resp.status_code} for {path} — the "
                f"house's own record of what changed could not be read")
        return resp.json()
    except WitnessUnavailable:
        raise
    except Exception as exc:                            # noqa: BLE001
        # Deliberately does not interpolate the URL's credentials or the
        # token; only the class and the path.
        raise WitnessUnavailable(
            f"the witness could not be reached ({type(exc).__name__}) — "
            f"nothing can say whether the house changed light during this "
            f"capture") from exc
    finally:
        if own:
            await client.aclose()


# ── the verdict ────────────────────────────────────────────────────────────

@dataclass
class Verdict:
    """One capture window's answer. `status` is the word a program branches
    on; `detail` is the sentence a person reads."""
    status: str
    detail: str = ""
    rows: list[dict] = field(default_factory=list)
    window: tuple[float, float] = (0.0, 0.0)

    @property
    def clean(self) -> bool:
        return self.status == VERDICT_CLEAN

    @property
    def contaminated(self) -> bool:
        return self.status == VERDICT_CONTAMINATED

    def as_dict(self) -> dict:
        return {"status": self.status, "detail": self.detail,
                "rows": list(self.rows),
                "window": [self.window[0], self.window[1]]}


def slug(text: str) -> str:
    """A Home Assistant object-id-shaped token: lowercase, non-alphanumerics
    collapsed to underscores. Used only to recognise OUR OWN fixtures in the
    witness's rows."""
    out, last = [], False
    for ch in str(text or "").lower():
        if ch.isalnum():
            out.append(ch)
            last = False
        elif not last:
            out.append("_")
            last = True
    return "".join(out).strip("_")


def own_entities(fixtures: Iterable[dict]) -> set[str]:
    """The tokens by which one of OUR fixtures is recognised in a witness
    row — from the run's own exported fixture list, which is the same list
    River's morning backstop is built against.

    THE MAPPING BETWEEN THE TWO WORLDS IS HERS, NOT OURS. She turns our
    exported fixtures into HA entities; this side can only recognise them by
    id and name. So the match is on the entity's OBJECT id (the part after
    the domain) against the slugified device id and device name.

    IT IS BIASED TO OVER-INDICT, deliberately and in the only safe
    direction: a fixture of ours we fail to recognise gets its capture
    re-taken for no reason (a cost), where a house light we mistake for ours
    silently corrupts a footprint (a lie). If a real run shows this
    over-indicting, the fix is to agree explicit entity ids with River — not
    to loosen the match."""
    tokens: set[str] = set()
    for fixture in fixtures or []:
        for key in ("id", "name"):
            value = slug((fixture or {}).get(key) or "")
            if value:
                tokens.add(value)
    return tokens


def is_ours(entity_id: str, tokens: Iterable[str]) -> bool:
    """Whether this row's entity is one of ours. Matches the object id
    exactly against a token — never a substring, which would make
    `light.kitchen` swallow `light.kitchen_ceiling_next_door`."""
    text = str(entity_id or "")
    obj = slug(text.split(".", 1)[1] if "." in text else text)
    return bool(obj) and obj in set(tokens or [])


def foreign_rows(rows: Iterable[ChangeRow], ours: Iterable[str],
                 start_ts: float, end_ts: float) -> list[ChangeRow]:
    """The rows that indict a window: inside it, and NOT one of our own
    fixtures.

    A row with no usable timestamp is KEPT rather than dropped — the safe
    direction is to notice a change we cannot place, never to discard it.
    The subtraction is by entity id against the run's own exported fixture
    entities, which is the SAME list River's morning backstop is built
    against; two definitions of "ours" would be two different rooms."""
    mine = {str(e) for e in ours or []}
    out: list[ChangeRow] = []
    for row in rows or []:
        if row.entity_id and (row.entity_id in mine
                              or is_ours(row.entity_id, mine)):
            continue
        if row.at_ts and not (start_ts <= row.at_ts <= end_ts):
            continue
        out.append(row)
    return out


def judge(rows: Iterable[ChangeRow], ours: Iterable[str],
          start_ts: float, end_ts: float) -> Verdict:
    """A window's verdict from rows already fetched. Pure, so the rule is
    testable without a witness and cannot differ between the immediate
    per-window query and the settled whole-run sweep — one function, both
    callers."""
    foreign = foreign_rows(rows, ours, start_ts, end_ts)
    if not foreign:
        return Verdict(VERDICT_CLEAN,
                       "the house's own record shows nothing outside this "
                       "run's fixtures changed while this was being "
                       "photographed", window=(start_ts, end_ts))
    named = ", ".join(sorted({r.entity_id or "(unnamed entity)"
                              for r in foreign})[:6])
    return Verdict(
        VERDICT_CONTAMINATED,
        f"{len(foreign)} change{'' if len(foreign) == 1 else 's'} in the "
        f"house happened while this was being photographed ({named}) — the "
        f"capture measures those as well as the fixture, so it is discarded "
        f"and taken again.",
        rows=[r.as_dict() for r in foreign], window=(start_ts, end_ts))


def unavailable(exc: BaseException, start_ts: float = 0.0,
                end_ts: float = 0.0) -> Verdict:
    """MARKS, never discards. The capture is kept and no clean claim is made
    for it."""
    return Verdict(VERDICT_UNAVAILABLE,
                   f"{exc} — this capture is KEPT and stamped, but nothing "
                   f"claims it was clean.", window=(start_ts, end_ts))


async def check_window(start_ts: float, end_ts: float, ours: Iterable[str], *,
                       client: Optional[Any] = None) -> Verdict:
    """Ask, then judge. The one call a capture makes, and it never raises:
    an unreachable witness comes back as a marked verdict, because a witness
    outage must not be able to end his night."""
    try:
        rows = await fetch_changes(start_ts, end_ts, client=client)
    except WitnessUnavailable as exc:
        logger.info("witness: unavailable for %s..%s: %s",
                    iso(start_ts), iso(end_ts), exc)
        return unavailable(exc, start_ts, end_ts)
    return judge(rows, ours, start_ts, end_ts)
