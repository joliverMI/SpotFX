"""ONE fuzzy name resolver, shared by any Sonic operation that must turn a
spoken name into an id WITHOUT inventing a second convention per domain
(show_console._resolve_set/_resolve_arm, house_console._resolve_mode/
_by_name all already do exact-id-or-case-insensitive-name, refusing with
difflib close matches on a miss — that discipline stays the floor here).

The ADDITION this module makes (the Admiral's own ruling on Force Scene/
Force Colour by name, 2026-10-06: "allow some flexibility in phrasing. I
know we have scenes named with 'V2' at the end, and I don't want to have
to say that, but it should be a close match") is ONE extra tier between
"exact" and "ask": a known trailing qualifier (" V2", " V1", " UI") is
stripped from BOTH the spoken name and every candidate before comparing,
so "Orbits" reaches "Orbits V2" when it is the only candidate that
reduces to "orbits". Past that tier, a fuzzy ratio over the same
stripped names picks a single candidate ONLY when its score clears
`cutoff` AND beats the next-best by `min_gap` — a near-tie between two
plausible candidates is refused exactly like a miss, never guessed
between them. Every refusal names the close candidates (or every known
name, when nothing was close) so Sonic can ask rather than invent one."""
from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Optional

#: Trailing qualifiers his own naming convention adds that a spoken
#: request will routinely drop — lowercase, checked repeatedly so a name
#: carrying more than one (unlikely, but cheap to allow) still reduces.
_SUFFIXES = (" v2", " v1", " v3", " ui")

DEFAULT_CUTOFF = 0.45
DEFAULT_MIN_GAP = 0.08


def _strip_suffixes(name: str) -> str:
    s = (name or "").strip().lower()
    changed = True
    while changed:
        changed = False
        for suf in _SUFFIXES:
            if s.endswith(suf):
                s = s[: -len(suf)].rstrip()
                changed = True
    return s


def _score(a: str, b: str) -> float:
    return difflib.SequenceMatcher(a=a, b=b).ratio()


@dataclass(frozen=True)
class NameMatch:
    id: str
    name: str


def resolve_name(query: str, candidates: list[tuple[str, str]], *, noun: str,
                 cutoff: float = DEFAULT_CUTOFF, min_gap: float = DEFAULT_MIN_GAP
                 ) -> tuple[Optional[NameMatch], Optional[dict]]:
    """(match, None) on a single clear answer; (None, rejection) naming the
    close candidates on a near-tie, an empty candidate list, or nothing
    close enough. `candidates` is [(id, name), ...]; `noun` names what's
    being matched for the rejection's own wording ('scene', 'colour set or
    group'). Never raises — every outcome is a plain return."""
    q = (query or "").strip()
    if not q:
        return None, {"status": "rejected", "reason": f"name a {noun} to use"}
    by_id = {cid: name for cid, name in candidates}
    if q in by_id:
        return NameMatch(id=q, name=by_id[q]), None

    q_low = q.lower()
    exact = [(cid, name) for cid, name in candidates if name.strip().lower() == q_low]
    if len(exact) == 1:
        return NameMatch(id=exact[0][0], name=exact[0][1]), None
    if len(exact) > 1:
        return None, {"status": "rejected",
                      "reason": f"more than one {noun} is named {query!r}",
                      "candidates": [name for _, name in exact]}

    q_norm = _strip_suffixes(q)
    norm_matches = [(cid, name) for cid, name in candidates
                    if _strip_suffixes(name) == q_norm]
    if len(norm_matches) == 1:
        return NameMatch(id=norm_matches[0][0], name=norm_matches[0][1]), None
    if len(norm_matches) > 1:
        return None, {"status": "rejected",
                      "reason": f"{query!r} could mean more than one {noun}",
                      "candidates": sorted(name for _, name in norm_matches)}

    if not candidates:
        return None, {"status": "rejected", "reason": f"no {noun}s exist yet"}

    scored = sorted(
        ((cid, name, _score(q_norm, _strip_suffixes(name))) for cid, name in candidates),
        key=lambda t: t[2], reverse=True)
    best_id, best_name, best_score = scored[0]
    second_score = scored[1][2] if len(scored) > 1 else 0.0
    if best_score >= cutoff and (best_score - second_score) >= min_gap:
        return NameMatch(id=best_id, name=best_name), None

    close = [name for _, name, s in scored if s >= cutoff][:5]
    return None, {
        "status": "rejected",
        "reason": f"no clear match for {query!r} among the {noun}s"
                  + (" — did you mean one of these?" if close else ""),
        "close_matches": close,
        "known_names": sorted(name for _, name in candidates),
    }
