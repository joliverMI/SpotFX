"""The production hop he actually uses: browser -> :8000 (spot-effects'
reverse proxy, services/spectra_proxy.py, the REAL class) -> Spectra.
  python proxy_rig.py --port 9130 --target 9110
"""
import argparse, os, sys
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)
import uvicorn
from fastapi import FastAPI
from services.spectra_proxy import SpectraProxy

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=9130)
ap.add_argument("--target", type=int, default=9110)
a = ap.parse_args()
app = FastAPI()

@app.get("/rig/up")
async def up():
    return {"pid": os.getpid()}

app.mount("/spectra", SpectraProxy(a.target))
uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")
