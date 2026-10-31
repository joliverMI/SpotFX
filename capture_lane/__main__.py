"""`python -m capture_lane [--port 8030]` — always on loopback."""
from __future__ import annotations

import argparse
import logging
import sys

TAKEN_PORTS = (8000, 8010, 8020)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="capture_lane",
                                 description="Learns songs on the hidden player, inaudibly.")
    ap.add_argument("--port", type=int, default=None, help="default: settings.capture_lane_port")
    args = ap.parse_args(argv)
    from config import settings
    port = args.port or settings.capture_lane_port
    if port in TAKEN_PORTS:
        print(f"refusing :{port}: SpotFX, SPECTRA or the guest app uses it", file=sys.stderr)
        return 2
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    import uvicorn

    from capture_lane.app import create_app
    uvicorn.run(create_app(), host="127.0.0.1", port=port, access_log=False, server_header=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
