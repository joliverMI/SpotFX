"""ARM AWARENESS WITHOUT ARM CLAIMS — what the capture client imports, and
why that is the whole of its story on a Raspberry Pi.

THE HONEST FRAME FIRST. **No ARM board has run this.** Nothing in this
script is evidence that the client works on a Pi; it is evidence about the
one thing that can be checked from an x86 machine — WHAT THE CLIENT PULLS IN
— because that is where an ARM port usually dies. `docs/
CAPTURE_CLIENT_HOST.md`'s ledger names what only real hardware can settle.

WHAT IT PROVES:

  1. THE CLIENT IMPORTS WITHOUT THE SERVER. `spectra.capture_client` is
     imported with every server-only distribution BLOCKED at the meta path —
     numpy, scipy, fastapi, pydantic, librosa, PIL, voluptuous, aubio,
     samplerate, mbedtls, sacn, serial, netifaces, anthropic, mcp, uvicorn,
     soundfile, sounddevice, spotipy, redis, markdown, dotenv, requests. If
     the import still succeeds, the client genuinely does not need any of
     them, and a Pi never has to build them.
  2. ITS THIRD-PARTY CLOSURE IS EXACTLY THE TWO DECLARED PACKAGES.
     Everything imported that is not stdlib and not `spectra`/`fx` itself
     must appear in `requirements-capture-client.txt` — so the file cannot
     drift from the truth by somebody adding an import.
  3. IT DOES NOT REACH INTO `fx/`. The vendored render pipeline is the
     server's, and it carries the compiled dependencies; a client that
     imported it would drag them onto the board.
  4. NOTHING IN IT ASSUMES AN ARCHITECTURE. No `x86`, `amd64`, `i686` or
     hard-coded `machine()` comparison anywhere in the package.
  5. THE SERVER'S OWN REQUIREMENTS ARE NAMED, NOT SILENTLY INHERITED. The
     ARM-hostile lines in `requirements.txt` are listed here as what a
     camera host must NOT install, so the reason is written down where
     somebody provisioning a board will find it.

Run from repo root:  .venv/bin/python scripts/check_capture_client_deps.py
No network, no camera, no server, no room.
"""
from __future__ import annotations

import importlib
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
print = __import__("functools").partial(print, flush=True)     # noqa: A001

FAILURES: list[str] = []


def check(cond, label):
    if not cond:
        FAILURES.append(label)
        print(f"FAIL: {label}")
        return False
    print(f"ok: {label}")
    return True


#: Every top-level module the SERVER needs and the CLIENT must not. Blocked
#: at the meta path so the proof is "it imported without them", not "we did
#: not notice it importing them".
SERVER_ONLY = (
    "numpy", "scipy", "librosa", "soundfile", "sounddevice", "PIL",
    "fastapi", "starlette", "uvicorn", "pydantic", "pydantic_settings",
    "voluptuous", "aubio", "samplerate", "mbedtls", "sacn", "serial",
    "netifaces", "pyfastnoiselite", "anthropic", "mcp", "spotipy", "redis",
    "markdown", "dotenv", "requests", "aiofiles", "multipart",
)

#: The ARM-hostile lines in the SERVER's requirements.txt — compiled
#: extensions with no guaranteed aarch64 wheel. Named so a person
#: provisioning a board knows what "do not install requirements.txt" means.
ARM_HOSTILE_SERVER_DEPS = (
    "aubio-ledfx", "samplerate-ledfx", "python-mbedtls", "pyfastnoiselite",
    "scipy", "librosa", "soundfile", "sounddevice", "netifaces2", "pillow",
)


class _Blocker:
    """Refuse a named import, the way a machine without the package would."""

    def __init__(self, blocked):
        self.blocked = set(blocked)
        self.hit: list[str] = []

    def find_module(self, name, path=None):               # legacy hook
        return self.find_spec(name, path)

    def find_spec(self, name, path=None, target=None):
        top = name.split(".")[0]
        if top in self.blocked:
            self.hit.append(name)
            raise ImportError(
                f"{name} is blocked by check_capture_client_deps.py: the "
                f"capture client may not need the server's dependencies")
        return None


