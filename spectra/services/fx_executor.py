"""The evolution engine's ONE execution seam — every glide and jump the S2
engine emits (drift legs, surge patches, colour jumps) passes through an
Executor. Two implementations, same surface:

  RecordingExecutor — the S2 PRODUCTION default. The engine is DARK against
      real lights until the S3 handover: calls are recorded (bounded log +
      modeled current values for the status surface) and go nowhere. No
      LedFX I/O of any kind lives behind this class.

  FacadeExecutor — the real path, driving the shared library's tween engine
      through fx.facade.handle() (in-process, zero HTTP). Headless tests
      prove the engine on it today; S3 points production at it when SPECTRA
      owns the lights. A glide is ONE PUT per virtual per leg
      (transition_ms tween — numeric lerp, colour/gradient hue-arc at LUT
      level, mid-tween retarget without snap); a jump is a 1 ms tween,
      which the tween engine lands on the next render frame — the design's
      "in-place instant write" without touching the colour-recreation
      crossfade branch.

The engine never calls services/fx_seam (the S1 owner-Fire HTTP path) —
that seam belongs to explicit owner fires, not the autonomous engine.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Any

JUMP_MS = 1            # a 1 ms tween lands next frame == an instant jump
HUE_BLEND = "hue"      # colours travel the wheel, never through grey
WRITE_LOG_LIMIT = 400  # bounded observability, oldest legs fall off


class ExecutorWrite(dict):
    """One recorded call. Plain dict subclass so status endpoints serialize
    it verbatim: {seq, at, kind, virtual_id, effect_type, params,
    duration_ms}."""


class RecordingExecutor:
    """Dark-mode executor: model, record, touch nothing."""

    mode = "recording"

    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._seq = 0
        self.writes: deque[ExecutorWrite] = deque(maxlen=WRITE_LOG_LIMIT)
        # Modeled value per virtual/param: jumps land immediately, glides are
        # modeled at their target (legs land by the next leg — display truth,
        # not render truth, which only exists behind the facade).
        self.current: dict[str, dict[str, Any]] = {}

    def _record(self, kind: str, virtual_id: str, effect_type: str,
                params: dict[str, Any], duration_ms: int) -> None:
        self._seq += 1
        self.writes.append(ExecutorWrite(
            seq=self._seq, at=self._clock(), kind=kind, virtual_id=virtual_id,
            effect_type=effect_type, params=dict(params),
            duration_ms=duration_ms))
        self.current.setdefault(virtual_id, {}).update(params)

    async def glide(self, virtual_id: str, effect_type: str,
                    params: dict[str, Any], duration_ms: int) -> None:
        if params:
            self._record("glide", virtual_id, effect_type, params, duration_ms)

    async def jump(self, virtual_id: str, effect_type: str,
                   params: dict[str, Any]) -> None:
        if params:
            self._record("jump", virtual_id, effect_type, params, JUMP_MS)


class FacadeExecutor(RecordingExecutor):
    """Real executor: same record/model discipline, plus the actual tween
    PUT through the in-process facade. Raises on a facade error status —
    the engine's supervisor logs it; silence would hide a dead write path
    (the write-plane lesson)."""

    mode = "facade"

    async def _put(self, virtual_id: str, effect_type: str,
                   params: dict[str, Any], duration_ms: int) -> None:
        from fx import facade
        resp = await facade.handle(
            "PUT", f"/api/virtuals/{virtual_id}/effects",
            json={"type": effect_type, "config": dict(params),
                  "transition_ms": duration_ms, "easing": "linear",
                  "transition_blend": HUE_BLEND})
        resp.raise_for_status()

    async def glide(self, virtual_id: str, effect_type: str,
                    params: dict[str, Any], duration_ms: int) -> None:
        if not params:
            return
        await self._put(virtual_id, effect_type, params, duration_ms)
        self._record("glide", virtual_id, effect_type, params, duration_ms)

    async def jump(self, virtual_id: str, effect_type: str,
                   params: dict[str, Any]) -> None:
        if not params:
            return
        await self._put(virtual_id, effect_type, params, JUMP_MS)
        self._record("jump", virtual_id, effect_type, params, JUMP_MS)
