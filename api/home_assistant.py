"""
SpotFX — Home Assistant integration.

Exposes an HTTP endpoint so HA can pause/resume the SpotFX trigger service.
Also provides a helper to call HA services from SpotFX if needed later.
"""
from __future__ import annotations
import logging

import httpx

from config import settings
from models.state import state

logger = logging.getLogger(__name__)


def pause_service() -> None:
    """Pause trigger firing (called via API endpoint or HA webhook)."""
    state.paused = True
    logger.info("SpotFX trigger service PAUSED.")


def resume_service() -> None:
    """Resume trigger firing."""
    state.paused = False
    logger.info("SpotFX trigger service RESUMED.")


async def call_ha_service(domain: str, service: str, data: dict) -> bool:
    """
    Call a Home Assistant service over the REST API.
    Not currently used but available for future actions.
    """
    if not settings.home_assistant_token:
        logger.warning("No HA token configured; skipping HA service call.")
        return False
    url = f"{settings.home_assistant_host}/api/services/{domain}/{service}"
    headers = {
        "Authorization": f"Bearer {settings.home_assistant_token}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=data, headers=headers, timeout=3.0)
            resp.raise_for_status()
            return True
    except Exception as exc:
        logger.error("HA service call failed: %s", exc)
        return False
