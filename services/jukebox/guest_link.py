"""
SpotFX — the Jukebox's GUEST LINK (data/jukebox-plan/report.md §8.3, N1):
the public HTTPS address guests open on their phones —
`https://serenity.<tailnet>.ts.net:8443/?t=<party token>` — published by
Tailscale Funnel ONLY while a night runs, pointing at the guest app's port
(:8020, phase 2) and nothing else.

SHIPPED OFF. `GuestLinkConfig.enabled` is False until he turns it on, and
turning it on is only worth doing after G4 (allowing Funnel for Serenity in
his Tailscale admin console — his, never the agent's). While it is off a
night never runs `tailscale` at all: nothing here touches Tailscale, Funnel,
Serve, the router or any network setting. The commands below are the plan's
and have NOT been run against his Tailscale; the first real enable is a G4
step with him (tests replace the runner with one that fails loudly).

THREE THINGS IT KEEPS TRUE:
  * ONE PORT, ONE TARGET. The only command that publishes anything is
    `tailscale funnel --bg --https=<public_port> http://127.0.0.1:<guest_port>`;
    the guest port can never be :8000 or :8010 (the model refuses it), the
    target is loopback, and it names its own HTTPS port so his existing
    `tailscale serve` (another port) is left as it is. A public port Serve is
    already using is refused by name before anything is opened.
  * ON ONLY DURING A NIGHT. A night's start opens it, the night's end closes
    it (whoever ended it), switching the link off mid-night closes it at
    once, and a supervised check closes a Funnel this process opened when
    no night is running (a crash or restart left it behind). The durable
    state file says whether one is open, so a restart knows.
  * THE SELF-TEST (N1's: ":8000/:8010 are never reachable through it").
    With nothing open it checks the plan — what WOULD be published. With
    the link open it reads Funnel's own status back (only our port is
    published, and it proxies only to the guest port) and asks the public
    address for the master's and SPECTRA's own paths, which must not answer.

THE PARTY TOKEN is in every printed card (N2), so it is made when first
needed and lives through the night; it is replaced when a night that used
the link ends (the next party gets a fresh one), or by his Rotate press
between nights. `token_matches` is what the guest app (phase 2) will check
a phone's link against.

Every outcome is recorded (`last_action`, the night's own log line) and a
failure never stops the music: a link that would not open is a warning on a
night that plays on.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import secrets
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from models.jukebox import (FUNNEL_PORTS, MASTER_PORTS, GuestLinkAction, GuestLinkConfig,
                            GuestLinkState)
from services.jukebox import store

logger = logging.getLogger(__name__)

COMMAND_TIMEOUT_S = 20.0
PROBE_TIMEOUT_S = 8.0
RECONCILE_S = 60.0
# what the master and SPECTRA answer on; the guest app answers none of them
PROBE_PATHS: tuple[str, ...] = ("/api/jukebox/status", "/api/settings", "/spectra/",
                                "/spectra/api/engine/status")
CONFIG_KEYS = frozenset(GuestLinkConfig.model_fields)


# ── pure: the token, the link, the commands ──────────────────────────────────

def new_token() -> str:
    return secrets.token_urlsafe(16)


def token_matches(given: Any, st: GuestLinkState) -> bool:
    """A phone's `?t=` against tonight's token (constant-time)."""
    return bool(st.token) and isinstance(given, str) and hmac.compare_digest(given, st.token)


def link_for(host: str, port: int, token: str) -> Optional[str]:
    if not host or not token:
        return None
    return f"https://{host}{'' if port == 443 else f':{port}'}/?t={token}"


def target(cfg: GuestLinkConfig) -> str:
    return f"http://127.0.0.1:{cfg.guest_port}"


def open_argv(cfg: GuestLinkConfig) -> list[str]:
    return ["tailscale", "funnel", "--bg", f"--https={cfg.public_port}", target(cfg)]


def close_argv(cfg: GuestLinkConfig) -> list[str]:
    return ["tailscale", "funnel", f"--https={cfg.public_port}", "off"]


STATUS_ARGV = ["tailscale", "funnel", "status", "--json"]
HOST_ARGV = ["tailscale", "status", "--json"]


def apply_patch(current: GuestLinkConfig, patch: Any) -> GuestLinkConfig:
    """The ONE validator for the guest link's settings: a partial edit, an
    unknown key or a bad value refused by name (ValueError)."""
    if not isinstance(patch, dict):
        raise ValueError("expected a JSON object")
    unknown = sorted(set(patch) - CONFIG_KEYS)
    if unknown:
        raise ValueError(f"unknown guest link setting: {', '.join(unknown)}")
    try:
        return GuestLinkConfig.model_validate({**current.model_dump(), **patch})
    except Exception as exc:                                      # pydantic ValidationError
        errs = getattr(exc, "errors", None)
        if callable(errs):
            e = errs()[0]
            loc = ".".join(str(x) for x in e.get("loc", ()))
            raise ValueError(f"{loc}: {e.get('msg')}") from None
        raise ValueError(str(exc)) from None


def _port_of(hostport: str) -> Optional[int]:
    try:
        return int(str(hostport).rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return None


def _proxy_port(proxy: Any) -> Optional[int]:
    """The port a Serve/Funnel handler forwards to ("http://127.0.0.1:8020",
    "127.0.0.1:8020" or a bare "8020")."""
    s = str(proxy or "").strip()
    if not s:
        return None
    s = s.split("://", 1)[-1].split("/", 1)[0]
    try:
        return int(s.rsplit(":", 1)[-1])
    except ValueError:
        return None


def judge_config(cfg: GuestLinkConfig) -> list[dict]:
    """What the link WOULD publish, checked without asking Tailscale."""
    argv = open_argv(cfg)
    return [
        {"name": "one public port", "ok": cfg.public_port in FUNNEL_PORTS,
         "detail": f"the link is published on :{cfg.public_port}"},
        {"name": "never the master or SPECTRA", "ok": cfg.guest_port not in MASTER_PORTS,
         "detail": f"it forwards to the guest app on :{cfg.guest_port}, never "
                   + " or ".join(f":{p}" for p in MASTER_PORTS)},
        {"name": "loopback only", "ok": argv[-1] == f"http://127.0.0.1:{cfg.guest_port}",
         "detail": f"the published address forwards to {argv[-1]}"},
    ]


def judge_status(status: Any, cfg: GuestLinkConfig) -> list[dict]:
    """Funnel's own status read back (`tailscale funnel status --json`, the
    serve-config shape: Web{"host:port": {Handlers{path: {Proxy}}}},
    AllowFunnel{"host:port": true}). Only our port may be on the internet,
    and everything published must forward to the guest port alone."""
    if not isinstance(status, dict):
        return [{"name": "Funnel status read back", "ok": False,
                 "detail": "Tailscale's Funnel status could not be read"}]
    allowed = [hp for hp, on in (status.get("AllowFunnel") or {}).items() if on]
    web = status.get("Web") or {}
    checks: list[dict] = []
    ports = sorted({p for p in (_port_of(hp) for hp in allowed) if p is not None})
    checks.append({"name": "only the guest link is on the internet",
                   "ok": ports == [cfg.public_port],
                   "detail": ("published: " + ", ".join(f":{p}" for p in ports)) if ports
                   else "nothing is published"})
    bad: list[str] = []
    ours_ok = False
    for hp in allowed:
        handlers = ((web.get(hp) or {}).get("Handlers") or {})
        for path, h in handlers.items():
            port = _proxy_port((h or {}).get("Proxy"))
            if port != cfg.guest_port:
                bad.append(f"{hp}{path} → {(h or {}).get('Proxy') or 'not a proxy'}")
            elif _port_of(hp) == cfg.public_port:
                ours_ok = True
    checks.append({"name": "never the master or SPECTRA", "ok": not bad and ours_ok,
                   "detail": ("published paths that are not the guest app: " + "; ".join(bad))
                   if bad else (f"everything published forwards to :{cfg.guest_port}" if ours_ok
                                else f"nothing published forwards to :{cfg.guest_port}")})
    return checks


def serve_conflict(status: Any, cfg: GuestLinkConfig) -> Optional[str]:
    """Something not ours already on the public port (his `tailscale serve`
    keeps its own port; this never takes one over)."""
    if not isinstance(status, dict):
        return None
    for hp, conf in (status.get("Web") or {}).items():
        if _port_of(hp) != cfg.public_port:
            continue
        for h in ((conf or {}).get("Handlers") or {}).values():
            if _proxy_port((h or {}).get("Proxy")) != cfg.guest_port:
                return (f":{cfg.public_port} is already used by something else on Serenity "
                        f"({(h or {}).get('Proxy') or 'not a proxy'}); the guest link won't take "
                        "it over — choose another public port (443 or 10000)")
    return None


def port_published(status: Any, port: int) -> bool:
    """Whether Funnel's own status (`judge_status`'s shape) shows anything
    at all published on `port` — used to tell "a crash left the marker set
    but nothing ever went out" from "it really is still open"."""
    if not isinstance(status, dict):
        return True   # couldn't be read: assume it might still be published
    allowed = (status.get("AllowFunnel") or {})
    if any(_port_of(hp) == port for hp, on in allowed.items() if on):
        return True
    web = (status.get("Web") or {})
    return any(_port_of(hp) == port for hp in web)


