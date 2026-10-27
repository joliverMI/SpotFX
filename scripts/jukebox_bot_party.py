#!/usr/bin/env python3
"""THE BOT PARTY (data/jukebox-plan/report.md §9, phase 2 PR 2.3's
acceptance: "30 bots for 20 minutes: SpotFX event-loop stalls p99 < 100 ms").

Three processes over loopback, the way a party reaches SpotFX:

  * a SpotFX STAND-IN: SpotFX's own Jukebox routes (routers/jukebox_router.py
    and routers/jukebox_guest_router.py), its engine (services/jukebox/
    night.py), its guests (services/jukebox/guests.py) and his library's
    search (services/jukebox/library.py, over a temp profile store), served
    by uvicorn. Only Spotify is faked: a player that plays in real time
    (20-35 s songs, so a party's worth of songs, votes and skips happens
    in minutes — and the load is harsher than a real night's), with every call slept 50-200 ms on its worker thread the way
    a real Spotify call blocks. A PROBE in its event loop sleeps 10 ms again
    and again and records how late it wakes: that lateness is exactly what a
    guest's tap, the master's poll or the engine's commit would wait out.
  * the REAL guest app (jukebox_guest/), its own process, forwarding to the
    stand-in with the guest app's key (it gets the same probe, read from a
    file it writes, since its routes are an allowlist).
  * N BOTS (30 by default), each a phone with its own cookie and address:
    it joins with tonight's token, polls the page every 3 s as the page
    does, votes on most songs (a few bots pick songs the room dislikes, so
    the room's skip and the jail happen), searches and adds songs, and moves
    songs; and a HOST polls the master's Live and Guests tabs every 5 s and
    pardons a guest in a time-out now and then.

It PASSES when the stand-in's loop stalls stay under 100 ms at the 99th
percentile, nothing answered with a server error, and the party really
happened (votes, adds, bumps and at least one room skip landed). The
request times it prints are measured from the bots' side, so they include
the bot process's own scheduling; the loop probe is the SpotFX number.

WHAT IT DOES NOT MEASURE, stated: the rest of SpotFX — its Spotify poll,
audio capture, Absorb and every other route — which shares the real loop.
This is the Jukebox's own share of SpotFX's loop under a party, not SpotFX
whole. Nothing here reaches Spotify, Home Assistant, Tailscale, his storage
or a live service; every store is repointed to a temp directory.

    .venv/bin/python scripts/jukebox_bot_party.py --minutes 20        # the acceptance run
    .venv/bin/python scripts/jukebox_bot_party.py --seconds 30 --json # tests/test_jukebox_bot_party.py
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import signal
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

TOKEN = "bot-party-token-0123456789"
PROBE_S = 0.010                  # the probe's sleep: its lateness is the stall
STALL_MS = 100.0                 # the acceptance bar (p99)
POLL_S = 3.0                     # the page polls every 3 s
HOST_POLL_S = 5.0                # the master's Live/Guests tabs
DEVICE = "Serenity"
PLAYLIST_ID = "PARTYSETLIST00000001"
PLAYLIST_URI = f"spotify:playlist:{PLAYLIST_ID}"
WORDS = ("Night", "Fire", "Dance", "Moon", "Gold", "River", "Neon", "Heart", "Summer", "Echo",
         "Velvet", "Thunder", "Sugar", "Paper", "Wild", "Electric", "Midnight", "Ocean",
         "Silver", "Rose", "Disco", "Honey", "Storm", "Rocket")
ARTISTS = ("The Lanterns", "Mira Vale", "Kid Copper", "Static Bloom", "Juno Park", "Los Faros",
           "Nova Reyes", "The Quiet Riot Club", "DJ Hollow", "Aurora Fields")
N_SET, N_CATALOG = 40, 400


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def catalog() -> list[dict]:
    """The songs Spotify knows tonight (the set is the first N_SET), each with
    an appeal the bots' taste reads: deterministic, so runs compare."""
    rng = random.Random(7)
    out = []
    for i in range(N_CATALOG):
        a, b = WORDS[i % len(WORDS)], WORDS[(i * 7 + 3) % len(WORDS)]
        out.append({"uri": f"spotify:track:party{i:017d}", "title": f"{a} {b}",
                    "artist": ARTISTS[(i * 3) % len(ARTISTS)],
                    "duration_ms": rng.randint(20, 35) * 1000, "explicit": i % 13 == 0,
                    "appeal": round(rng.random(), 3), "image": "", "thumb": ""})
    # the night opens on a song the room dislikes, so every party meets the
    # room's skip in its first minute
    out[0]["appeal"] = 0.02
    return out


def stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    v = sorted(values)

    def pct(p: float) -> float:
        return round(v[min(len(v) - 1, int(p * len(v)))], 2)
    return {"n": len(v), "p50": pct(0.50), "p95": pct(0.95), "p99": pct(0.99),
            "max": round(v[-1], 2), "over_100ms": sum(1 for x in v if x > STALL_MS),
            "mean": round(statistics.fmean(v), 2)}


# ═══ the SpotFX stand-in ════════════════════════════════════════════════════

class Player:
    """Spotify's player for the party, in real time: the set as its context,
    "Add to queue" songs before the context's next song."""

    def __init__(self, songs: list[dict]) -> None:
        self.lock = threading.Lock()
        self.songs = {s["uri"]: s for s in songs}
        self.context = [s["uri"] for s in songs[:N_SET]]
        self.ctx_pos = -1
        self.user_queue: list[str] = []
        self.current: Optional[str] = None
        self.started = 0.0              # monotonic time the current song was at 0
        self.is_playing = False
        self.shuffle, self.repeat = True, "off"
        self.plays = 0

    def _begin(self, uri: str) -> None:
        self.current, self.started, self.is_playing = uri, time.monotonic(), True
        self.plays += 1

    def progress_ms(self) -> int:
        if self.current is None:
            return 0
        return min(self.songs[self.current]["duration_ms"], int((time.monotonic() - self.started) * 1000))

    def go_next(self) -> None:
        if self.user_queue:
            self._begin(self.user_queue.pop(0))
            return
        nxt = self.ctx_pos + 1
        if nxt >= len(self.context):
            if self.repeat != "context":
                self.is_playing = False
                return
            nxt = 0
        self.ctx_pos = nxt
        self._begin(self.context[nxt])

    def tick(self) -> None:
        with self.lock:
            if self.is_playing and self.current and \
                    self.progress_ms() >= self.songs[self.current]["duration_ms"]:
                self.go_next()


class Gateway:
    """The Jukebox's gateway (services/jukebox/gateway.py), over the Player.
    Every call blocks 50-200 ms on its worker thread, as a Spotify call does."""

    def __init__(self, player: Player, songs: list[dict]) -> None:
        self.p = player
        self.songs = songs
        self.calls = 0

    def _wait(self) -> None:
        self.calls += 1
        time.sleep(random.uniform(0.05, 0.2))

    def _song(self, s: dict) -> dict:
        return {k: s[k] for k in ("uri", "title", "artist", "duration_ms", "explicit", "image", "thumb")}

    def device_id(self, name):
        self._wait()
        return "dev-serenity" if name == DEVICE else None

    def playback(self):
        self._wait()
        with self.p.lock:
            if self.p.current is None:
                return None
            return {"uri": self.p.current, "is_playing": self.p.is_playing,
                    "progress_ms": self.p.progress_ms(),
                    "duration_ms": self.p.songs[self.p.current]["duration_ms"],
                    "device_name": DEVICE, "context_uri": PLAYLIST_URI, "shuffle": self.p.shuffle,
                    "smart_shuffle": False, "repeat": self.p.repeat}

    def start_context(self, device_id, context_uri, position=0):
        self._wait()
        with self.p.lock:
            self.p.user_queue.clear()
            self.p.ctx_pos = position
            self.p._begin(self.p.context[position])

    def set_shuffle(self, on, device_id=None):
        self._wait()
        self.p.shuffle = bool(on)

    def set_repeat(self, mode, device_id=None):
        self._wait()
        self.p.repeat = mode

    def pause(self, device_id=None):
        self._wait()
        self.p.is_playing = False

    def add_to_queue(self, uri):
        self._wait()
        with self.p.lock:
            self.p.user_queue.append(uri)

    def queue(self):
        self._wait()
        with self.p.lock:
            rest = self.p.context[self.p.ctx_pos + 1:self.p.ctx_pos + 11]
            return {"current": self.p.current or "", "queue": list(self.p.user_queue) + rest}

    def next_track(self):
        self._wait()
        with self.p.lock:
            self.p.go_next()

    def resolve_playlist(self, link):
        self._wait()
        return ({"id": PLAYLIST_ID, "name": "Party set", "uri": PLAYLIST_URI, "snapshot_id": "snap-1"}
                if PLAYLIST_ID in link else None)

    def playlist_snapshot(self, pid):
        self._wait()
        return "snap-1"

    def playlist_items(self, pid):
        self._wait()
        return [self._song(self.p.songs[u]) for u in self.p.context]

    def reorder(self, pid, range_start, insert_before, snapshot_id=""):
        self._wait()
        return "snap-1"

    def track(self, uri):
        self._wait()
        s = self.p.songs.get(uri)
        return self._song(s) if s else None

    def search(self, query, limit=10, offset=0):
        self._wait()
        words = query.lower().split()
        hits = [s for s in self.songs[N_SET:] if all(w in f"{s['title']} {s['artist']}".lower() for w in words)]
        return [self._song(s) for s in hits[offset:offset + limit]]

    def tracks(self, uris):
        self._wait()
        return [self._song(self.p.songs[u]) for u in uris if u in self.p.songs]


