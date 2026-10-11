"""THE OUTBOUND HOME ASSISTANT CLIENT — the ONE path SPECTRA calls OUT to
Home Assistant. Every other HA seam in this codebase is the reverse
direction — `house.py`'s own "THE HA SEAM" section: HA pushes a mode, a
fixture state, the mains, IN to SPECTRA over its own routes
(`spectra/api/house.py`). This is the first one that calls out, built for
the Light Show's HA actions (`spectra/services/show_actions.py`'s "ha"
group: volume absolute/relative, activate scene — the Admiral, 2026-10-11).

    POST {SPECTRA_HA_URL}/api/services/<domain>/<service>
    Authorization: Bearer {SPECTRA_HA_TOKEN}
    {..data..}
    -> 2xx [...changed entity states, HA's own documented shape...]

This is Home Assistant's own REST API `call_service` endpoint, unchanged —
SPECTRA conforms to it rather than inventing a shape of its own, the same
posture `witness.py` takes with River's change service and
`transcription.py` takes with the Whisper bridge.

UNSET URL == INERT, AND THAT IS THE SHIPPED STATE. With `SPECTRA_HA_URL`
absent, `call_service()` sends nothing, opens no socket, imports no httpx,
and returns `HAResult(status=UNCONFIGURED)` — every caller (a Light Show
step) turns that into a named, visible outcome ("Home Assistant is not
configured...") on the step's own result. `pretake_ping.py`'s own
"UNSET URL == INERT" section is the precedent this follows exactly.

NEVER RAISES. Unreachable, a non-2xx, a timeout, a malformed body — every
one of these comes back as an `HAResult` the caller reports; nothing here
can make a Light Show set fail to RUN because Home Assistant happens to be
down. A set still records the failure, loudly, on that one step's outcome
— it is never swallowed.

THE TOKEN IS NEVER LOGGED, and neither is the configured URL's own
credentials (it carries none today, but the rule is `pretake_ping._post`'s,
unconditional): a transport exception is logged by its CLASS only, and a
non-2xx answer never echoes the Authorization header back.

A MISSING TOKEN STILL SENDS THE REQUEST, with no Authorization header,
rather than refusing locally — `pretake_token()`'s own reasoning: Home
Assistant's own 401 is the visible signal that no token is provisioned,
where a silent local refusal would read identically to a correctly
configured Home Assistant that is simply not answering.

LIVE USE IS UNVERIFIED BY THIS BUILD. No live Home Assistant instance was
reachable while this was written — every test here drives a mocked
transport. `SPECTRA_HA_URL`/`SPECTRA_HA_TOKEN` are River's to provision at
deploy; until they are, every HA action in the Light Show reports its own
"not configured" outcome and changes nothing.

`list_scenes()` is the SECOND call this module makes — `GET /api/states`,
filtered to the `scene.` domain — so the "Activate HA scene" step can
offer HIS OWN real scenes (the Admiral, 2026-10-11: "I want to be able to
customize the scene in HA and trigger it as part of the light show"), not
a hand-maintained allow-list that would never see a scene he makes later.
Unconfigured or unreachable answers the SAME way `call_service` does
(`HAStates(status=UNCONFIGURED/FAILED)`, never raises) — the step's own
entity-id field still works by typing a full id directly in that case,
since `show_console._resolve_ha_scene` only consults this list when the
given text does NOT already look like one.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from spectra import config

logger = logging.getLogger(__name__)

STATUS_SENT = "sent"
STATUS_FAILED = "failed"
STATUS_UNCONFIGURED = "unconfigured"

#: Bounded and modest — a Light Show step calling out to Home Assistant
#: should never be the thing that holds up a set for long; `pretake_ping`'s
#: own constants are the precedent for naming every leg explicitly rather
#: than trusting httpx's defaults.
CONNECT_TIMEOUT_S = 3.0
READ_TIMEOUT_S = 10.0
WRITE_TIMEOUT_S = 3.0
POOL_TIMEOUT_S = 1.0


@dataclass
class HAResult:
    """One outbound call's outcome, in the shape a Light Show step's
    Outcome is built from."""

    status: str = STATUS_UNCONFIGURED
    #: Home Assistant's own status code, or None when the request never
    #: got an answer (unconfigured, unreachable, timed out).
    http_status: Optional[int] = None
    detail: str = ""
    #: Her response body (a list of changed entity states on success), for
    #: a caller that wants more than the pass/fail word. Never rendered on
    #: its own — the `detail` sentence is what a person reads.
    body: Any = None

    @property
    def ok(self) -> bool:
        return self.status == STATUS_SENT

    def as_dict(self) -> dict:
        return {"status": self.status, "http_status": self.http_status,
                "detail": self.detail}


def ha_url() -> str:
    """Read at call time — `spectra/config.py` is where every SPECTRA
    environment knob lives (`pretake_ping.pretake_url()`'s own mirror)."""
    return config.ha_url()


def ha_token() -> str:
    return config.ha_token()


def configured() -> bool:
    """Whether there is an endpoint to call at all. URL only — a missing
    token is a VISIBLE 401 on the call itself, never silence
    (`ha_token()`'s own rule)."""
    return bool(ha_url())


def _endpoint(domain: str, service: str) -> str:
    return f"{ha_url()}/api/services/{domain}/{service}"


async def call_service(domain: str, service: str, data: Optional[dict] = None,
                       *, client: Optional[Any] = None) -> HAResult:
    """POST to Home Assistant's `/api/services/<domain>/<service>` — the
    ONE call every HA-reaching Light Show action makes. Never raises.

    `client` is the injection seam (tests drive a mocked transport); a
    caller passing none gets its own short-lived `httpx.AsyncClient`,
    closed on the way out."""
    url = ha_url()
    if not url:
        # INERT. Nothing sent, no httpx import — the shipped state.
        return HAResult(
            status=STATUS_UNCONFIGURED,
            detail="Home Assistant is not configured on this host "
                   "(SPECTRA_HA_URL is unset)")

    import httpx

    headers = {}
    token = ha_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    endpoint = _endpoint(domain, service)
    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=httpx.Timeout(
            connect=CONNECT_TIMEOUT_S, read=READ_TIMEOUT_S,
            write=WRITE_TIMEOUT_S, pool=POOL_TIMEOUT_S))
    try:
        resp = await client.post(endpoint, json=data or {}, headers=headers)
        try:
            body = resp.json()
        except Exception:                                # noqa: BLE001
            body = None
        if 200 <= resp.status_code < 300:
            return HAResult(status=STATUS_SENT, http_status=resp.status_code,
                            detail=f"Home Assistant: {domain}.{service} called",
                            body=body)
        detail = (f"Home Assistant answered {resp.status_code} for "
                 f"{domain}.{service} — nothing was changed")
        if resp.status_code == 401 and not token:
            detail += (" (no SPECTRA_HA_TOKEN is set on this host, so no "
                       "bearer was sent)")
        logger.error("ha_client: %s", detail)
        return HAResult(status=STATUS_FAILED, http_status=resp.status_code,
                        detail=detail, body=body)
    except Exception as exc:                             # noqa: BLE001
        # Deliberately the exception CLASS only — `pretake_ping._post`'s
        # own rule: the configured URL (and a future credentialed one)
        # must never reach a log line.
        detail = (f"Home Assistant could not be reached for {domain}."
                 f"{service} ({type(exc).__name__})")
        logger.error("ha_client: %s", detail)
        return HAResult(status=STATUS_FAILED, detail=detail)
    finally:
        if own:
            await client.aclose()