def judge_probe(results: dict[str, Optional[int]]) -> dict:
    """The public address asked for the master's and SPECTRA's own paths:
    none may answer 200 (the guest app answers only its own routes)."""
    reached = [p for p, code in results.items() if code is not None and 200 <= code < 300]
    unread = [p for p, code in results.items() if code is None]
    return {"name": "the master and SPECTRA can't be reached through it", "ok": not reached and not unread,
            "detail": ("ANSWERED: " + ", ".join(reached)) if reached else
            ("could not be asked: " + ", ".join(unread)) if unread else
            "every master and SPECTRA path was refused"}


# ── the effects (injectable; tests never run tailscale) ──────────────────────

def run_command(argv: list[str], timeout: float) -> tuple[int, str, str]:
    """Run one `tailscale` command (blocking; called off the loop)."""
    p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)  # noqa: S603
    return p.returncode, p.stdout, p.stderr


def _probe(url: str, timeout: float) -> Optional[int]:
    try:
        import httpx
        r = httpx.get(url, timeout=timeout, follow_redirects=False)
        return r.status_code
    except Exception:                                             # noqa: BLE001
        return None


@dataclass
class GuestLinkDeps:
    run: Callable[[list[str], float], tuple[int, str, str]] = field(
        default_factory=lambda: (lambda argv, timeout: run_command(argv, timeout)))
    probe: Callable[[str, float], Optional[int]] = _probe
    to_thread: Callable[..., Awaitable[Any]] = asyncio.to_thread
    now_ms: Callable[[], int] = lambda: int(time.time() * 1000)
    night_running: Callable[[], bool] = lambda: _night_running()


