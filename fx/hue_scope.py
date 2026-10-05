"""THE HUE SCOPE — the ONE way any SpotFX or SPECTRA code writes a Hue bulb
over the bridge's REST API, and the explicit per-bulb ALLOW-LIST it enforces
(SpotFX-authored, not fork code; `fx/VENDOR.md` deviation #50).

Found 2026-10-05 02:31 (a house-lighting proof take, his house asleep): two
SPECTRA paths lit bulbs that belong to Home Assistant — the release fade's
"dim to 1%" write and the room's Hue Hold, each of which wrote EVERY bulb in
the Hue entertainment area: the Loft Ceiling Uplight and the three Ledge
lights sit in the "Music Group" area but are his house's, not Spectra's. The
fix is not "skip those names" in each writer — that is one more list per
writer to keep in step. It is this module: every REST light write goes
through `put()`, which refuses

  * any endpoint that is not ONE light (`/clip/v2/resource/light/<id>`) —
    never `grouped_light`, a room, a zone, the v1 `/groups/0` "all lights"
    group, or anything else that fans out to bulbs nobody listed; and
  * any light whose resource id is not on the allow-list.

THE ALLOW-LIST is his data: `storage/spectra/hue_scope.json`,
`{"lights": {"<light resource id>": "<his name for it>"}}` — the living-room
and dining bulbs only. Resource ids are the bridge's own UUIDs (stable when a
bulb is renamed); the names are for people and refusal messages. A MISSING
OR UNREADABLE FILE ALLOWS NOTHING: every Hue REST write is refused and named,
never a guess. `scripts/seed_hue_scope.py` writes it from the bridges.

`allowed_pairs()` is for the RESOLVERS (each writer maps its entertainment
area to bulbs first): filter there so an out-of-scope bulb is never even
attempted or reported; `put()` is the backstop that holds whatever a writer
forgets. Reads (GET) are not this module's business.

Both processes use it (`fx/` may be imported by spot-effects and SPECTRA
alike; it imports neither): SPECTRA's ambient.py and release_fade.py, and
spot-effects' legacy services/ambient_mode.py.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
SCOPE_FILE = _REPO_ROOT / "storage" / "spectra" / "hue_scope.json"

_LIGHT_ENDPOINT = re.compile(r"^/clip/v2/resource/light/([A-Za-z0-9_-]+)/?$")

_lock = threading.Lock()
_warned_missing = False


class HueScopeRefused(PermissionError):
    """A Hue REST write outside the allow-list (or not to ONE light)."""


def read_allowed_file() -> dict[str, str]:
    """light resource id -> name. Missing/unreadable/malformed = {} (allow
    nothing), logged once loudly."""
    global _warned_missing
    try:
        data = json.loads(SCOPE_FILE.read_text(encoding="utf-8"))
        lights = data.get("lights") if isinstance(data, dict) else None
        if not isinstance(lights, dict):
            raise ValueError("no 'lights' object")
        return {str(k): str(v) for k, v in lights.items() if k}
    except Exception as exc:                             # noqa: BLE001
        with _lock:
            if not _warned_missing:
                logger.critical("Hue scope: %s unreadable (%s) — EVERY Hue REST "
                                "write is refused until it exists "
                                "(scripts/seed_hue_scope.py)", SCOPE_FILE, exc)
                _warned_missing = True
        return {}


#: The ONE reader every check below goes through (tests swap it).
load_allowed = read_allowed_file


def allowed(rid: str) -> bool:
    return str(rid) in load_allowed()


def allowed_pairs(pairs: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    """Keep only allow-listed (rid, name) pairs — what a resolver hands its
    writer. Order kept."""
    ok = load_allowed()
    return [(rid, name) for rid, name in pairs if str(rid) in ok]


def light_id(endpoint: str) -> str:
    """The light resource id of a write endpoint, or HueScopeRefused when the
    endpoint is not exactly ONE light."""
    m = _LIGHT_ENDPOINT.match(endpoint or "")
    if not m:
        raise HueScopeRefused(f"refused a Hue write to {endpoint!r}: only one "
                              "allow-listed light at a time, never a group, room, "
                              "zone or 'all lights'")
    return m.group(1)


def check(endpoint: str) -> str:
    """Raise HueScopeRefused unless `endpoint` is one allow-listed light;
    returns its id."""
    rid = light_id(endpoint)
    lights = load_allowed()
    if rid not in lights:
        raise HueScopeRefused(f"refused a Hue write to light {rid}: it is not "
                              f"on Spectra's allow-list ({SCOPE_FILE.name})")
    return rid


async def put(client, endpoint: str, body: dict):
    """THE Hue REST light write. `client` is an httpx.AsyncClient bound to
    the bridge. Returns the response (callers keep their own status
    handling); refuses before any byte leaves for an out-of-scope target."""
    check(endpoint)
    return await client.put(endpoint, json=body)
