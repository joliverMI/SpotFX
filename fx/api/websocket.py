"""SpotFX stub for the fork's ledfx/api/websocket.py (not vendored).

fx/effects/audio.py imports WEB_AUDIO_CLIENTS / WebAudioStream /
ACTIVE_AUDIO_STREAM to support browser-microphone audio sources. SpotFX never
uses web audio (the audio source is a local capture stream), so this stub
keeps those references importable while making accidental use loud.
"""

# Set of connected web-audio client ids. Always empty: no websocket layer.
WEB_AUDIO_CLIENTS: set = set()

# The fork stores the active WebAudioStream here; audio.py reassigns it.
ACTIVE_AUDIO_STREAM = None


class WebAudioStream:
    """Placeholder for the fork's browser-microphone stream. Constructing one
    means an audio_device index pointing at a WEB AUDIO entry was selected,
    which SpotFX never configures."""

    def __init__(self, *args, **kwargs):
        raise RuntimeError(
            "fx.api.websocket.WebAudioStream is a SpotFX stub: web-audio "
            "sources are not part of the vendored render pipeline"
        )
