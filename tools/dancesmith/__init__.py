"""dancesmith — headless preview/validation for the native LedFX Dancer
effect's dance library (ledfx-src/ledfx/effects/dancer_moves.py).

The GIF pipeline lives in tools/gifsmith; this toolkit is for the
procedural dancer. See README.md here for the dance-authoring pipeline.
"""

import sys
from pathlib import Path

LEDFX_SRC = Path.home() / "ledfx-src"


def import_moves():
    """Import ledfx.effects.dancer_moves without needing the ledfx venv."""
    if str(LEDFX_SRC) not in sys.path:
        sys.path.insert(0, str(LEDFX_SRC))
    from ledfx.effects import dancer_moves  # noqa: PLC0415

    return dancer_moves