def spotfx_app(tmp: Path):
    """SpotFX's own Jukebox routes, engine and guests over the fake Spotify,
    every store in `tmp`, and the loop probe."""
    from datetime import datetime, timedelta
    from contextlib import asynccontextmanager

    from fastapi import FastAPI

    from models.jukebox import EconomyConfig, ProgramConfig, ShowConfig
    from models.state import SpotifyTrackInfo
    from routers import jukebox_guest_router, jukebox_router
    from services.jukebox import guests, ledger, library, night, store

    for attr in ("CONFIG_FILE", "NIGHT_FILE", "SHOW_FILE", "GUEST_LINK_FILE", "GUESTS_FILE"):
        setattr(store, attr, tmp / f"{attr.lower()}.json")
    ledger.LEDGER_DIR = tmp / "jukebox_ledger"
    jukebox_guest_router.KEY_FILE = tmp / "guest_key"
    songs = catalog()
    # his library: a third of the catalog has a profile (the "Ready" section's search)
    library.PROFILES_DIR = tmp / "profiles"
    library.PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    for i, s in enumerate(songs[N_SET::3]):
        (library.PROFILES_DIR / f"p{i}.json").write_text(json.dumps(
            {"spotify_uri": s["uri"], "title": s["title"], "artist": s["artist"]}))
    library.reset()
    known = {s["uri"] for s in songs[N_SET::5]}

    ends = datetime.now(guests.HOUSE_TZ) + timedelta(hours=4)
    # free play: the bots exercise phase 2.3's rules (credits mode is the
    # default since PR 3.2, and its writes go through the ledger, off the loop)
    store.save_show(ShowConfig(night_ends=f"{ends.hour:02d}:{ends.minute:02d}", explicit="extra",
                               max_phones=100, play_mode="free",
                               economy=EconomyConfig(skip_grace_s=10)))
    cfg = ProgramConfig(playlist=PLAYLIST_URI, mode="auto", every=1, run=2, run_out="again",
                        commit_lead_s=20)
    store.save_config(cfg)
    player = Player(songs)
    gw = Gateway(player, songs)

    def current_track():
        with player.lock:
            if player.current is None:
                return None
            s = player.songs[player.current]
            return SpotifyTrackInfo(spotify_uri=s["uri"], title=s["title"], artist=s["artist"],
                                    duration_ms=s["duration_ms"], progress_ms=player.progress_ms(),
                                    is_playing=player.is_playing, fetched_at=time.monotonic(),
                                    device_name=DEVICE, context_uri=PLAYLIST_URI,
                                    context_type="playlist")

    async def never_sleeping():
        return False

    runner = night.JukeboxRunner(night.JukeboxDeps(
        gateway=gw, current_track=current_track, device_name=lambda: DEVICE,
        sleeping=never_sleeping, load_config=lambda: cfg, known=lambda uri: uri in known,
        sign_in=lambda: {"state": "ok", "warning": ""}))
    night.runner = runner
    guests.book = guests.Guests(guests.GuestDeps(
        token_ok=lambda t: t == TOKEN, gateway=lambda: gw,
        known=lambda uris: {u: u in known for u in uris}))

    lag: list[float] = []
    tasks: list[asyncio.Task] = []

    async def probe() -> None:
        while True:
            t0 = time.perf_counter()
            await asyncio.sleep(PROBE_S)
            lag.append((time.perf_counter() - t0 - PROBE_S) * 1000)

    async def ticker() -> None:
        while True:
            await asyncio.sleep(0.25)
            player.tick()
            runner.on_track_state()

    @asynccontextmanager
    async def lifespan(_app):
        out = await runner.start(play=True)
        if out.get("status") != "running":
            raise RuntimeError(f"the party's night didn't start: {out}")
        tasks.extend(asyncio.create_task(c) for c in (probe(), ticker(), runner.run_supervised()))
        yield
        for t in tasks:
            t.cancel()

    app = FastAPI(lifespan=lifespan)
    app.include_router(jukebox_router.router)
    app.include_router(jukebox_guest_router.router)

    @app.get("/__party/ready")
    async def ready() -> dict:
        return {"running": runner.running}

    @app.get("/__party/report")
    async def report() -> dict:
        n = runner.night
        log = n.log if n else []
        return {"loop_ms": stats(lag), "plays": player.plays, "spotify_calls": gw.calls,
                "voted_off": sum(1 for x in log if "voted" in x and "off" in x),
                "jailed": sum(1 for x in log if "sit out" in x),
                "pardoned": sum(1 for x in log if "pardoned" in x),
                "bumps": sum(1 for x in log if "moved" in x and "one place" in x),
                "adds": sum(1 for x in log if "a guest added" in x),
                "phones": len(guests.book._book.phones) if guests.book._book else 0}
    return app


