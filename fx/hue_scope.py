"""THE HUE SCOPE — the ONE way any SpotFX or SPECTRA code writes a Hue bulb
over the bridge's REST API, and the explicit per-bulb ALLOW-LIST it enforces
(SpotFX-authored, not fork code; `fx/VENDOR.md` deviation #50).

Found 2026-10-05 02:31 (a house-lighting proof take, his house asleep): a
SPECTRA writer that resolves "the bulbs in this entertainment area" and
writes every one of them is only as scoped as that resolution — the release
fade's "dim to 1%" write and the room's Hue Hold each wrote EVERY bulb in
the Hue entertainment area it was handed, with no check that every one of
those bulbs was actually allow-listed yet. The fix is not "skip these names"
in each writer — that is one more list per writer to keep in step. It is
this module: every REST light write goes through `put()`, which refuses

  * any endpoint that is not ONE light (`/clip/v2/resource/light/<id>`) —
    never `grouped_light`, a room, a zone, the v1 `/groups/0` "all lights"
    group, or anything else that fans out to bulbs nobody listed; and
  * any light whose resource id is not on the allow-list.

THE ALLOW-LIST is his data: `storage/spectra/hue_scope.json`,
`{"lights": {"<light resource id>": "<his name for it>"}}` — every bulb in
his Spectra home's living-room and dining entertainment areas (17 bulbs,
including the Loft Ceiling Uplight and the three Ledge bulbs — an earlier
build wrongly carved those four out as "left to Home Assistant"; his own
correction, 2026-10-06: they are ordinary bulbs of his Spectra home like
every other one in the Music Group area, not treated differently).
Resource ids are the bridge's own UUIDs (stable when a bulb is renamed);
the names are for people and refusal messages. A MISSING OR UNREADABLE FILE
ALLOWS NOTHING: every Hue REST write is refused and named, never a guess.
`scripts/seed_hue_scope.py` writes it from the bridges.

`allowed_pairs()` is for the RESOLVERS (each writer maps its entertainment
area to bulbs first): filter there so an out-of-scope bulb is never even
attempted or reported; `put()` is the backstop that holds whatever a writer
forgets. Reads (GET) are not this module's business.

Both processes use it (`fx/` may be imported by spot-effects and SPECTRA
alike; it imports neither): SPECTRA's ambient.py and release_fade.py, and
spot-effects' legacy services/ambient_mode.py.

THE ENTERTAINMENT STREAM IS IN SCOPE TOO (2026-10-06). A REST write is not
the only way a bulb comes on: asking the bridge to START an entertainment
session (`devices/hue.py`, `action: start`) switches on EVERY bulb in that
entertainment area, whatever frames follow. This is the generic safety net
for that: `stream_refusal()` names an area that holds any bulb not on the
allow-list (or a channel whose bulb cannot be identified), and `HueDevice`
never starts a session on it. It stays in place for any future bulb that
is genuinely someone else's — it does not single out any bulb today, since
every bulb in both of his streamed entertainment areas, Music Group
included, is now allow-listed. This module never edits the bridge's
configuration.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path
from typing import Iterable, Optional

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


def area_lights(ent_config: dict, entertainments: list, lights: list
                ) -> list[tuple[object, Optional[str], str]]:
    """Every bulb an entertainment configuration drives, one entry per
    channel member: `(channel_id, light resource id or None, name)`.

    The same walk spectra/services/ambient.py makes (channel member ->
    entertainment service -> its owning device -> that device's light), but
    over EVERY member of every channel, and a member that does not resolve
    to a light is kept with `None` rather than dropped — the stream judges
    what it cannot identify as out of scope. Pure: the three bridge payloads
    (`entertainment_configuration/<id>` data[0], `entertainment` data,
    `light` data) are passed in."""
    ent_owner = {e.get("id"): (e.get("owner") or {}).get("rid")
                 for e in entertainments or ()}
    dev_light = {(l.get("owner") or {}).get("rid"): l.get("id")
                 for l in lights or ()}
    light_name = {l.get("id"): (l.get("metadata") or {}).get("name") or l.get("id")
                  for l in lights or ()}
    out: list[tuple[object, Optional[str], str]] = []
    for channel in (ent_config or {}).get("channels", []) or []:
        cid = channel.get("channel_id")
        members = channel.get("members") or []
        if not members:
            out.append((cid, None, f"channel {cid} (no bulb named)"))
            continue
        for member in members:
            svc = member.get("service") or {}
            rid = None
            if svc.get("rtype") == "entertainment":
                rid = dev_light.get(ent_owner.get(svc.get("rid")))
            if rid:
                out.append((cid, str(rid), str(light_name.get(rid, rid))))
            else:
                out.append((cid, None, f"channel {cid} (bulb not identified)"))
    return out


def stream_refusal(area: Iterable[tuple[object, Optional[str], str]]
                   ) -> Optional[str]:
    """None when every bulb of an entertainment area is allow-listed (a
    session may start); otherwise the sentence naming the bulbs that keep
    it from starting. An empty area is refused too: nothing to judge is not
    the same as nothing to light."""
    area = list(area)
    if not area:
        return ("refused to start the Hue entertainment stream: the area's "
                "bulbs could not be read from the bridge, so Spectra cannot "
                "tell which bulbs a session would switch on")
    ok = load_allowed()
    bad = []
    for _cid, rid, name in area:
        if rid is None or str(rid) not in ok:
            if name not in bad:
                bad.append(name)
    if not bad:
        return None
    return ("refused to start the Hue entertainment stream: this area "
            f"includes {', '.join(bad)}, which Spectra may not light "
            f"(not on {SCOPE_FILE.name}). Starting a session switches on "
            "every bulb in the area, so the area is not streamed at all. "
            "Remove those bulbs from the entertainment area in the Hue app "
            "and Spectra streams the rest.")


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
