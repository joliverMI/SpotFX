"""The one shared reader of his Anthropic API key (spectra/services/
anthropic_key.py + config.settings_agent_api_key()) — the Admiral's
2026-11-17 order: "read the key from that file at runtime (or pass it via
an env var loaded from that file by the service unit) — never copy it into
code, config in git, logs, status lines or reports."

Offline, no network, and — the point of conftest.py's autouse
_no_real_anthropic_key fixture — never his real key file: every test here
writes its own key into a tmp_path file and points
SPECTRA_ANTHROPIC_API_KEY_FILE at that, so the suite proves the file route
without ever reading the real credential.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def key_file(tmp_path, monkeypatch):
    """A throwaway key file this test owns, with the env var pointed at it
    and ANTHROPIC_API_KEY cleared so the FILE route is what's under test."""
    path = tmp_path / "api-key"
    monkeypatch.setenv("SPECTRA_ANTHROPIC_API_KEY_FILE", str(path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return path


# ═══ 1. where the key comes from ═════════════════════════════════════════

def test_the_key_is_read_from_the_file_at_call_time(key_file):
    """Read on every call, never cached at import — so rotating the key is
    a file edit with no code path that could keep serving the old one (the
    posture config.night_run_token() documents for the same reason)."""
    from spectra import config as scfg
    from spectra.services import anthropic_key

    key_file.write_text("sk-ant-api03-first\n")
    assert anthropic_key.read() == "sk-ant-api03-first"
    assert scfg.settings_agent_api_key() == "sk-ant-api03-first"

    key_file.write_text("sk-ant-api03-rotated\n")
    assert anthropic_key.read() == "sk-ant-api03-rotated", \
        "a rotated key must take effect without a restart or a cache flush"


def test_trailing_whitespace_in_the_file_is_not_part_of_the_key(key_file):
    """`printf` into the file leaves no newline, `echo` leaves one, an
    editor may leave both — all three must produce the same key rather
    than a 401 nobody can explain."""
    from spectra.services import anthropic_key

    key_file.write_text("  sk-ant-api03-padded \n\n")
    assert anthropic_key.read() == "sk-ant-api03-padded"


def test_the_environment_wins_when_it_is_set(key_file, monkeypatch):
    """The route a service unit's own EnvironmentFile takes — and the route
    every pre-existing test in this suite takes — so it has to outrank the
    file rather than be shadowed by it."""
    from spectra.services import anthropic_key

    key_file.write_text("sk-ant-api03-from-the-file")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-from-the-env")
    assert anthropic_key.read() == "sk-ant-api03-from-the-env"
    assert anthropic_key.source() == "env"


def test_an_empty_or_whitespace_env_var_falls_through_to_the_file(key_file, monkeypatch):
    """`Environment=ANTHROPIC_API_KEY=` in a unit file, or an
    EnvironmentFile line that lost its value, must not mask a perfectly
    good key file with an empty string."""
    from spectra.services import anthropic_key

    key_file.write_text("sk-ant-api03-from-the-file")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "   ")
    assert anthropic_key.read() == "sk-ant-api03-from-the-file"
    assert anthropic_key.source() == "file"


def test_the_default_path_is_his_own_config_dir(monkeypatch):
    """The documented location, asserted rather than left to a comment:
    ~/.config/anthropic/api-key, outside the repo, outside anything this
    codebase's own writes can reach."""
    from pathlib import Path

    from spectra import config as scfg

    monkeypatch.delenv("SPECTRA_ANTHROPIC_API_KEY_FILE", raising=False)
    assert scfg.anthropic_api_key_file() == Path.home() / ".config" / "anthropic" / "api-key"


def test_the_override_expands_a_tilde(monkeypatch):
    from pathlib import Path

    from spectra import config as scfg

    monkeypatch.setenv("SPECTRA_ANTHROPIC_API_KEY_FILE", "~/elsewhere/api-key")
    assert scfg.anthropic_api_key_file() == Path.home() / "elsewhere" / "api-key"


# ═══ 2. a missing key is a clear, actionable, leak-free refusal ══════════

@pytest.mark.parametrize("contents", [None, "", "   \n"])
def test_a_missing_or_empty_key_file_is_unavailable_with_a_reason(key_file, contents):
    """Absent, empty, and whitespace-only all mean the same thing — and
    none of them is an exception out of read(), which must never raise: the
    features turn "" into their own stated refusal."""
    from spectra.services import anthropic_key

    if contents is not None:
        key_file.write_text(contents)

    assert anthropic_key.read() == ""
    status = anthropic_key.status()
    assert status["available"] is False
    assert status["source"] is None
    assert status["reason"] == anthropic_key.missing_reason()


def test_an_unreadable_key_file_is_unavailable_rather_than_an_exception(key_file):
    """A mode-000 file (a bad `chmod`, a file owned by another user after a
    migration) must read as "not configured", not crash a request handler
    with an OSError no surface knows how to render."""
    from spectra.services import anthropic_key

    key_file.write_text("sk-ant-api03-unreadable")
    key_file.chmod(0o000)
    try:
        assert anthropic_key.read() == ""
        assert anthropic_key.status()["available"] is False
    finally:
        key_file.chmod(0o600)


def test_a_directory_where_the_key_file_should_be_is_unavailable(tmp_path, monkeypatch):
    """The other OSError shape (IsADirectoryError): same answer."""
    from spectra.services import anthropic_key

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    directory = tmp_path / "api-key-dir"
    directory.mkdir()
    monkeypatch.setenv("SPECTRA_ANTHROPIC_API_KEY_FILE", str(directory))
    assert anthropic_key.read() == ""


def test_the_missing_reason_names_both_ways_to_fix_it_and_leaks_nothing(key_file):
    """What a human actually sees. It must name ANTHROPIC_API_KEY (the
    service route) AND the file path (the machine route) — a half-named
    cause is what sends someone looking in the wrong place — and it must
    carry no credential, because this sentence goes into a 503 body, a
    status line and the journal."""
    from spectra.services import anthropic_key

    reason = anthropic_key.missing_reason()
    assert "ANTHROPIC_API_KEY" in reason
    assert str(key_file) in reason
    assert "sk-ant-" not in reason


def test_status_never_carries_the_key_itself(key_file):
    """status() is shaped for an availability surface — which is to say for
    something that gets serialised to the web app. It may say WHERE the key
    came from; it may never say what it is, or how long it is, or what it
    starts with."""
    from spectra.services import anthropic_key

    key_file.write_text("sk-ant-api03-secret-value")
    status = anthropic_key.status()
    assert status == {"available": True, "reason": None, "source": "file",
                      "key_file": str(key_file)}
    assert "secret-value" not in repr(status)


# ═══ 3. redaction — the one place a credential could be echoed back ══════

def test_redact_removes_the_configured_key(key_file):
    from spectra.services import anthropic_key

    key_file.write_text("sk-ant-api03-configured")
    text = "claude: auth failed for sk-ant-api03-configured (401)"
    assert anthropic_key.redact(text) == "claude: auth failed for [redacted] (401)"


def test_redact_also_removes_a_key_shaped_string_it_was_never_given():
    """Belt and braces: a credential that reached us from somewhere this
    process does not control (a stale env var in a child, a pasted log)
    is not necessarily byte-identical to the configured one, and must
    still not survive into a journal line."""
    from spectra.services import anthropic_key

    out = anthropic_key.redact("stderr: using sk-ant-api03-SomeOtherKey_123 oh dear")
    assert "sk-ant-api03-SomeOtherKey_123" not in out
    assert "[redacted]" in out


def test_redact_leaves_ordinary_text_and_empty_input_alone():
    from spectra.services import anthropic_key

    assert anthropic_key.redact("") == ""
    assert anthropic_key.redact("Credit balance is too low") == "Credit balance is too low"


# ═══ 4. the inventory this module claims to cover ════════════════════════

def test_every_claude_calling_module_reads_the_key_through_this_helper():
    """The inventory, asserted so a FOURTH caller cannot quietly appear
    with its own os.getenv("ANTHROPIC_API_KEY") and its own idea of what a
    missing key means. config.py is the one place that touches the env var
    and the file; anthropic_key.py is the one place that decides what
    "configured" means; everyone else goes through it."""
    import pathlib

    import spectra.services.anthropic_key as ak

    root = pathlib.Path(ak.__file__).parent.parent  # spectra/
    offenders = []
    for path in root.rglob("*.py"):
        if path.name in ("config.py", "anthropic_key.py"):
            continue
        if 'getenv("ANTHROPIC_API_KEY' in path.read_text() or \
                "getenv('ANTHROPIC_API_KEY" in path.read_text():
            offenders.append(str(path.relative_to(root)))
    assert offenders == [], \
        f"these read the key themselves instead of through anthropic_key.py: {offenders}"


def test_nothing_in_the_tree_reads_a_subscription_credential_any_more():
    """"never a silent fallback to claude -p" as a repo-wide property: no
    module may read CLAUDE_CODE_OAUTH_TOKEN, because there must be no
    second credential to fall back to. (settings_agent_cli.py names it in
    prose and POPS it from the child environment — that is the opposite of
    reading it, and is what the exclusion below allows for.)"""
    import pathlib

    import spectra.services.anthropic_key as ak

    root = pathlib.Path(ak.__file__).parent.parent
    offenders = []
    for path in root.rglob("*.py"):
        text = path.read_text()
        if 'getenv("CLAUDE_CODE_OAUTH_TOKEN' in text or \
                "getenv('CLAUDE_CODE_OAUTH_TOKEN" in text:
            offenders.append(str(path.relative_to(root)))
    assert offenders == [], f"these still read a subscription credential: {offenders}"


def test_the_key_file_path_is_never_a_path_inside_the_repo(monkeypatch):
    """A public repo must not be able to become the key's home by
    accident — the default has to sit outside REPO_ROOT."""
    from spectra import config as scfg

    monkeypatch.delenv("SPECTRA_ANTHROPIC_API_KEY_FILE", raising=False)
    assert scfg.REPO_ROOT not in scfg.anthropic_api_key_file().parents