def serve_spotfx(port: int, tmp: Path) -> None:
    import logging

    import uvicorn
    logging.getLogger("services.jukebox").setLevel(logging.WARNING)
    uvicorn.run(spotfx_app(tmp), host="127.0.0.1", port=port, log_level="warning", access_log=False)


def serve_guest(port: int, spotfx: str, tmp: Path) -> None:
    """The real guest app, plus the same probe (written to a file every few
    seconds, since its routes are an allowlist)."""
    import uvicorn

    from jukebox_guest.app import create_app
    app = create_app(spotfx_url=spotfx, key_file=tmp / "guest_key", dist_dir=tmp / "no-dist")
    lag: list[float] = []

    async def probe() -> None:
        last = time.monotonic()
        while True:
            t0 = time.perf_counter()
            await asyncio.sleep(PROBE_S)
            lag.append((time.perf_counter() - t0 - PROBE_S) * 1000)
            if time.monotonic() - last > 2:
                last = time.monotonic()
                (tmp / "guest_loop.json").write_text(json.dumps(stats(lag)))

    async def main() -> None:
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning",
                                               access_log=False, server_header=False))
        task = asyncio.create_task(probe())
        try:
            await server.serve()
        finally:
            task.cancel()
    asyncio.run(main())


# ═══ the bots ═══════════════════════════════════════════════════════════════

class Tally:
    def __init__(self) -> None:
        self.latency: dict[str, list[float]] = {}
        self.codes: dict[int, int] = {}
        self.done: dict[str, int] = {}
        self.server_errors: list[str] = []

    def call(self, kind: str, ms: float, code: int, detail: str = "") -> None:
        self.latency.setdefault(kind, []).append(ms)
        self.codes[code] = self.codes.get(code, 0) + 1
        if code >= 500 or code == 0:
            self.server_errors.append(f"{kind} {code} {detail}"[:200])

    def count(self, what: str) -> None:
        self.done[what] = self.done.get(what, 0) + 1


async def _req(client, tally: Tally, kind: str, method: str, path: str, body: Any = None):
    import httpx
    t0 = time.perf_counter()
    try:
        r = await (client.get(path) if method == "GET" else client.post(path, json=body or {}))
    except httpx.HTTPError as exc:
        tally.call(kind, (time.perf_counter() - t0) * 1000, 0, type(exc).__name__)
        return None, {}
    ms = (time.perf_counter() - t0) * 1000
    try:
        data = r.json()
    except ValueError:
        data = {}
    tally.call(kind, ms, r.status_code, str(data.get("reason", "")) if isinstance(data, dict) else "")
    return r.status_code, data if isinstance(data, dict) else {}


