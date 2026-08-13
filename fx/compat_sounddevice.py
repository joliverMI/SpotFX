"""Lazy sounddevice loader (SpotFX-authored).

The fork's ledfx/effects/audio.py does `import sounddevice as sd` at module
scope; importing sounddevice initializes PortAudio and scans the host's audio
hardware. That is an import-time hardware side effect the vendored package
must not have (fx must import cleanly in tests, offline tools, and processes
that never touch audio). audio.py's import is therefore rewritten to
`from fx.compat_sounddevice import sd` — the ONE functional deviation from
the verbatim vendor, see fx/VENDOR.md.

`sd` proxies attribute access to the real sounddevice module, imported on
first use. All call sites (`sd.query_devices()`, `sd.InputStream`, ...) work
unchanged; PortAudio now loads when audio input is actually opened, not when
fx.effects.audio is imported.
"""

import importlib


class _LazySounddevice:
    _module = None

    def __getattr__(self, name):
        if _LazySounddevice._module is None:
            _LazySounddevice._module = importlib.import_module("sounddevice")
        return getattr(_LazySounddevice._module, name)


sd = _LazySounddevice()
