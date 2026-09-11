"""WHO ASKED — naming the caller of the one route that moves his room.

Twice in two days (2026-09-09 18:10:31 and 2026-09-10 19:59:45) an
unannounced take moved his lights, and both times the origin could only be
INFERRED, because nothing recorded who asked. This module is the record for
`POST /spectra/api/ownership/handover` — the single surface that decides who
drives his house.

READ THIS BEFORE CHANGING THE LOOKUP; IT IS THE WHOLE POINT OF THE MODULE.
River built the same capture on her own endpoint and it resolved THE WRONG
SIDE: it printed the pid and cmdline of her OWN listening process, so every
entry named herself and identified nobody. The resolution here is anchored
on the CLIENT end of the socket and is structurally incapable of that
mistake, because the two ends of one connection are MIRRORS::

    the server's own socket:   local = (server_ip, server_port)
                               rem   = (peer_ip,   peer_port)
    the CALLER's own socket:   local = (peer_ip,   peer_port)
                               rem   = (server_ip, server_port)

`find_socket_inode` matches the CALLER's tuple — local == the peer, rem ==
the server — so the only row it can ever match is the caller's. Naming the
server would require finding a socket whose LOCAL address is the peer's,
which the listening socket never has. `tests/test_handover_caller_logging.py`
asserts that directly: a request made by a known child process must report
THAT child's pid, and must NOT report this process's own.

THREE THINGS THAT ARE NOT NEGOTIABLE HERE:

- **BEST EFFORT, NEVER FATAL.** Nothing in this module raises at its public
  edge. A missing /proc, a permission error, a socket that closed mid-lookup,
  a process table storm — every one of them produces a STATED reason and a
  handover that is completely unaffected. The room moving is the important
  thing; naming who moved it is not worth breaking.
- **A REMOTE CALLER IS SAID TO BE UNRESOLVABLE, NEVER GUESSED.** A caller on
  another machine has no pid on this host. Printing a local pid anyway is
  River's failure mode arriving through the other door, so `describe` reports
  the peer and the User-Agent and says plainly that the process is not
  resolvable from here.
- **NO SECRETS.** Headers are read from an explicit ALLOWLIST
  (`SAFE_HEADERS`) — never a loop over what arrived — so an `Authorization`
  header cannot reach a log line by accident. The caller's command line is
  the deliverable and is logged, but `redact` masks the obvious
  secret-bearing shapes inside it first (a `curl -H 'Authorization: …'` press
  of this route would otherwise put a token in the log the long way round).

It reads /proc and logs. It changes no ownership behaviour, no timing and
nothing on disk.
"""
from __future__ import annotations

import asyncio
import ipaddress
import os
import re
import sys
import threading
import time
from dataclasses import dataclass
from typing import Iterable, Iterator, Optional, Tuple

#: Hard wall budget for the whole /proc lookup, checked BETWEEN processes so
#: the scan gives up honestly rather than being abandoned mid-flight.
#: MEASURED on his host, not tuned: reading /proc/net/tcp + tcp6 costs ~3 ms,
#: and a FULL scan of every readable /proc/<pid>/fd (477 processes, ~6000
#: descriptors, no early exit) ~18 ms — so this is ~25x headroom. It exists
#: only so a pathological /proc cannot sit in front of a take.
LOOKUP_BUDGET_S = 0.5

#: The outer await's ceiling. Larger than the in-thread budget on purpose:
#: the thread's own deadline should be what ends a slow scan, so the log line
#: carries a real reason instead of a bare "timed out".
AWAIT_BUDGET_S = LOOKUP_BUDGET_S + 0.25

#: The command line is the deliverable, so it is logged whole — up to here.
#: A longer one is truncated and SAYS it was.
CMDLINE_MAX = 600

#: The only request headers this module will ever read. An allowlist, never a
#: filter over what arrived: `Authorization` and every future secret-bearing
#: header is excluded by not being here, rather than by being remembered.
SAFE_HEADERS = ("user-agent", "x-forwarded-for")

_PROC_NET = ("/proc/net/tcp", "/proc/net/tcp6")

#: Conservative masks for the secret shapes a command line actually carries.
#: Deliberately narrow — over-redacting the cmdline would blunt the one field
#: this whole module exists to produce.
#: The `authorization` value runs to the end of its ARGUMENT, not to the next
#: space: `-H 'Authorization: Bearer <token>'` is TWO words inside ONE argv
#: element, and masking only the first word leaves the token sitting in the
#: log (measured — that is what the first version of this did). `redact_argv`
#: is what makes that safe to be greedy about: it redacts each argv element
#: separately, so a masked `-H` argument cannot swallow the `-d` payload
#: after it.
_SECRET_RE = (
    re.compile(r"""(?i)(authorization\s*[:=]\s*)[^'"]*"""),
    re.compile(r"(?i)\b(bearer\s+)\S+"),
    re.compile(
        r"(?i)((?:--?)?(?:token|password|passwd|secret|api[-_]?key|apikey|"
        r"auth[-_]?token)\s*[=:\s]\s*)\S+"),
)
_REDACTED = "<redacted>"