async def bot(i: int, guest_url: str, until: float, songs: dict[str, dict], tally: Tally) -> None:
    import httpx
    rng = random.Random(1000 + i)
    picky = i % 6 == 0                       # picks songs the room dislikes: skips and jail happen
    headers = {"X-Forwarded-For": f"10.20.{i // 200}.{i % 200 + 1}"}
    async with httpx.AsyncClient(base_url=guest_url, headers=headers, timeout=10.0) as c:
        await asyncio.sleep(rng.uniform(0, 4))
        code, out = await _req(c, tally, "hello", "POST", "/g/hello", {"token": TOKEN})
        if code != 200:
            return
        await _req(c, tally, "join", "POST", "/g/join", {})
        voted: set[str] = set()
        while time.monotonic() < until:
            code, out = await _req(c, tally, "view", "GET", "/g/view")
            view = out.get("view") or out
            now = view.get("now") if isinstance(view, dict) else None
            if now and now.get("can_vote"):
                if now.get("my_vote") == 0 and now["uri"] not in voted and rng.random() < 0.8:
                    appeal = songs.get(now["uri"], {}).get("appeal", 0.6)
                    vote = "down" if appeal + rng.uniform(-0.25, 0.25) < 0.35 else "up"
                    code, _ = await _req(c, tally, "vote", "POST", "/g/vote", {"vote": vote})
                    if code == 200:
                        tally.count(f"vote_{vote}")
                    voted.add(now["uri"])
            req = view.get("requests") if isinstance(view, dict) else None
            if req and req.get("open") and req.get("waiting", 0) < req.get("max_waiting", 2) \
                    and rng.random() < 0.07:
                q = f"{rng.choice(WORDS)}"
                code, found = await _req(c, tally, "search", "POST", "/g/search", {"q": q})
                results = [r for r in found.get("results", []) if r.get("can_add")] if code == 200 else []
                if results:
                    results.sort(key=lambda r: songs.get(r["uri"], {}).get("appeal", 0.5))
                    pick = results[0] if picky else rng.choice(results[len(results) // 3:] or results)
                    code, _ = await _req(c, tally, "add", "POST", "/g/add", {"uri": pick["uri"]})
                    if code == 200:
                        tally.count("add")
            nxt = view.get("next", []) if isinstance(view, dict) else []
            movable = [s for s in nxt if s.get("bump") and s.get("entry_id")]
            if movable and rng.random() < 0.03:
                s = rng.choice(movable)
                code, _ = await _req(c, tally, "bump", "POST", "/g/bump",
                                     {"entry_id": s["entry_id"], "direction": s["bump"]})
                if code == 200:
                    tally.count("bump")
            await asyncio.sleep(POLL_S * rng.uniform(0.9, 1.1))


async def host(spotfx_url: str, until: float, tally: Tally) -> None:
    import httpx
    rng = random.Random(99)
    async with httpx.AsyncClient(base_url=spotfx_url, timeout=10.0) as c:
        while time.monotonic() < until:
            await _req(c, tally, "master_status", "GET", "/api/jukebox/status?count=20")
            code, g = await _req(c, tally, "master_guests", "GET", "/api/jukebox/guests")
            for p in (g.get("phones") or []) if code == 200 else []:
                if p.get("jail_left") and rng.random() < 0.25:
                    code, _ = await _req(c, tally, "pardon", "POST", f"/api/jukebox/guests/{p['id']}",
                                         {"pardon": True})
                    if code == 200:
                        tally.count("pardon")
            await asyncio.sleep(HOST_POLL_S)


async def wait_up(url: str, timeout: float = 60.0) -> bool:
    import httpx
    deadline = time.monotonic() + timeout
    async with httpx.AsyncClient(timeout=2.0) as c:
        while time.monotonic() < deadline:
            try:
                r = await c.get(url)
                if r.status_code < 500 or url.endswith("/"):
                    if not url.endswith("/__party/ready") or r.json().get("running"):
                        return True
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(0.3)
    return False


def _spawn(args: list[str]) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, str(Path(__file__).resolve()), *args],  # noqa: S603
                            cwd=REPO, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE, start_new_session=True)


def _stop(proc: subprocess.Popen) -> str:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        _, err = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        _, err = proc.communicate()
    return (err or b"").decode(errors="replace")[-2000:]