@dataclass
class HAEntityState:
    """`get_state()`'s own outcome: one entity's current `state` string,
    or why it could not be read. `state` is None whenever `ok` is False —
    never a stale or guessed value."""

    status: str = STATUS_UNCONFIGURED
    http_status: Optional[int] = None
    detail: str = ""
    state: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status == STATUS_SENT


async def get_state(entity_id: str, *, client: Optional[Any] = None) -> HAEntityState:
    """`GET /api/states/<entity_id>` — one entity's current state, READ
    ONLY. The THIRD call this module makes, added for the eased absolute
    volume step (`ha_volume_ease.py`), which has to know where the volume
    IS before it can walk it to where it should be. Never raises; the same
    fail-soft shape as `list_scenes()`."""
    url = ha_url()
    if not url:
        return HAEntityState(
            status=STATUS_UNCONFIGURED,
            detail="Home Assistant is not configured on this host "
                   "(SPECTRA_HA_URL is unset)")

    import httpx

    headers = {}
    token = ha_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=httpx.Timeout(
            connect=CONNECT_TIMEOUT_S, read=READ_TIMEOUT_S,
            write=WRITE_TIMEOUT_S, pool=POOL_TIMEOUT_S))
    try:
        resp = await client.get(f"{url}/api/states/{entity_id}", headers=headers)
        if not (200 <= resp.status_code < 300):
            detail = f"Home Assistant answered {resp.status_code} for {entity_id}"
            logger.error("ha_client: %s", detail)
            return HAEntityState(status=STATUS_FAILED,
                                 http_status=resp.status_code, detail=detail)
        try:
            body = resp.json()
        except Exception:                                # noqa: BLE001
            body = None
        state = body.get("state") if isinstance(body, dict) else None
        if not isinstance(state, str):
            return HAEntityState(status=STATUS_FAILED,
                                 http_status=resp.status_code,
                                 detail=f"Home Assistant's state for "
                                        f"{entity_id} carried no state")
        return HAEntityState(status=STATUS_SENT, http_status=resp.status_code,
                             state=state)
    except Exception as exc:                             # noqa: BLE001
        detail = (f"Home Assistant could not be reached for {entity_id} "
                 f"({type(exc).__name__})")
        logger.error("ha_client: %s", detail)
        return HAEntityState(status=STATUS_FAILED, detail=detail)
    finally:
        if own:
            await client.aclose()


