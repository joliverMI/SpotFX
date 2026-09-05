#!/usr/bin/env python3
"""HIS 2026-09-04 FAILURE, REPRODUCED AND THEN FIXED — with one variable
changed and everything else held.

The night: `sconce-kitchen-left` was pinned `192.168.40.112`, the fixture
had taken a new lease and was answering at `192.168.40.110`, and the room
had no way to tell that from a dead light. This drives the REAL production
chain — `fx.devices.wled.WLEDDevice.async_initialize` -> `reconcile_address`
-> `fx.device_identity.locate` -> `spectra.services.device_relocation.
persist` — against REAL HTTP servers on loopback, never his network.

Run:  .venv/bin/python scripts/check_device_relocation.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import device_identity as ident            # noqa: E402
from fx.devices import wled as wled_module         # noqa: E402
from fx.devices.wled import WLEDDevice             # noqa: E402
from spectra.services import device_relocation     # noqa: E402

#: His own left sconce, from the backlog card.
MAC = "e0:8c:fe:5c:3a:78"
#: TEST-NET-3 (RFC 5737) standing in for his 192.168.40.112 — the stale pin.
STALE_PIN = "203.0.113.112"

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}"
          + (f"  — {detail}" if detail else ""), flush=True)
    if not ok:
        failures.append(label)


class RealWled:
    """A real HTTP socket speaking real WLED JSON."""

    def __init__(self, mac: str):
        self.info = {"brand": "WLED", "ver": "0.15.4",
                     "name": "Sconce, Kitchen, Left",
                     "mac": ident.normalize_mac(mac), "vid": 2405180,
                     "live": False, "leds": {"count": 88, "rgbw": False}}
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path.endswith("/json/info"):
                    raw = json.dumps(outer.info).encode()
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    return self.wfile.write(raw)
                if self.path.endswith("/json/cfg"):
                    raw = b"{}"
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    return self.wfile.write(raw)
                self.send_response(404)
                self.end_headers()

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.address = f"127.0.0.1:{self._server.server_address[1]}"
        threading.Thread(target=self._server.serve_forever,
                         daemon=True).start()

    def stop(self):
        self._server.shutdown()
        self._server.server_close()


class FakeLedfx:
    thread_executor = None

    @property
    def loop(self):
        return asyncio.get_running_loop()


class FakeHost:
    def __init__(self, config_dir, devices, entries):
        self.devices = {d.id: d for d in devices}
        self.config_dir = config_dir
        self.config = {"devices": entries, "virtuals": []}


def build_device(hardware_id: str | None, actual_address: str):
    """A device pinned at the stale address, with a resolver that knows
    where the fixture really is — exactly his network's state that night."""
    config = {"name": "sconce-kitchen-left", "ip_address": STALE_PIN,
              "pixel_count": 88, "sync_mode": "DDP", "refresh_rate": 60,
              "icon_name": "wled", "center_offset": 0, "timeout": 1,
              "create_segments": False}
    if hardware_id:
        config["hardware_id"] = hardware_id
    device = WLEDDevice(FakeLedfx(), config)
    device._destination = STALE_PIN

    async def resolve_host(hostname):
        # what avahi answers on his host: the derived mDNS name -> the
        # fixture's CURRENT address
        return actual_address if hostname == ident.mdns_name_for_mac(MAC) \
            else None

    device._resolve_host = resolve_host
    return device


def main() -> int:
    # The fork's `resolve_destination` returns a literal IP verbatim and
    # otherwise calls gethostbyname — it cannot parse `host:port`, which is
    # how a loopback fixture has to be addressed. Standing in the
    # verbatim-passthrough it already performs for every real bare IP keeps
    # this harness honest AND keeps it off the network.
    import fx.devices as devices_module

    async def passthrough(loop, executor, destination):
        return destination

    devices_module.resolve_destination = passthrough

    fixture = RealWled(MAC)
    print(f"\nA real WLED is listening at {fixture.address}; the config says "
          f"{STALE_PIN}.\n")
    try:
        print("1. TODAY'S BEHAVIOUR — pinned by address only")
        pinned_only = build_device(None, fixture.address)
        try:
            asyncio.run(pinned_only.async_initialize())
            check("a stale pin fails to come up", False,
                  "it came up, which this check does not expect")
        except Exception as exc:
            check("a stale pin fails to come up", "Failed to connect" in str(exc),
                  str(exc))
        check("and nothing moved", pinned_only._config["ip_address"] == STALE_PIN,
              pinned_only._config["ip_address"])

        print("\n2. WITH AN IDENTITY — the same start, one field added")
        by_identity = build_device(MAC, fixture.address)
        asyncio.run(by_identity.async_initialize())
        check("the device is re-found and driven",
              by_identity._config["ip_address"] == fixture.address,
              f"{STALE_PIN} -> {by_identity._config['ip_address']}")
        check("the JSON client follows",
              by_identity.wled.ip_address == fixture.address)
        check("the streaming subdevice follows",
              by_identity.subdevice._destination == fixture.address)
        check("its real pixel count was read off the fixture",
              by_identity._config["pixel_count"] == 88)

        print("\n3. A HEALTHY PIN IS UNTOUCHED — the byte-identical path")
        healthy = build_device(MAC, fixture.address)
        healthy._config["ip_address"] = fixture.address
        healthy._destination = fixture.address
        before = dict(healthy._config)
        location = asyncio.run(healthy.reconcile_address())
        check("confirmed at the address it already had",
              location is not None and not location.moved and
              location.via == "pinned")
        check("and its config is unchanged", healthy._config == before)

        print("\n4. LEARNED WITHOUT BEING TOLD — a device that answers once")
        learner = build_device(None, fixture.address)
        learner._config["ip_address"] = fixture.address
        learner._destination = fixture.address
        asyncio.run(learner.async_initialize())
        check("the MAC is learned off json/info",
              learner.hardware_id == ident.normalize_mac(MAC),
              str(learner.hardware_id))

        print("\n5. AND REMEMBERED — so the restart after the lease changes "
              "can still find it")
        with tempfile.TemporaryDirectory() as config_dir:
            entries = [{"id": "sconce-kitchen-left", "type": "wled",
                        "config": {"ip_address": STALE_PIN,
                                   "name": "sconce-kitchen-left",
                                   "sync_mode": "DDP"}},
                       {"id": "hue-lights", "type": "hue",
                        "config": {"ip_address": "203.0.113.215",
                                   "name": "hue"}}]
            untouched = json.loads(json.dumps(entries[1]))
            learner._id = "sconce-kitchen-left"
            host = FakeHost(config_dir, [learner], entries)
            changed = device_relocation.persist(host, learner)
            stored = json.loads(
                (Path(config_dir) / "config.json").read_text())["devices"]
            check("only the device that changed was written",
                  changed == ["sconce-kitchen-left"], str(changed))
            check("its identity is on disk",
                  stored[0]["config"].get("hardware_id")
                  == ident.normalize_mac(MAC))
            check("its other keys survived",
                  stored[0]["config"].get("sync_mode") == "DDP")
            check("every other device is byte-identical",
                  stored[1] == untouched)
    finally:
        fixture.stop()

    print("\n" + ("ALL CHECKS PASSED" if not failures
                  else f"FAILED: {failures}"), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        status = main()
    except Exception:
        import traceback
        traceback.print_exc()
        status = 1
    os._exit(status)