async def party(bots: int, seconds: float) -> dict:
    import httpx
    tmp = Path(tempfile.mkdtemp(prefix="jukebox-bot-party-"))
    sp, gp = free_port(), free_port()
    spotfx_url, guest_url = f"http://127.0.0.1:{sp}", f"http://127.0.0.1:{gp}"
    procs = [_spawn(["--role", "spotfx", "--port", str(sp), "--tmp", str(tmp)]),
             _spawn(["--role", "guest", "--port", str(gp), "--spotfx", spotfx_url, "--tmp", str(tmp)])]
    errs: list[str] = []
    try:
        if not await wait_up(f"{spotfx_url}/__party/ready") or not await wait_up(f"{guest_url}/"):
            raise RuntimeError("the stand-in or the guest app never came up")
        songs = {s["uri"]: s for s in catalog()}
        tally = Tally()
        until = time.monotonic() + seconds
        t0 = time.monotonic()
        await asyncio.gather(host(spotfx_url, until, tally),
                             *(bot(i, guest_url, until, songs, tally) for i in range(bots)))
        ran_s = time.monotonic() - t0
        async with httpx.AsyncClient(timeout=10.0) as c:
            night = (await c.get(f"{spotfx_url}/__party/report")).json()
        guest_loop = json.loads((tmp / "guest_loop.json").read_text()) if (tmp / "guest_loop.json").exists() else {}
    finally:
        for p in procs:
            errs.append(_stop(p))
    loop = night.pop("loop_ms")
    out = {
        "bots": bots, "seconds": round(ran_s, 1),
        "spotfx_loop_stall_ms": loop, "guest_app_loop_stall_ms": guest_loop,
        "requests": {k: stats(v) for k, v in sorted(tally.latency.items())},
        "status_codes": dict(sorted(tally.codes.items())),
        "server_errors": tally.server_errors[:20],
        "bots_did": tally.done, "night": night,
    }
    problems = []
    if not loop.get("n"):
        problems.append("the probe recorded nothing")
    elif loop["p99"] >= STALL_MS:
        problems.append(f"SpotFX's loop stalled {loop['p99']} ms at the 99th percentile (bar: {STALL_MS:.0f})")
    if tally.server_errors:
        problems.append(f"{len(tally.server_errors)} server error(s), first: {tally.server_errors[0]}")
    if not tally.done.get("vote_up", 0) + tally.done.get("vote_down", 0):
        problems.append("no bot managed a vote — the party didn't happen")
    if not tally.done.get("add"):
        problems.append("no bot managed to add a song — the party didn't happen")
    if seconds >= 120 and not night.get("voted_off"):
        problems.append("no song was voted off in a party this long")
    if seconds >= 120 and not tally.done.get("bump"):
        problems.append("no bot moved a song in a party this long")
    out["problems"] = problems
    out["pass"] = not problems
    if problems:
        out["stderr_tail"] = [e for e in errs if e.strip()]
    return out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--role", choices=("party", "spotfx", "guest"), default="party")
    ap.add_argument("--port", type=int)
    ap.add_argument("--spotfx")
    ap.add_argument("--tmp")
    ap.add_argument("--bots", type=int, default=30)
    ap.add_argument("--minutes", type=float)
    ap.add_argument("--seconds", type=float)
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    ap.add_argument("--out", help="also write the JSON report here")
    a = ap.parse_args(argv)
    if a.role == "spotfx":
        serve_spotfx(a.port, Path(a.tmp))
        return 0
    if a.role == "guest":
        serve_guest(a.port, a.spotfx, Path(a.tmp))
        return 0
    seconds = a.seconds if a.seconds is not None else 60 * (a.minutes if a.minutes is not None else 20)
    out = asyncio.run(party(a.bots, seconds))
    if a.out:
        Path(a.out).write_text(json.dumps(out, indent=1) + "\n")
    if a.json:
        print(json.dumps(out))
    else:
        loop = out["spotfx_loop_stall_ms"]
        print(f"{out['bots']} bots for {out['seconds']} s")
        print(f"SpotFX loop stalls (ms): p50 {loop.get('p50')} · p99 {loop.get('p99')} · "
              f"max {loop.get('max')} · over 100 ms: {loop.get('over_100ms')} of {loop.get('n')}")
        g = out["guest_app_loop_stall_ms"]
        if g:
            print(f"guest app loop stalls (ms): p50 {g.get('p50')} · p99 {g.get('p99')} · max {g.get('max')}")
        for k, v in out["requests"].items():
            print(f"  {k:14} n={v['n']:6}  p50 {v['p50']:7.1f} ms  p99 {v['p99']:7.1f} ms")
        print(f"bots did: {out['bots_did']}")
        print(f"the night: {out['night']}")
        print(f"status codes: {out['status_codes']}")
        print("PASS" if out["pass"] else "FAIL\n  " + "\n  ".join(out["problems"]))
    return 0 if out["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
