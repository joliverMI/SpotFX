# fx/ — vendored LedFX render pipeline

Source: the SpotFX LedFX fork at `/home/javi/ledfx-src`,
branch `wip/matrix-dancers-snapshot-20260812`, commit `149f4470`
("WIP snapshot: dancer/eye/shapemap/lattice matrix work as of 2026-08-12").
License: GPL-3.0 (`fx/LICENSE`, copied from the fork's `LICENSE.txt`).

This is Stage 1 of the approved Option C merge
(`/home/javi/fleet-spotfx/data/spotfx-ledfx-merge-scout/report.md` §3,
`decision-merge-architecture-choice.md`): the subset of `ledfx/` that
production actually uses, imported as `fx.*` inside SpotFX. The fork stays
installed and untouched; nothing here runs unless the in-process facade is
switched on (`settings.fx_in_process`, default off).

## What is vendored (verbatim except the deviations below)

- Core: `color.py`, `config.py`, `consts.py`, `events.py`, `shapemap.py`,
  `transitions.py`, `utils.py`, `virtuals.py`, `scenes.py`, `assets.py`
- Effects plumbing: `effects/__init__.py` (effect base + server-side tween
  engine), `twod.py`, `audio.py`, `melbank.py`, `mel.py`, `math.py`,
  `gradient.py`, `hsv_effect.py`, `modulate.py`, `temporal.py`, `gifbase.py`,
  `particle_handoff.py`, `lattice.py`, `oneshots/oneshot.py`,
  `utils/logsec_helper.py`, `utils/get_info.py`
- The effects production uses (the 19 in `config/effect_params.json` plus
  `singleColor`; `dancer` brings `dancer_moves` + `dancer_flames`):
  blackhole, blackhole1d, blender, concentric, dancer, equalizer2d, eye,
  fireworks, fireworks1d, gifplayer, keybeat2d, melt, noise2d, orbits,
  orbits1d, pacman, power, radial, squiggles, singleColor
- Devices: registry (`devices/__init__.py`), the three production driver
  families — `ddp.py`/`wled.py` (plus `e131.py`, `udp.py`, `packets.py` which
  `wled.py` imports), `hue.py` (the fork's hardened Hue entertainment driver,
  as-is), `dummy.py` — and nothing else (the other ~20 drivers are dropped)
- Support pulled by `utils.py`/`assets.py`: `libraries/cache.py`,
  `utilities/{gradient_extraction,image_utils,security_utils}.py`

Dropped entirely (per report Option C): `core.py`, the aiohttp server and
`ledfx/api/*`, the LedFX frontend, zeroconf/mDNS, integrations, sentry, tray
icon, sendspin, nowplaying, presets library, playlists.

`effects/oneshots/` and `effects/utils/` have no `__init__.py` in the fork
(namespace packages); that is preserved here.

## Import rewrite

Mechanical rewrite in every vendored file — import statements only, plus the
three registry package-name strings (`"ledfx.effects"` → `"fx.effects"`,
`"ledfx.devices"` → `"fx.devices"`, `"ledfx.virtuals"` → `"fx.virtuals"`) and
`ledfx.api.websocket.` attribute references in `effects/audio.py`. Local
variables named `ledfx` (the core object handle) are untouched.

## Deviations from verbatim (complete list)

1. `effects/audio.py`: `import sounddevice as sd` →
   `from fx.compat_sounddevice import sd`. Importing sounddevice initializes
   PortAudio and scans audio hardware at import time; the proxy defers that
   to first use. See `fx/compat_sounddevice.py`.
2. `effects/utils/get_info.py`: module-scope `import aiohttp` moved into the
   two functions that use it. aiohttp belongs to the dropped web stack and is
   not a SpotFX dependency; the helper only runs in logsec diag mode.
3. `consts.py`: `import ledfx_assets` → `import fx.assets_builtin as
   ledfx_assets`. The fork's `ledfx_assets/` is 23 MB of media; the shim
   keeps `LEDFX_ASSETS_PATH` resolvable (builtin:// lookups find nothing —
   production GIFs live in the user asset store under the fx config dir).
4. New SpotFX-authored boundary stubs (not fork code): `api/websocket.py`
   (WEB_AUDIO_CLIENTS / WebAudioStream / ACTIVE_AUDIO_STREAM),
   `sendspin/{__init__,config,stream}.py` (SENDSPIN_AVAILABLE = False),
   `assets_builtin/`, `compat_sounddevice.py`.
5. `device_model.py` — SpotFX-authored (not fork code): the shared device
   model (categories/virtual topology, effect-param registry, scope
   resolution) the architecture decision places in the shared library.
   SPECTRA imports it; spot-effects keeps its own services until replaced.

Everything else is byte-identical to the fork at 149f4470 modulo the import
rewrite. When updating vendored files, re-diff against that commit.
