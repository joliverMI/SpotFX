"""SPA index.html must revalidate every request; hashed /assets/ files may be
cached forever. Regression coverage for the no-Cache-Control-at-all defect
that let a phone pin an old bundle indefinitely (AGENTS.md: "SPA index.html
must never be heuristically cached").

Both spot-effects' /app mount (main.py) and SPECTRA's own mount
(spectra/app.py) carry an independent copy of SPAStaticFiles, so both are
covered here. Same convention as test_device_preview.py: TestClient built
without `with`, so no lifespan runs — pure static-file routing, no live
access.
"""
from __future__ import annotations

from pathlib import Path

import pytest


def _hashed_asset_name(dist_dir: Path) -> str:
    assets = sorted((dist_dir / "assets").glob("*.js"))
    assert assets, f"no built JS assets under {dist_dir}/assets — run the frontend build first"
    return assets[0].name


@pytest.fixture(params=["spotfx", "spectra"])
def spa_client(request):
    """(TestClient, dist_dir) for each of the two independent SPA mounts."""
    if request.param == "spotfx":
        import main
        from fastapi.testclient import TestClient
        return TestClient(main.app), main.WEB_DIST, "/app/"
    else:
        from fastapi.testclient import TestClient
        from spectra import config
        from spectra.app import create_app
        return TestClient(create_app()), config.WEB_DIST, "/"


def test_index_html_is_no_cache(spa_client):
    client, dist_dir, root = spa_client
    r = client.get(root)
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-cache"


def test_spa_fallback_route_is_no_cache(spa_client):
    """An unknown client-side route (e.g. a deep link) falls back to
    index.html and must carry the same no-cache directive, not the asset
    policy."""
    client, dist_dir, root = spa_client
    r = client.get(root + "some/unknown/client/route")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-cache"


def test_hashed_asset_is_immutable(spa_client):
    client, dist_dir, root = spa_client
    asset = _hashed_asset_name(dist_dir)
    r = client.get(root + "assets/" + asset)
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "public, max-age=31536000, immutable"


def test_index_html_revalidates_with_304(spa_client):
    client, dist_dir, root = spa_client
    first = client.get(root)
    etag = first.headers["etag"]
    second = client.get(root, headers={"if-none-match": etag})
    assert second.status_code == 304
    # A 304 still tells a downstream cache how to treat the resource.
    assert second.headers.get("cache-control") == "no-cache"


def test_hashed_asset_revalidates_with_304(spa_client):
    client, dist_dir, root = spa_client
    asset = _hashed_asset_name(dist_dir)
    first = client.get(root + "assets/" + asset)
    etag = first.headers["etag"]
    second = client.get(root + "assets/" + asset, headers={"if-none-match": etag})
    assert second.status_code == 304
    assert second.headers.get("cache-control") == "public, max-age=31536000, immutable"