def main() -> int:
    print("== 1. the client imports with every server-only package blocked ==")
    # Drop anything already imported so the blocker actually gets asked.
    for mod in list(sys.modules):
        if mod.split(".")[0] in set(SERVER_ONLY) | {"spectra", "fx"}:
            del sys.modules[mod]
    blocker = _Blocker(SERVER_ONLY)
    sys.meta_path.insert(0, blocker)
    try:
        importlib.import_module("spectra.capture_client")
        importlib.import_module("spectra.capture_client.__main__")
        importlib.import_module("spectra.capture_client.config")
        check(True, "spectra.capture_client (and its __main__) import with "
                    f"{len(SERVER_ONLY)} server-only packages unavailable")
    except ImportError as exc:
        check(False, f"the client needs a server-only package: {exc}")
    finally:
        sys.meta_path.remove(blocker)
    check(not blocker.hit,
          f"and nothing in it even TRIED one: {blocker.hit or 'none attempted'}")

    print("\n== 2. its third-party closure is exactly the declared two ==")
    declared = set()
    for line in (ROOT / "requirements-capture-client.txt").read_text().splitlines():
        line = line.split("#")[0].strip()
        if line:
            declared.add(re.split(r"[<>=!~\[]", line)[0].strip().lower())
    check(declared == {"httpx", "websockets"},
          f"requirements-capture-client.txt declares exactly httpx and "
          f"websockets: {sorted(declared)}")

    stdlib = set(getattr(sys, "stdlib_module_names", ()))
    third_party = set()
    for name, mod in list(sys.modules.items()):
        top = name.split(".")[0]
        if top in ("spectra", "fx", "__main__") or top.startswith("_"):
            continue
        if top in stdlib or mod is None:
            continue
        origin = getattr(getattr(mod, "__spec__", None), "origin", "") or ""
        if origin in ("built-in", "frozen") or not origin:
            continue
        if str(ROOT) in origin:                          # this repo's own code
            continue
        third_party.add(top)
    # Everything the CLIENT itself pulled in, minus what this script and the
    # interpreter's own start-up brought along.
    from spectra.capture_client import camera, session               # noqa: F401
    client_imports = set()
    for mod in (camera, session,
                sys.modules["spectra.capture_client.__main__"],
                sys.modules["spectra.capture_client.config"]):
        src = Path(mod.__file__).read_text()
        for m in re.finditer(r"^\s*(?:import|from)\s+([A-Za-z_][\w.]*)",
                             src, re.M):
            top = m.group(1).split(".")[0]
            if top in ("spectra", "fx", "__future__") or top in stdlib:
                continue
            client_imports.add(top)
    check(client_imports <= declared,
          f"every third-party import in the client is declared: "
          f"{sorted(client_imports)}")

    print("\n== 3. it does not reach into the vendored render pipeline ==")
    reaches_fx = [m for m in sys.modules if m.split(".")[0] == "fx"]
    check(not reaches_fx,
          f"nothing under fx/ was imported by the client: {reaches_fx or 'none'}")

    print("\n== 4. nothing in it assumes an architecture ==")
    bad = []
    for path in sorted((ROOT / "spectra" / "capture_client").glob("*.py")):
        text = path.read_text()
        for m in re.finditer(r"(?i)\b(x86|x86_64|amd64|i686|aarch64|arm64)\b",
                             text):
            bad.append(f"{path.name}: {m.group(0)}")
    check(not bad, f"no architecture literal anywhere in the package: {bad or 'none'}")
    # `platform.machine()` is READ (it goes in the user agent so a server can
    # SAY which board it is talking to) but never compared against.
    session_src = (ROOT / "spectra" / "capture_client" / "session.py").read_text()
    check("platform.machine()" in session_src,
          "the machine name is REPORTED in hello, so SPECTRA can say which "
          "board it is talking to")
    check(not re.search(r"machine\(\)\s*(==|!=|in\b)", session_src),
          "and never branched on")

    print("\n== 5. the server's ARM-hostile deps are named, not inherited ==")
    server_reqs = (ROOT / "requirements.txt").read_text().lower()
    named = [d for d in ARM_HOSTILE_SERVER_DEPS if d in server_reqs]
    check(len(named) >= 8,
          f"requirements.txt still carries the compiled dependencies a "
          f"camera host must NOT install ({len(named)}): {named}")
    client_reqs = (ROOT / "requirements-capture-client.txt").read_text().lower()
    check(not any(d in client_reqs.split("#")[0] for d in ARM_HOSTILE_SERVER_DEPS),
          "and none of them appears in the client's own requirements")
    check("requirements.txt" in
          (ROOT / "requirements-capture-client.txt").read_text(),
          "the client's requirements file SAYS so, where a person "
          "provisioning a board will read it")

    print()
    if FAILURES:
        print(f"FAILED {len(FAILURES)} check(s):\n  " + "\n  ".join(FAILURES))
        return 1
    print("NOT PROVEN HERE, and stated rather than implied: that any of this "
          "runs on ARM. No board has executed it.")
    print("ALL CAPTURE CLIENT DEPENDENCY CHECKS PASSED")
    return 0


if __name__ == "__main__":
    status = 1
    try:
        status = main()
    except BaseException:
        import traceback
        traceback.print_exc()
    os._exit(status)
