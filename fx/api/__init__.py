"""SpotFX stub package. The fork's ledfx/api is the aiohttp REST layer and is
deliberately NOT vendored (SpotFX's FastAPI app is the only web server).
Only fx.api.websocket exists, as an import-boundary stub for fx/effects/audio.py.
"""