def _night_running() -> bool:
    from services.jukebox import night
    return bool(night.runner.running)


class GuestLink:
    def __init__(self, deps: Optional[GuestLinkDeps] = None) -> None:
        self.deps = deps or GuestLinkDeps()
        self._lock: Optional[asyncio.Lock] = None

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    # ── reads ───────────────────────────────────────────────────────────────

    def status(self) -> dict:
        cfg, st = store.load_guest_link()
        state = ("live" if st.funnel_open else "error" if (st.last_action and not st.last_action.ok
                                                          and cfg.enabled) else
                 "armed" if cfg.enabled else "off")
        host = st.host or cfg.public_host
        return {"config": cfg.model_dump(mode="json"), "state": state,
                "funnel_open": st.funnel_open, "opened_ms": st.opened_ms,
                "opened_for_night": st.opened_for_night or None,
                "link": link_for(host, cfg.public_port, st.token),
                "host": host or None, "token_created_ms": st.token_created_ms,
                "open_command": " ".join(open_argv(cfg)), "close_command": " ".join(close_argv(cfg)),
                "last_action": st.last_action.model_dump(mode="json") if st.last_action else None,
                "self_test": st.self_test,
                "summary": self._summary(state, cfg, st, host)}

    @staticmethod
    def _summary(state: str, cfg: GuestLinkConfig, st: GuestLinkState, host: str) -> str:
        if state == "off":
            return "The guest link is off: a night never publishes anything."
        if state == "live":
            return (f"The guest link is live on {host}:{cfg.public_port}, forwarding only to "
                    f"the guest app on :{cfg.guest_port}.")
        if state == "error":
            return f"The guest link is on but its last step failed: {st.last_action.detail}"
        return (f"The guest link is on: the next night publishes :{cfg.public_port} → the guest "
                f"app on :{cfg.guest_port}, and closes it when the night ends.")

    # ── the settings ────────────────────────────────────────────────────────

    async def edit(self, patch: Any, dry_run: bool = False) -> dict:
        """A partial settings edit through the ONE validator. Switching the
        link off while a Funnel this process opened is open closes it now;
        switching it on takes effect at the next night's start."""
        async with self._get_lock():
            cfg, st = store.load_guest_link()
            new = apply_patch(cfg, patch)
            if st.funnel_open and (new.public_port != cfg.public_port
                                   or new.guest_port != cfg.guest_port):
                raise ValueError("the link is live: its ports can't change until the night ends")
            if dry_run:
                return {"dry_run": True, "config": new.model_dump(mode="json")}
            store.save_guest_link(new, st)
            if st.funnel_open and not new.enabled:
                await self._close_locked("switched off")
        return {"dry_run": False, **self.status()}

    async def rotate(self) -> dict:
        """A fresh party token. Refused while a night runs: tonight's printed
        cards carry the current one."""
        async with self._get_lock():
            if self.deps.night_running():
                return {"status": "refused", "reason": "night_running",
                        "detail": "A night is running and tonight's cards carry this link; "
                                  "rotate it after the night ends."}
            cfg, st = store.load_guest_link()
            st.token, st.token_created_ms = new_token(), self.deps.now_ms()
            store.save_guest_link(cfg, st)
        return {"status": "rotated", **self.status()}

    def ensure_token(self) -> None:
        cfg, st = store.load_guest_link()
        if not st.token:
            st.token, st.token_created_ms = new_token(), self.deps.now_ms()
            store.save_guest_link(cfg, st)

    # ── the night's hooks (services/jukebox/night.py) ───────────────────────

    async def on_night_start(self, night_id: str) -> Optional[tuple[bool, str]]:
        """Open the link for this night when it is switched on. Returns
        (live, the sentence for the night's log), or None when the link is
        off (nothing was run). Never raises."""
        try:
            async with self._get_lock():
                cfg, st = store.load_guest_link()
                if not cfg.enabled:
                    return None
                said = await self._open_locked(cfg, st, night_id)
                return store.load_guest_link()[1].funnel_open, said
        except Exception as exc:                                  # noqa: BLE001
            logger.exception("Jukebox guest link: opening failed")
            return False, f"the guest link couldn't open ({type(exc).__name__}: {exc})"

    async def on_night_end(self, night_id: str) -> Optional[tuple[bool, str]]:
        """Close what this process opened (whoever ended the night) and give
        the next party a fresh token. Returns (closed, the sentence), or None
        when nothing was open. Never raises."""
        try:
            async with self._get_lock():
                cfg, st = store.load_guest_link()
                said = None
                if st.funnel_open:
                    said = await self._close_locked("the night ended")
                    cfg, st = store.load_guest_link()
                if st.opened_for_night == night_id:      # this night used the link
                    st.token, st.token_created_ms = new_token(), self.deps.now_ms()
                    st.opened_for_night = ""
                    store.save_guest_link(cfg, st)
                return None if said is None else (not st.funnel_open, said)
        except Exception as exc:                                  # noqa: BLE001
            logger.exception("Jukebox guest link: closing failed")
            return False, f"the guest link couldn't close ({type(exc).__name__}: {exc})"

    async def reconcile(self) -> Optional[str]:
        """A Funnel this process opened, still open with no night running
        (a crash or restart between the two), is closed."""
        async with self._get_lock():
            _, st = store.load_guest_link()
            if st.funnel_open and not self.deps.night_running():
                return await self._close_locked("no night is running")
        return None

    async def run_supervised(self) -> None:
        while True:
            try:
                said = await self.reconcile()
                if said:
                    logger.warning("Jukebox guest link: %s", said)
            except asyncio.CancelledError:
                raise
            except Exception:                                     # noqa: BLE001
                logger.exception("Jukebox guest link: reconcile failed")
            await asyncio.sleep(RECONCILE_S)

    # ── the self-test ───────────────────────────────────────────────────────

    async def self_test(self) -> dict:
        """With nothing open, the plan alone (no Tailscale call). With the
        link live, Funnel's own status and the public address too."""
        async with self._get_lock():
            cfg, st = store.load_guest_link()
            checks = judge_config(cfg)
            mode = "planned"
            if st.funnel_open:
                mode = "live"
                status, _ = await self._status(cfg)
                checks += judge_status(status, cfg)
                host = st.host or cfg.public_host
                base = f"https://{host}{'' if cfg.public_port == 443 else f':{cfg.public_port}'}"
                results = {}
                for path in PROBE_PATHS:
                    results[path] = await self.deps.to_thread(self.deps.probe, base + path,
                                                              PROBE_TIMEOUT_S)
                checks.append(judge_probe(results))
            result = {"mode": mode, "ok": all(c["ok"] for c in checks), "checks": checks,
                      "at_ms": self.deps.now_ms()}
            st.self_test = result
            store.save_guest_link(cfg, st)
            return result

    # ── inside the lock ─────────────────────────────────────────────────────

    async def _run(self, argv: list[str]) -> tuple[int, str, str]:
        return await self.deps.to_thread(self.deps.run, argv, COMMAND_TIMEOUT_S)

    async def _status(self, cfg: GuestLinkConfig) -> tuple[Optional[dict], str]:
        try:
            rc, out, err = await self._run(STATUS_ARGV)
        except Exception as exc:                                  # noqa: BLE001
            return None, f"{type(exc).__name__}: {exc}"
        if rc != 0:
            return None, (err or out or f"exit {rc}").strip()
        try:
            data = json.loads(out or "{}")
        except ValueError:
            return None, "Tailscale's Funnel status was not JSON"
        return (data if isinstance(data, dict) else {}), ""

    async def _host(self, cfg: GuestLinkConfig) -> tuple[str, str]:
        if cfg.public_host:
            return cfg.public_host, ""
        try:
            rc, out, err = await self._run(HOST_ARGV)
            if rc != 0:
                return "", (err or out or f"exit {rc}").strip()
            name = ((json.loads(out or "{}").get("Self") or {}).get("DNSName") or "").rstrip(".")
            return name.lower(), "" if name else "Tailscale reported no name for Serenity"
        except Exception as exc:                                  # noqa: BLE001
            return "", f"{type(exc).__name__}: {exc}"

    def _record(self, cfg: GuestLinkConfig, st: GuestLinkState, what: str, ok: bool,
                detail: str) -> str:
        st.last_action = GuestLinkAction(what=what, ok=ok, detail=detail, at_ms=self.deps.now_ms())
        store.save_guest_link(cfg, st)
        (logger.info if ok else logger.warning)("Jukebox guest link: %s", detail)
        return detail

    async def _open_locked(self, cfg: GuestLinkConfig, st: GuestLinkState, night_id: str) -> str:
        if not st.token:
            st.token, st.token_created_ms = new_token(), self.deps.now_ms()
        if not all(c["ok"] for c in judge_config(cfg)):
            return self._record(cfg, st, "open", False, "the guest link's settings failed its "
                                "own check, so nothing was published")
        host, why = await self._host(cfg)
        if not host:
            return self._record(cfg, st, "host", False,
                                f"the guest link didn't open: Serenity's public name is unknown ({why})")
        before, why = await self._status(cfg)
        if before is None:
            return self._record(cfg, st, "status", False,
                                f"the guest link didn't open: Funnel's status couldn't be read ({why})")
        conflict = serve_conflict(before, cfg)
        if conflict:
            return self._record(cfg, st, "open", False, f"the guest link didn't open: {conflict}")
        st.funnel_open, st.opened_ms, st.opened_for_night, st.host = (
            True, self.deps.now_ms(), night_id, host)
        store.save_guest_link(cfg, st)
        try:
            rc, out, err = await self._run(open_argv(cfg))
        except Exception as exc:                                  # noqa: BLE001
            rc, out, err = -1, "", f"{type(exc).__name__}: {exc}"
        if rc != 0:
            st.funnel_open, st.opened_ms, st.opened_for_night = False, None, ""
            return self._record(cfg, st, "open", False,
                                f"the guest link didn't open: {(err or out or f'exit {rc}').strip()}")
        after, _ = await self._status(cfg)
        checks = judge_status(after, cfg)
        if not all(c["ok"] for c in checks):
            self._record(cfg, st, "open", False, "published, but the read-back failed: "
                         + "; ".join(c["detail"] for c in checks if not c["ok"]))
            await self._close_locked("its read-back failed")
            return "the guest link opened but failed its check, so it was closed again"
        return self._record(cfg, st, "open", True,
                            f"guest link live: {link_for(host, cfg.public_port, st.token)}")

    async def _close_locked(self, why: str) -> str:
        cfg, st = store.load_guest_link()
        try:
            rc, out, err = await self._run(close_argv(cfg))
        except Exception as exc:                                  # noqa: BLE001
            rc, out, err = -1, "", f"{type(exc).__name__}: {exc}"
        if rc != 0:
            status, _ = await self._status(cfg)
            if status is not None and not port_published(status, cfg.public_port):
                st.funnel_open = False
                st.opened_ms = None
                return self._record(cfg, st, "close", True,
                                    f"guest link closed ({why}): nothing was published")
            # left marked open: the supervised check tries again
            return self._record(cfg, st, "close", False,
                                f"the guest link couldn't close ({why}): "
                                f"{(err or out or f'exit {rc}').strip()}")
        st.funnel_open = False
        st.opened_ms = None
        return self._record(cfg, st, "close", True, f"guest link closed ({why})")


controller = GuestLink()
