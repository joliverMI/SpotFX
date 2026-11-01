"""THE "ONE TAP" (data/tv-display-plan/plan.html PR 1.6, §2.3) —
SPECTRA never talks to the TV directly. ONE Home Assistant script owns
"open the TV app" (River's own, named in the plan's §2.3 diagram:
`script.tv_open_spectra`, which calls `webostv.command
system.launcher/open` with the TV app's URL and also turns the TV on).
Every caller funnels through ONE function here, `put_on_tv()`, into
`ha_client.call_service("script", "turn_on", ...)` — never a second
path:

  * the Jukebox page's "Put on the TV" button (`spectra/api/tv_launch.py`'s
    `POST /api/tv/put-on-tv`);
  * a Light Show HA step (`show_actions.py`'s `ha_put_on_tv` action kind,
    the "ha" group's precedent — `ha_volume_absolute`/`ha_activate_scene`);
  * the optional auto-open at a jukebox night's start (this module's own
    `run_auto_open_supervised`, below);
  * Sonic, asking first (`tv_console.py`).

INERT WITHOUT HA CONFIGURED, structurally, the same way as every other
`ha_client` caller: `put_on_tv()` is a thin pass-through to
`ha_client.call_service`, which itself returns
`HAResult(status="unconfigured")` with `SPECTRA_HA_URL` unset — nothing
here adds a SECOND configuration gate on top of that one.

THE CONFIGURED SCRIPT ENTITY is a tiny durable setting
(`storage/spectra/tv_launch.json`, `TvLaunchConfig`:
`auto_open_enabled` default False, `script_entity` default None meaning
`DEFAULT_SCRIPT_ENTITY`) — never a `RoomControlState` field (that's
lighting) and never a `ShowConfig`/`ProgramConfig` field (the Jukebox's
own settings live in SpotFX, which this module may not import —
`scripts/check_process_split.py`).

THE AUTO-OPEN POLL IS ITS OWN ALWAYS-RUNNING BACKGROUND TASK
(`run_auto_open_supervised`, wired in `spectra/app.py`'s lifespan next to
`known_buffer`'s own poll loops) — deliberately NOT riding
`tv_feed.run_jukebox_loop`'s existing per-connection poll, because that
loop only runs while a TV is already connected, which is exactly the
case auto-open needs to cover: nobody has the TV open yet. It polls
SpotFX's `GET /api/jukebox/tv` on its own modest cadence
(`AUTO_OPEN_POLL_S`, independent of `tv_feed`'s own tighter 1 s
per-connection polling) and fires `put_on_tv()` on the RISING EDGE of
`running` — never on every poll while a night continues, and never while
`auto_open_enabled` is False (plan's own Q4 default: "off — a TV
switching itself on is surprising"). THE VERY FIRST POLL OF A FRESH
PROCESS NEVER FIRES, even if a night happens to already be running —
only an edge OBSERVED by this poller counts, so a process restart during
an ongoing night can never fire a spurious auto-open (the same "a fresh
tracker starts just became active, never already idle" reasoning
`tv_feed.ActivityTracker` already states for the identical class of
restart hazard). A FAILED fetch (`fetch_running()` returning `None`, the
board was unreachable) is treated as "unknown" and folded into the next
real reading the same way: an unknown→True transition DOES count as an
edge (the conservative direction — we would rather risk one unnecessary
open than silently miss a real night start because one poll dropped).

NO TV CALL IN ANY TEST. Every test here injects a fake `call_service`
(or a fake `fetch_running`/`put_on_tv`) — nothing imports `httpx` or
`ha_client` at module load time, matching `ha_client.py`'s own posture.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from spectra import config as scfg

logger = logging.getLogger(__name__)

#: River's own HA script, named in the plan's §2.3 diagram — opens the TV
#: app and also turns the TV on. A room without this exact script
#: provisioned still sends the call; HA's own error is the visible
#: signal, same as `ha_client.py`'s own "a missing token still sends the
#: request" rule.
DEFAULT_SCRIPT_ENTITY = "script.tv_open_spectra"

#: How often the always-running auto-open poller asks SpotFX whether a
#: night is running. Modest on purpose — this answers "did a night just
#: start", not "give me a live feed" (tv_feed.py's own per-connection 1 s
#: poll already covers that once a TV is connected).
AUTO_OPEN_POLL_S = 10.0


@dataclass
class TvLaunchConfig:
    auto_open_enabled: bool = False
    #: None means "use DEFAULT_SCRIPT_ENTITY" — see resolved_script().
    script_entity: Optional[str] = None

    def resolved_script(self) -> str:
        return (self.script_entity or "").strip() or DEFAULT_SCRIPT_ENTITY

    def as_dict(self) -> dict:
        return {"auto_open_enabled": self.auto_open_enabled,
                "script_entity": self.script_entity}


class TvLaunchPatchError(ValueError):
    """Raised by `apply_patch` for a malformed field — the API layer maps
    this to HTTP 422 rather than silently guessing a value."""


def _coerce_bool(name: str, value: Any) -> bool:
    """A real JSON/Python bool is the only trusted input; a bare
    `bool(value)` cast (Python truthiness) would read the JSON STRING
    `"false"` as `True`, inverting a safety-critical default (`AGENTS.md`'s
    own `show_actions._coerce` bool branch is the precedent this mirrors:
    check `isinstance(value, bool)` first, accept only the literal
    `"true"`/`"false"` tokens case-insensitively as a leniency, and refuse
    anything else by name instead of guessing)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
    raise TvLaunchPatchError(f"{name}: expected true or false, got {value!r}")


