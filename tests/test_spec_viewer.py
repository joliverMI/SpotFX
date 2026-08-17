"""GET /spectra/spec renders docs/SPECTRA_SPEC.md as a phone-readable page,
not the raw markdown and not the SPA's own 200-for-everything shell (the
exact trap AGENTS.md's SPA cache-header entry names — a 200 alone proves
nothing). Same TestClient convention as test_spa_cache_headers.py: no
`with`, so no lifespan runs — pure route rendering, no live access.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from spectra.app import create_app
from spectra.services import spec_viewer


def _client() -> TestClient:
    return TestClient(create_app())


def test_spec_route_returns_real_content_not_the_spa_shell():
    client = _client()
    spec_resp = client.get("/spec")
    shell_resp = client.get("/some/unknown/route")
    assert spec_resp.status_code == 200
    assert shell_resp.status_code == 200
    # Both are 200 — the proof has to be the bytes, not the status code.
    assert len(spec_resp.content) > len(shell_resp.content) * 10


def test_spec_route_is_html_and_contains_known_spec_text():
    client = _client()
    r = client.get("/spec")
    assert r.headers["content-type"].startswith("text/html")
    assert "SPECTRA spec" in r.text
    assert "Maintenance protocol" in r.text


def test_tables_are_individually_scrollable_not_the_page():
    """Every rendered <table> is wrapped in its own overflow-x:auto
    container — long tables must scroll within themselves, never push the
    page sideways."""
    html = spec_viewer.render_spec_html()
    assert html.count("<table>") > 0
    assert html.count('<div class="table-scroll"><table>') == html.count("<table>")
    assert html.count("</table></div>") == html.count("</table>")


def test_toc_present_and_contains_a_real_section_anchor():
    html = spec_viewer.render_spec_html()
    assert '<details class="toc"' in html
    assert 'href="#' in html


def test_render_reads_the_real_file_fresh(tmp_path, monkeypatch):
    """No caching: editing the spec on disk must be visible on the next
    render (the spec is a living document under its own maintenance
    protocol — a stale cached render would defeat the point)."""
    fake = tmp_path / "SPECTRA_SPEC.md"
    fake.write_text("# Title\n\nOriginal content marker ABC123.\n", encoding="utf-8")
    monkeypatch.setattr(spec_viewer, "SPEC_PATH", fake)
    first = spec_viewer.render_spec_html()
    assert "ABC123" in first
    fake.write_text("# Title\n\nUpdated content marker XYZ789.\n", encoding="utf-8")
    second = spec_viewer.render_spec_html()
    assert "XYZ789" in second
    assert "ABC123" not in second
