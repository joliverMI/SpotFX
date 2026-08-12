"""Extract per-device layout profiles from a live LedFX instance.

A profile records the 2D grid of a matrix virtual and which cells are real
pixels vs gap fillers, so asset renderers/previews can account for unusual
layouts (e.g. the hex-lattice "crystal" panel where only every other column
of a row is a real pixel).
"""

from __future__ import annotations

import json
from pathlib import Path

import requests

from . import DEFAULT_LEDFX_URL

PROFILES_DIR = Path(__file__).resolve().parents[2] / "storage" / "device_profiles"


def _mask_to_rle(mask: list[bool]) -> list[int]:
    """Run-length encode a flat bool mask as alternating run lengths,
    starting with a run of False (may be 0)."""
    runs: list[int] = []
    current = False
    count = 0
    for value in mask:
        if value == current:
            count += 1
        else:
            runs.append(count)
            current = value
            count = 1
    runs.append(count)
    return runs


def rle_to_mask(runs: list[int]) -> list[bool]:
    mask: list[bool] = []
    value = False
    for run in runs:
        mask.extend([value] * run)
        value = not value
    return mask


def extract_profile(virtual_id: str, base_url: str = DEFAULT_LEDFX_URL) -> dict:
    resp = requests.get(f"{base_url}/api/virtuals", timeout=10)
    resp.raise_for_status()
    virtuals = resp.json()["virtuals"]
    if virtual_id not in virtuals:
        raise SystemExit(f"virtual '{virtual_id}' not found; have: {sorted(virtuals)}")
    virtual = virtuals[virtual_id]

    rows = virtual.get("config", {}).get("rows", 1)
    pixel_count = virtual["pixel_count"]
    cols = pixel_count // rows
    segments = virtual.get("segments", [])

    # A cell is "real" when its segment points at a non-gap, non-dummy device.
    devices = requests.get(f"{base_url}/api/devices", timeout=10).json()["devices"]

    def is_real(device_id: str) -> bool:
        if device_id.startswith("gap-"):
            return False
        return devices.get(device_id, {}).get("type") != "dummy"

    mask: list[bool] = []
    real_devices: set[str] = set()
    for device_id, start, end, _flip, *_ in segments:
        length = end - start + 1
        real = is_real(device_id)
        if real:
            real_devices.add(device_id)
        mask.extend([real] * length)

    if not segments:
        # A plain device-backed virtual: every cell is real.
        mask = [True] * pixel_count
        real_devices = {virtual_id}
    if len(mask) != pixel_count:
        raise SystemExit(
            f"segment mask length {len(mask)} != pixel_count {pixel_count}"
        )

    grid = [mask[r * cols : (r + 1) * cols] for r in range(rows)]

    # Detect a hex lattice: real cells only on alternating columns, with the
    # column parity varying by row. In that case a 1-px vertical stroke lands
    # on gaps in half the rows, so strokes must be >= 2 px wide.
    hex_lattice = False
    if cols > 1 and rows > 1:
        parities = set()
        alternating = True
        for row in grid:
            used = [c for c, v in enumerate(row) if v]
            if not used:
                continue
            pars = {c % 2 for c in used}
            if len(pars) > 1:
                alternating = False
                break
            parities.add(next(iter(pars)))
        hex_lattice = alternating and len(parities) == 2

    real_count = sum(mask)
    effective_width = max(
        (sum(1 for v in row if v) for row in grid), default=cols
    ) if hex_lattice else cols

    profile = {
        "virtual_id": virtual_id,
        "rows": rows,
        "cols": cols,
        "pixel_count": pixel_count,
        "real_devices": sorted(real_devices),
        "real_pixel_count": real_count,
        "mask_rle": _mask_to_rle(mask),
        "hex_lattice": hex_lattice,
        "effective_width": effective_width,
        "effective_height": rows,
        "min_stroke_px": 2 if hex_lattice else 1,
        "recommended_effect_config": {
            "force_fit": True,
            "keep_aspect_ratio": False,
            "stretch_horizontal": 100,
            "stretch_vertical": 100,
            "center_horizontal": 0,
            "center_vertical": 0,
        },
    }
    return profile


def load_profile(virtual_id: str) -> dict:
    path = PROFILES_DIR / f"{virtual_id}.json"
    if not path.exists():
        raise SystemExit(
            f"no profile for '{virtual_id}' — run: python -m tools.gifsmith profile {virtual_id}"
        )
    return json.loads(path.read_text())


def profile_mask(profile: dict) -> list[list[bool]]:
    mask = rle_to_mask(profile["mask_rle"])
    cols = profile["cols"]
    return [mask[r * cols : (r + 1) * cols] for r in range(profile["rows"])]


def save_profile(profile: dict) -> Path:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    path = PROFILES_DIR / f"{profile['virtual_id']}.json"
    path.write_text(json.dumps(profile, indent=2) + "\n")
    return path
