"""`python -m jukebox_guest [--host 127.0.0.1] [--port 8020] [--spotfx URL]`"""
from __future__ import annotations

import argparse
import logging
import sys

MASTER_PORTS = (8000, 8010)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="jukebox_guest", description="The Jukebox's guest page.")
    ap.add_argument("--host", default="127.0.0.1",
                    help="where to listen (default loopback: Tailscale Funnel reaches it there)")
    ap.add_argument("--port", type=int, default=8020)
    ap.add_argument("--spotfx", default="http://127.0.0.1:8000", help="SpotFX's address")
    args = ap.parse_args(argv)
    if args.port in MASTER_PORTS:
        print(f"refusing :{args.port}: that is the master's or SPECTRA's port", file=sys.stderr)
        return 2
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    import uvicorn

    from jukebox_guest.app import create_app
    # access_log off: the page's own address carries the party token
    uvicorn.run(create_app(spotfx_url=args.spotfx), host=args.host, port=args.port,
                access_log=False, server_header=False, proxy_headers=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
