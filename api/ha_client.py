"""
SpotFX — the house volume, for Absorb Music (data/absorb-music-plan/
report.md §3 and §12 phase 2). Three things and only three:

  read()            input_number.snap_volume and input_boolean.sleeping
  set_volume(v)     script.music_volume_set {"volume": v}, one SNAPPED write

`snap_volume` is River's global Snapcast level: the house's "Snap Volume
Control" automation fans it out to every audible room and — the plan's
evidence, which absorb_silence.py re-proves at runtime rather than trusting —
leaves the capture client (`Effects Host`) alone.

TWO ROUTES, ONE CHOSEN BY A SETTING (`settings.absorb_ha_via`):

  "spectra" (default)  SPECTRA's narrow /spectra/api/house-audio route
                       (spectra/api/house_audio.py), which holds the working
                       River-provisioned token and writes through
                       spectra/services/ha_volume_ease.py — the one owner of
                       snap_volume ramps, which stops a Light Show ramp in
                       flight before writing, so absorb's 0 can never be
                       overwritten by a ramp's next step.
  "direct"             Home Assistant's own REST API with HOME_ASSISTANT_HOST
                       / HOME_ASSISTANT_TOKEN from this process's .env. The
                       plan asked for this route ("verify that token first");
                       verified 2026-10-20 with one read-only GET /api/: the
                       token there is the .env.template placeholder and Home
                       Assistant answers 401 — hence the default above. A
                       real token makes it usable; it does not stop a ramp.

NEVER RAISES. Every failure comes back as a result the caller reports —
an unreadable volume is `volume=None`, an unreadable sleeping flag is
`sleeping=None`, never a guess. THE TOKEN IS NEVER LOGGED: a transport error
is logged by its class only.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

SNAP_VOLUME_ENTITY = "input_number.snap_volume"
SLEEPING_ENTITY = "input_boolean.sleeping"
VOLUME_SCRIPT = ("script", "music_volume_set")
TEMPLATE_PLACEHOLDER_TOKEN = "your_ha_long_lived_token_here"
TIMEOUT_S = 6.0


@dataclass
class HouseAudioReading:
    """`volume` 0-100 or None (unreadable); `sleeping` or None (unreadable)."""
    volume: Optional[float] = None
    sleeping: Optional[bool] = None
    detail: str = ""

    @property
    def volume_ok(self) -> bool:
        return self.volume is not None


@dataclass
class HouseAudioWrite:
    ok: bool
    detail: str = ""


def _on_off(state: Any) -> Optional[bool]:
    s = str(state).strip().lower()
    if s == "on":
        return True
    if s == "off":
        return False
    return None


def _num(state: Any) -> Optional[float]:
    try:
        v = float(state)
    except (TypeError, ValueError):
        return None
    return v if 0.0 <= v <= 100.0 else None


class HouseAudio:
    """The interface absorb_silence talks to; tests hand it a fake."""
    via = "none"

    async def read(self) -> HouseAudioReading:
        raise NotImplementedError

    async def set_volume(self, volume: int) -> HouseAudioWrite:
        raise NotImplementedError


class SpectraHouseAudio(HouseAudio):
    """Through SPECTRA's /spectra/api/house-audio (the default)."""
    via = "spectra"

    def __init__(self, base_url: str, *, client: Any = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = client

    async def _request(self, method: str, path: str, **kw) -> Any:
        import httpx
        if self._client is not None:
            return await self._client.request(method, self.base_url + path, **kw)
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            return await client.request(method, self.base_url + path, **kw)

    async def read(self) -> HouseAudioReading:
        try:
            resp = await self._request("GET", "")
            if resp.status_code != 200:
                return HouseAudioReading(detail=f"SPECTRA answered {resp.status_code}")
            body = resp.json()
        except Exception as exc:                                  # noqa: BLE001
            logger.warning("Absorb: house audio unreadable via SPECTRA (%s)",
                           type(exc).__name__)
            return HouseAudioReading(detail=f"SPECTRA unreachable ({type(exc).__name__})")
        if not isinstance(body, dict):
            return HouseAudioReading(detail="SPECTRA's answer was not an object")
        vol = body.get("snap_volume") or {}
        slp = body.get("sleeping") or {}
        volume = _num(vol.get("value")) if vol.get("ok") else None
        sleeping = slp.get("value") if slp.get("ok") and isinstance(slp.get("value"), bool) else None
        detail = "; ".join(d for d in (
            "" if volume is not None else (vol.get("detail") or "snap_volume unreadable"),
            "" if sleeping is not None else (slp.get("detail") or "sleeping unreadable"),
        ) if d)
        if body.get("configured") is False:
            detail = "Home Assistant is not configured on SPECTRA (SPECTRA_HA_URL is unset)"
        return HouseAudioReading(volume=volume, sleeping=sleeping, detail=detail)

    async def set_volume(self, volume: int) -> HouseAudioWrite:
        v = max(0, min(100, int(round(volume))))
        try:
            resp = await self._request("PUT", "/volume", json={"volume": v})
            body = resp.json() if resp.status_code == 200 else {}
        except Exception as exc:                                  # noqa: BLE001
            logger.warning("Absorb: house volume write via SPECTRA failed (%s)",
                           type(exc).__name__)
            return HouseAudioWrite(False, f"SPECTRA unreachable ({type(exc).__name__})")
        if resp.status_code != 200:
            return HouseAudioWrite(False, f"SPECTRA answered {resp.status_code}")
        if not isinstance(body, dict) or not body.get("ok"):
            return HouseAudioWrite(False, str((body or {}).get("detail") or "not accepted"))
        return HouseAudioWrite(True, str(body.get("detail") or ""))


class DirectHouseAudio(HouseAudio):
    """Home Assistant's REST API directly, with this process's own token."""
    via = "direct"

    def __init__(self, host: str, token: str, *, client: Any = None) -> None:
        self.host = host.rstrip("/")
        self._token = token
        self._client = client

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    async def _request(self, method: str, path: str, **kw) -> Any:
        import httpx
        kw.setdefault("headers", self._headers())
        if self._client is not None:
            return await self._client.request(method, self.host + path, **kw)
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            return await client.request(method, self.host + path, **kw)

    async def _state(self, entity: str) -> tuple[Any, str]:
        try:
            resp = await self._request("GET", f"/api/states/{entity}")
        except Exception as exc:                                  # noqa: BLE001
            logger.warning("Absorb: Home Assistant unreachable for %s (%s)",
                           entity, type(exc).__name__)
            return None, f"Home Assistant unreachable ({type(exc).__name__})"
        if resp.status_code != 200:
            return None, f"Home Assistant answered {resp.status_code} for {entity}"
        try:
            return (resp.json() or {}).get("state"), ""
        except Exception:                                         # noqa: BLE001
            return None, f"Home Assistant's answer for {entity} was not JSON"

    async def read(self) -> HouseAudioReading:
        if not self.host:
            return HouseAudioReading(detail="HOME_ASSISTANT_HOST is unset")
        vol_raw, vd = await self._state(SNAP_VOLUME_ENTITY)
        slp_raw, sd = await self._state(SLEEPING_ENTITY)
        volume = _num(vol_raw)
        sleeping = _on_off(slp_raw)
        detail = "; ".join(d for d in (
            vd or ("" if volume is not None else f"snap_volume unreadable ({vol_raw!r})"),
            sd or ("" if sleeping is not None else f"sleeping unreadable ({slp_raw!r})"),
        ) if d)
        return HouseAudioReading(volume=volume, sleeping=sleeping, detail=detail)

    async def set_volume(self, volume: int) -> HouseAudioWrite:
        if not self.host:
            return HouseAudioWrite(False, "HOME_ASSISTANT_HOST is unset")
        v = max(0, min(100, int(round(volume))))
        domain, service = VOLUME_SCRIPT
        try:
            resp = await self._request("POST", f"/api/services/{domain}/{service}",
                                       json={"volume": v})
        except Exception as exc:                                  # noqa: BLE001
            logger.warning("Absorb: house volume write failed (%s)", type(exc).__name__)
            return HouseAudioWrite(False, f"Home Assistant unreachable ({type(exc).__name__})")
        if not (200 <= resp.status_code < 300):
            return HouseAudioWrite(False, f"Home Assistant answered {resp.status_code}")
        return HouseAudioWrite(True, f"snap_volume set to {v}")


def real_token(token: str) -> bool:
    t = (token or "").strip()
    return bool(t) and t != TEMPLATE_PLACEHOLDER_TOKEN


def from_settings() -> HouseAudio:
    from config import settings
    if settings.absorb_ha_via == "direct":
        token = settings.home_assistant_token if real_token(settings.home_assistant_token) else ""
        return DirectHouseAudio(settings.home_assistant_host, token)
    return SpectraHouseAudio(
        f"http://127.0.0.1:{settings.spectra_port}/spectra/api/house-audio")