def _path(path=None):
    return path or scfg.TV_LAUNCH_FILE


def load_config(path=None) -> TvLaunchConfig:
    p = _path(path)
    try:
        if not os.path.exists(p):
            return TvLaunchConfig()
        with open(p, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        return TvLaunchConfig(
            auto_open_enabled=bool(raw.get("auto_open_enabled", False)),
            script_entity=(raw.get("script_entity") or None))
    except Exception:                                  # noqa: BLE001
        logger.exception("tv launch: unreadable config %s", p)
        return TvLaunchConfig()


def save_config(cfg: TvLaunchConfig, path=None) -> None:
    p = _path(path)
    os.makedirs(os.path.dirname(str(p)) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(str(p)) or ".",
                               prefix="tv-launch", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(cfg.as_dict(), fh, indent=2)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def apply_patch(patch: dict, path=None) -> TvLaunchConfig:
    """A TRUE PARTIAL UPDATE — only the keys actually present in `patch`
    change; everything else is byte-preserved (`room_controls.
    merge_room_controls`'s own precedent for why a partial merge, not a
    full-model bind, is the only safe shape for a PUT body an API caller
    may send only part of)."""
    cfg = load_config(path)
    if "auto_open_enabled" in patch:
        cfg.auto_open_enabled = _coerce_bool("auto_open_enabled", patch["auto_open_enabled"])
    if "script_entity" in patch:
        raw = patch["script_entity"]
        cfg.script_entity = (str(raw).strip() or None) if raw else None
    save_config(cfg, path)
    return cfg


async def put_on_tv(script_entity: Optional[str] = None, *,
                    call_service: Optional[Callable[..., Awaitable[Any]]] = None,
                    config_path=None) -> Any:
    """The ONE function every caller funnels through. An explicit
    `script_entity` wins outright; otherwise the configured one
    (`load_config().resolved_script()`). `call_service` defaults to
    `ha_client.call_service`, imported lazily so this module carries zero
    httpx/ha_client side effects at load time — the same reason every
    other `ha_client` caller in this codebase lazy-imports it."""
    entity = (script_entity or "").strip() or load_config(config_path).resolved_script()
    if call_service is None:
        from spectra.services import ha_client
        call_service = ha_client.call_service
    return await call_service("script", "turn_on", {"entity_id": entity})


# ── the always-running auto-open poller ─────────────────────────────────────

async def _default_fetch_running() -> Optional[bool]:
    """`GET` SpotFX's own `/api/jukebox/tv` — the SAME endpoint
    `tv_feed.py`'s own jukebox relay reads (PR 1.3). A SECOND, independent
    fetch is necessary here (not a shared cache) because this poller must
    keep running even while no TV is connected — see the module
    docstring. `None` (never `False`) on any failure — a dropped read is
    "unknown", not "not running"."""
    import httpx

    from spectra.services import bridge
    url = bridge.default_http_url()
    try:
        async with httpx.AsyncClient(base_url=url, timeout=5.0) as client:
            resp = await client.get("/api/jukebox/tv")
            resp.raise_for_status()
            data = resp.json()
        return bool(data.get("running")) if isinstance(data, dict) else None
    except Exception:                                  # noqa: BLE001
        logger.warning("tv launch: auto-open poll could not read "
                       "/api/jukebox/tv", exc_info=True)
        return None


@dataclass
class AutoOpenDeps:
    """Every seam `run_auto_open_supervised` touches, all swappable —
    `TvFeedDeps`'s own shape. Production defaults are set in
    `run_auto_open_supervised` itself, not here, so importing this
    dataclass never pulls in httpx/bridge/ha_client."""
    fetch_running: Callable[[], Awaitable[Optional[bool]]] = _default_fetch_running
    put_on_tv: Callable[[Optional[str]], Awaitable[Any]] = put_on_tv
    load_config: Callable[[], TvLaunchConfig] = load_config
    sleep: Callable[[float], Awaitable[None]] = field(default=asyncio.sleep)


async def run_auto_open_supervised(deps: Optional[AutoOpenDeps] = None,
                                   iterations: Optional[int] = None) -> None:
    """Polls whether a jukebox night is running, every `AUTO_OPEN_POLL_S`,
    and fires `put_on_tv()` on the rising edge — ONLY while
    `auto_open_enabled` is set. The first iteration of a fresh task NEVER
    fires (see module docstring: a restart during an ongoing night must
    not re-trigger). `iterations` is the testability seam (`known_buffer.
    run_poll_supervised`'s own convention) — `None` loops forever. Never
    raises; a dead poller takes only the auto-open feature with it."""
    d = deps or AutoOpenDeps()
    last_running: Optional[bool] = None
    first = True
    count = 0
    while iterations is None or count < iterations:
        count += 1
        try:
            running = await d.fetch_running()
            cfg = d.load_config()
            if not first and cfg.auto_open_enabled and running and not last_running:
                result = await d.put_on_tv(None)
                logger.info("tv launch: auto-opened the TV on jukebox "
                           "night start (%s)", result)
            last_running = running
            first = False
        except asyncio.CancelledError:
            raise
        except Exception:                                # noqa: BLE001
            logger.exception("tv launch: auto-open poll iteration failed")
        if iterations is not None and count >= iterations:
            return
        await d.sleep(AUTO_OPEN_POLL_S)