def redact(text: str) -> str:
    """Mask the obvious secret-bearing shapes in one string."""
    for pattern in _SECRET_RE:
        text = pattern.sub(lambda m: m.group(1) + _REDACTED, text)
    return text


def redact_argv(parts: Iterable[str]) -> str:
    """Redact each ARGV ELEMENT, then join — never the joined string.

    A command line arrives NUL-separated, so the argument boundaries are
    known exactly here and are thrown away by the join. Redacting first is
    what lets `_SECRET_RE` run to the end of a value without eating the
    arguments that follow it."""
    return " ".join(redact(p) for p in parts)


@dataclass(frozen=True)
class CallerProcess:
    """The process at the CLIENT end of the socket — never this server's."""
    pid: int
    cmdline: str
    cwd: Optional[str]
    #: Set when part of the process detail could not be read (a cwd whose
    #: readlink was refused, an empty cmdline). Never a substitute for the
    #: pid: the pid is proven by the socket, the detail is best effort.
    note: Optional[str] = None


@dataclass(frozen=True)
class Caller:
    """Everything this module is willing to say about who called.

    `process is None` is always accompanied by `reason` — there is no state
    in which this reports nothing and explains nothing."""
    peer: Optional[str]
    server: Optional[str]
    user_agent: Optional[str]
    forwarded_for: Optional[str]
    process: Optional[CallerProcess]
    reason: Optional[str]
    elapsed_ms: float

    def line(self) -> str:
        """The one log line. Built from the fields above only."""
        bits = [f"peer={self.peer or 'unknown'}",
                f"server={self.server or 'unknown'}",
                f'ua="{self.user_agent or "-"}"']
        if self.forwarded_for:
            bits.append(f'x-forwarded-for="{self.forwarded_for}"')
        if self.process is not None:
            bits.append(f"pid={self.process.pid}")
            bits.append(f"cwd={self.process.cwd or 'unreadable'}")
            bits.append(f'cmd="{self.process.cmdline}"')
            if self.process.note:
                bits.append(f"({self.process.note})")
        else:
            bits.append("calling process NOT RESOLVABLE "
                        f"({self.reason or 'no reason recorded'})")
        bits.append(f"lookup={self.elapsed_ms:.1f}ms")
        return " ".join(bits)


# ── The request, reduced to plain data (free, and safe to hand a thread) ────

def snapshot(request) -> dict:
    """Peer/server/allowlisted headers off the ASGI scope. Never raises.

    Pure and free — no /proc, no I/O — so the expensive half can run on a
    worker thread without carrying a `Request` object across it."""
    snap = {"peer": None, "server": None, "peer_ip": None, "peer_port": None,
            "server_ip": None, "server_port": None,
            "user_agent": None, "forwarded_for": None}
    try:
        client = getattr(request, "client", None)
        if client is not None:
            snap["peer_ip"] = client.host
            snap["peer_port"] = client.port
            snap["peer"] = f"{client.host}:{client.port}"
        server = (getattr(request, "scope", None) or {}).get("server")
        if server:
            snap["server_ip"], snap["server_port"] = server[0], server[1]
            snap["server"] = f"{server[0]}:{server[1]}"
        headers = getattr(request, "headers", None)
        if headers is not None:
            for name in SAFE_HEADERS:
                value = headers.get(name)
                if value:
                    key = "user_agent" if name == "user-agent" \
                        else "forwarded_for"
                    snap[key] = str(value)[:300]
    except Exception:                                   # pragma: no cover
        pass
    return snap


# ── /proc/net/tcp{,6} ───────────────────────────────────────────────────────

def _decode_addr(hex_addr: str) -> Optional[str]:
    """A /proc/net address field → a normalised IP string.

    The kernel prints each 32-bit word in HOST byte order, so on a
    little-endian machine every 4-byte group is reversed. An IPv4-mapped
    IPv6 address is normalised back to its IPv4 form, so a connection
    reported as `::ffff:127.0.0.1` compares equal to `127.0.0.1`."""
    try:
        if len(hex_addr) not in (8, 32):
            return None
        raw = b""
        for i in range(0, len(hex_addr), 8):
            word = bytes.fromhex(hex_addr[i:i + 8])
            raw += word[::-1] if sys.byteorder == "little" else word
        return _norm_ip(
            str(ipaddress.ip_address(raw)))
    except Exception:
        return None


