from api.spotify_client import SCOPES


def test_scopes_include_user_library_read():
    assert "user-library-read" in SCOPES.split()
