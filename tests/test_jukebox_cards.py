"""The printable guest card (the plan's §9 N2, §8.1): SpotFX's GET
/api/jukebox/card hands the card page the join link (making the party token
if there is none yet — the cards carry it), the unused bonus codes and the
QR bonus, and nothing about the Wi-Fi, which is typed on the page and never
reaches SpotFX. `scripts/check_jukebox_cards.mjs` decodes every QR the page
draws back with jsQR and proves the password never leaves the page; this
file runs it, and `scripts/render_jukebox_cards.py` (the built harness in
Chromium, printed to a Letter PDF: eight cards a page, QR codes at least an
inch, the longest Wi-Fi still fitting), the same posture as
tests/test_jukebox_guest_page.py."""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import jukebox_router
from services.jukebox import bonus_codes, guest_link, store

REPO = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "check_jukebox_cards.mjs"
WEB = REPO / "spectra" / "web" / "node_modules"


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(jukebox_router.router)
    return TestClient(app)


def test_the_card_read_makes_the_party_token_and_lists_the_unused_codes():
    c = _client()
    out = c.get("/api/jukebox/card").json()
    assert out["link"] is None and out["host"] is None          # no address yet: the page asks
    _cfg, st = store.load_guest_link()
    assert st.token and out["token_created_ms"]                   # the cards carry it, so it exists now
    assert c.put("/api/jukebox/guest-link", json={"public_host": "serenity.tail1234.ts.net"}).status_code == 200
    a, b = bonus_codes.mint(2, "party")
    bonus_codes.claim(a, "n", "Ana", 1)
    out = c.get("/api/jukebox/card").json()
    assert out["link"] == f"https://serenity.tail1234.ts.net:8443/?t={st.token}"
    assert out["unused"] == [bonus_codes.pretty(b)] and out["qr_bonus"] == 5
    assert out["play_mode"] == "credits" and out["codes_error"] is None
    assert store.load_guest_link()[0].enabled is False             # reading never switches the link on
    again = c.get("/api/jukebox/card").json()
    assert again["link"] == out["link"]                            # the token is kept, not remade
    assert not any("wifi" in k.lower() or "password" in k.lower() for k in out)


def test_an_unreadable_codes_file_is_said_and_the_link_still_comes():
    store.BONUS_FILE.write_text("{ not json", encoding="utf-8")
    out = _client().get("/api/jukebox/card").json()
    assert out["unused"] == [] and "can't be read" in out["codes_error"]
    assert store.BONUS_FILE.read_text(encoding="utf-8") == "{ not json"


def test_a_token_made_for_the_cards_is_the_one_the_guest_page_admits():
    out = _client().get("/api/jukebox/card")
    assert out.status_code == 200
    _cfg, st = store.load_guest_link()
    assert guest_link.token_matches(st.token, st) and not guest_link.token_matches("nope", st)


@pytest.mark.skipif(
    not (WEB / ".bin" / "esbuild").exists() or not (WEB / "jsqr").exists() or shutil.which("node") is None,
    reason="frontend toolchain (node, esbuild and jsqr in spectra/web) not installed",
)
def test_every_card_qr_decodes_and_the_password_never_leaves_the_page():
    result = subprocess.run(["node", str(SCRIPT)], cwd=REPO, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, f"check_jukebox_cards.mjs failed:\n{result.stdout}\n{result.stderr}"


@pytest.mark.skipif(not (WEB / ".bin" / "vite").exists(), reason="frontend toolchain (vite in spectra/web) not installed")
def test_the_sheet_prints_eight_cards_a_letter_page(tmp_path):
    sys.path.insert(0, str(REPO / "scripts"))
    from check_ui_fidelity import find_chrome
    if find_chrome() is None:
        pytest.skip("no Chromium to render with")
    build = subprocess.run([str(WEB / ".bin" / "vite"), "build", "--config", "vite.harness.config.ts", "--logLevel", "error"],
                           cwd=REPO / "spectra" / "web", capture_output=True, text=True, timeout=300)
    assert build.returncode == 0, f"the harness didn't build:\n{build.stdout}\n{build.stderr}"
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "render_jukebox_cards.py"), "--out", str(tmp_path)],
                       cwd=REPO, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0 and "PASS" in r.stdout and "SKIP" not in r.stdout, f"{r.stdout}\n{r.stderr}"
    assert (tmp_path / "cards.pdf").stat().st_size > 0