@dataclass
class HAStates:
    """`list_scenes()`'s own outcome — the `HAResult` shape, plus the
    scenes themselves. `ok` is True only on a genuine 2xx; `scenes` is
    always `[]` otherwise, never a partial or stale list."""

    status: str = STATUS_UNCONFIGURED
    http_status: Optional[int] = None
    detail: str = ""
    scenes: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == STATUS_SENT

    def as_dict(self) -> dict:
        return {"status": self.status, "http_status": self.http_status,
                "detail": self.detail, "scenes": list(self.scenes)}


async def list_scenes(*, client: Optional[Any] = None) -> HAStates:
    """`GET /api/states`, filtered to the `scene.` domain — his own real
    HA scenes, named by their `friendly_name` attribute where HA reports
    one. Never raises; unconfigured/unreachable/non-2xx all come back as
    an empty, explicitly-non-ok list, exactly `call_service`'s own fail-
    soft shape."""
    url = ha_url()
    if not url:
        return HAStates(
            status=STATUS_UNCONFIGURED,
            detail="Home Assistant is not configured on this host "
                   "(SPECTRA_HA_URL is unset)")

    import httpx

    headers = {}
    token = ha_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    endpoint = f"{url}/api/states"
    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=httpx.Timeout(
            connect=CONNECT_TIMEOUT_S, read=READ_TIMEOUT_S,
            write=WRITE_TIMEOUT_S, pool=POOL_TIMEOUT_S))
    try:
        resp = await client.get(endpoint, headers=headers)
        if not (200 <= resp.status_code < 300):
            detail = f"Home Assistant answered {resp.status_code} for /api/states"
            if resp.status_code == 401 and not token:
                detail += (" (no SPECTRA_HA_TOKEN is set on this host, so "
                          "no bearer was sent)")
            logger.error("ha_client: %s", detail)
            return HAStates(status=STATUS_FAILED, http_status=resp.status_code,
                            detail=detail)
        try:
            body = resp.json()
        except Exception:                                # noqa: BLE001
            return HAStates(status=STATUS_FAILED, http_status=resp.status_code,
                            detail="Home Assistant's /api/states did not "
                                  "return JSON")
        scenes = []
        if isinstance(body, list):
            for entry in body:
                if not isinstance(entry, dict):
                    continue
                eid = entry.get("entity_id")
                if not isinstance(eid, str) or not eid.startswith("scene."):
                    continue
                attrs = entry.get("attributes") or {}
                name = (attrs.get("friendly_name") if isinstance(attrs, dict) else None) \
                    or eid.split(".", 1)[-1].replace("_", " ")
                scenes.append({"id": eid, "name": name})
        scenes.sort(key=lambda s: s["name"].lower())
        return HAStates(status=STATUS_SENT, http_status=resp.status_code,
                        scenes=scenes)
    except Exception as exc:                             # noqa: BLE001
        detail = f"Home Assistant could not be reached ({type(exc).__name__})"
        logger.error("ha_client: %s", detail)
        return HAStates(status=STATUS_FAILED, detail=detail)
    finally:
        if own:
            await client.aclose()