def _norm_ip(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        addr = ipaddress.ip_address(value)
    except ValueError:
        return None
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return str(addr)


def _iter_rows(paths: Iterable[str]) -> Iterator[Tuple[str, str, str]]:
    """(local_hex, rem_hex, inode) for every row, both families."""
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                next(fh, None)                          # the header row
                for line in fh:
                    parts = line.split()
                    if len(parts) >= 10:
                        yield parts[1], parts[2], parts[9]
        except OSError:
            continue


def _split_hex(field: str) -> Tuple[Optional[str], Optional[int]]:
    if ":" not in field:
        return None, None
    addr, _, port = field.rpartition(":")
    try:
        return _decode_addr(addr), int(port, 16)
    except ValueError:
        return None, None


def find_socket_inode(peer_ip: str, peer_port: int,
                      server_ip: Optional[str], server_port: Optional[int],
                      paths: Iterable[str] = _PROC_NET
                      ) -> Tuple[Optional[str], Optional[str]]:
    """The inode of the CALLER's socket, or (None, reason).

    THE MIRROR MATCH IS THE WHOLE SAFETY ARGUMENT (see the module docstring):
    local == the peer AND rem == the server. The listening/accepted socket on
    this side has that tuple the other way round, so this can never resolve
    the server itself — which is exactly how River's version named her own
    process every time.

    When the ASGI scope could not tell us the server address, the match falls
    back to local == the peer and requires it to be UNIQUE; a non-unique
    fallback refuses rather than picking one."""
    want_peer = _norm_ip(peer_ip)
    want_server = _norm_ip(server_ip) if server_ip else None
    if want_peer is None:
        return None, f"the peer address {peer_ip!r} could not be parsed"

    matches = []
    saw_peer_end = False
    for local_hex, rem_hex, inode in _iter_rows(paths):
        local_ip, local_port = _split_hex(local_hex)
        if local_port != peer_port or local_ip != want_peer:
            continue
        saw_peer_end = True
        if want_server is not None and server_port is not None:
            rem_ip, rem_port = _split_hex(rem_hex)
            if rem_port != server_port or rem_ip != want_server:
                continue
            return inode, None
        matches.append(inode)

    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        return None, ("the server address is unknown to this process and "
                      f"{len(matches)} local sockets share {want_peer}:"
                      f"{peer_port} — refusing to pick one")
    if saw_peer_end:
        # A socket at the peer's own address:port exists but is talking to
        # somebody else — so this connection reached us through something
        # that rewrote it, or the port has already been reused. Either way
        # the row in front of us is NOT this caller's, and saying "closed"
        # would file a rewriting hop as a race.
        return None, (f"a local socket holds {want_peer}:{peer_port} but is "
                      f"not connected to {want_server}:{server_port} — this "
                      "connection was rewritten in between, or the port has "
                      "been reused; refusing to name the wrong process")
    loopback = False
    try:
        loopback = ipaddress.ip_address(want_peer).is_loopback
    except ValueError:                                  # pragma: no cover
        pass
    if loopback:
        return None, ("no socket in /proc/net/tcp{,6} matches this "
                      "connection — the caller's socket closed before it "
                      "could be read")
    return None, (f"the peer {want_peer} has no socket on this host — a "
                  "REMOTE caller has no local pid, so the calling process "
                  "is not resolvable from here")


# ── inode → process ─────────────────────────────────────────────────────────

def _pid_for_inode(inode: str, deadline: float
                   ) -> Tuple[Optional[int], Optional[str]]:
    target = f"socket:[{inode}]"
    unreadable = 0
    try:
        entries = os.listdir("/proc")
    except OSError as exc:
        return None, f"/proc could not be listed ({exc})"
    for entry in entries:
        if time.monotonic() > deadline:
            return None, (f"the /proc scan for socket inode {inode} ran past "
                          f"its {LOOKUP_BUDGET_S:g}s budget and gave up")
        if not entry.isdigit():
            continue
        fd_dir = f"/proc/{entry}/fd"
        try:
            fds = os.listdir(fd_dir)
        except PermissionError:
            unreadable += 1
            continue
        except OSError:
            continue
        for fd in fds:
            try:
                if os.readlink(f"{fd_dir}/{fd}") == target:
                    return int(entry), None
            except OSError:
                continue
    return None, (f"no readable process holds socket inode {inode} "
                  f"({unreadable} process(es) were not readable by this "
                  "user, so the caller may be one of them)")


def _process_detail(pid: int) -> CallerProcess:
    notes = []
    cmdline = ""
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            raw = fh.read()
        cmdline = redact_argv(
            p.decode("utf-8", "replace") for p in raw.split(b"\0") if p)
    except OSError as exc:
        notes.append(f"cmdline unreadable: {exc}")
    if not cmdline:
        try:
            with open(f"/proc/{pid}/comm", "r", encoding="utf-8") as fh:
                cmdline = redact(f"[{fh.read().strip()}]")
        except OSError:
            cmdline = "<unknown>"
    if len(cmdline) > CMDLINE_MAX:
        cmdline = cmdline[:CMDLINE_MAX] + "…"
        notes.append(f"cmdline truncated at {CMDLINE_MAX} chars")
    cwd = None
    try:
        cwd = os.readlink(f"/proc/{pid}/cwd")
    except OSError as exc:
        notes.append(f"cwd unreadable: {exc}")
    return CallerProcess(pid=pid, cmdline=cmdline, cwd=cwd,
                         note="; ".join(notes) or None)


# ── The public edge ─────────────────────────────────────────────────────────

def describe(snap: dict, budget_s: float = LOOKUP_BUDGET_S) -> Caller:
    """Resolve a `snapshot()` into a `Caller`. NEVER RAISES.

    Blocking (it reads /proc), so callers on an event loop go through
    `describe_request`, which hands this to a worker thread."""
    started = time.monotonic()
    deadline = started + budget_s

    def done(process, reason):
        return Caller(peer=snap.get("peer"), server=snap.get("server"),
                      user_agent=snap.get("user_agent"),
                      forwarded_for=snap.get("forwarded_for"),
                      process=process, reason=reason,
                      elapsed_ms=(time.monotonic() - started) * 1000.0)

    try:
        peer_ip, peer_port = snap.get("peer_ip"), snap.get("peer_port")
        if not peer_ip or peer_port is None:
            return done(None, "the request carried no peer address (a unix "
                              "socket, or a transport that does not report "
                              "one)")
        inode, reason = find_socket_inode(
            peer_ip, peer_port, snap.get("server_ip"), snap.get("server_port"))
        if inode is None:
            return done(None, reason)
        pid, reason = _pid_for_inode(inode, deadline)
        if pid is None:
            return done(None, reason)
        return done(_process_detail(pid), None)
    except Exception as exc:                            # pragma: no cover
        # THE OUTERMOST SWALLOW. Whatever happened, a take is not the place
        # to find out about it: report it in the line and move on.
        return done(None, f"the lookup failed ({type(exc).__name__}: {exc})")


def _unresolved(snap: dict, reason: str, elapsed_ms: float = 0.0) -> Caller:
    return Caller(peer=snap.get("peer"), server=snap.get("server"),
                  user_agent=snap.get("user_agent"),
                  forwarded_for=snap.get("forwarded_for"),
                  process=None, reason=reason, elapsed_ms=elapsed_ms)


async def describe_request(request) -> Caller:
    """`describe()` for an async route. NEVER RAISES, ALWAYS BOUNDED.

    The snapshot is taken on the loop (free); the /proc work runs off it so a
    route never blocks, and the await is capped at `AWAIT_BUDGET_S`.

    IT IS A **DAEMON** THREAD, NOT `asyncio.to_thread`, AND THAT IS THE
    POINT — measured, not preferred. `to_thread` runs on the loop's default
    executor, whose threads are joined when the loop shuts down, so a lookup
    abandoned at the budget still held the PROCESS for however long it had
    left to run (a deliberately wedged one held a test's teardown for the
    full 30 s while the route itself had returned in 200 ms). On his box that
    would be a wedged /proc read sitting in front of a `spectra.service`
    restart — the thing a stuck room is recovered with. A daemon thread is
    joined by nobody: the take does not wait for it, and neither does a
    shutdown. The result is delivered back through the loop, and the guard in
    `_deliver` is what makes a late delivery onto an abandoned future a
    no-op rather than an `InvalidStateError` in someone else's callback."""
    snap = snapshot(request)
    loop = asyncio.get_running_loop()
    future: "asyncio.Future[Caller]" = loop.create_future()

    def _deliver(value: Caller) -> None:
        if not future.done():
            future.set_result(value)

    def _work() -> None:
        try:
            result = describe(snap)
        except Exception as exc:                        # pragma: no cover
            result = _unresolved(
                snap, f"the lookup failed ({type(exc).__name__}: {exc})")
        try:
            loop.call_soon_threadsafe(_deliver, result)
        except RuntimeError:                            # pragma: no cover
            pass        # the loop is gone; by definition nothing is waiting

    try:
        threading.Thread(target=_work, name="spectra-caller-identity",
                         daemon=True).start()
    except Exception as exc:                            # pragma: no cover
        return _unresolved(
            snap, f"the lookup could not start ({type(exc).__name__}: {exc})")
    try:
        return await asyncio.wait_for(future, AWAIT_BUDGET_S)
    except asyncio.TimeoutError:
        return _unresolved(
            snap, f"the lookup ran past {AWAIT_BUDGET_S:g}s and was abandoned "
                  "so the take would not wait", AWAIT_BUDGET_S * 1000.0)
    except Exception as exc:                            # pragma: no cover
        return _unresolved(
            snap, f"the lookup failed ({type(exc).__name__}: {exc})")
