"""Tests for credential redaction (B11 / L-013).

Every key below is synthetic — pattern-shaped, never a real credential.
"""
from app.services.redact import scrub_json, scrub_text

# Shaped like the real thing, deliberately not one.
FAKE_GROQ = "gsk_" + "A1b2C3d4E5f6G7h8I9j0" * 2
FAKE_OPENAI = "sk-proj-" + "Xy9zAb8cDe7fGh6iJk5l"
FAKE_ANTHROPIC = "sk-ant-" + "Mn4oPq3rSt2uVw1xYz0a"


# ── the incident that motivated this ────────────────────────────────────────
def test_redacts_the_httpx_illegal_header_error() -> None:
    """The L-013 shape: a trailing newline in the key makes httpx raise, and the
    exception message carries the whole Authorization header — key included."""
    error = {
        "type": "LocalProtocolError",
        "message": f"Illegal header value b'Bearer {FAKE_GROQ}\\n'",
    }
    scrubbed, paths = scrub_json(error)

    assert FAKE_GROQ not in str(scrubbed)
    assert "[REDACTED:groq_key]" in scrubbed["message"]
    assert paths == ["message"]
    # untouched fields survive intact
    assert scrubbed["type"] == "LocalProtocolError"


def test_redacts_key_in_nested_span_error() -> None:
    """The key appeared 4-5x per trace — trace error *and* span errors."""
    payload = {
        "error": {"message": f"Bearer {FAKE_GROQ}"},
        "spans": [
            {"name": "groq.chat", "error": {"message": f"Bearer {FAKE_GROQ}"}},
            {"name": "search_movies", "error": None},
        ],
    }
    scrubbed, paths = scrub_json(payload)

    assert FAKE_GROQ not in str(scrubbed)
    assert paths == ["error.message", "spans[0].error.message"]


# ── each pattern fires ──────────────────────────────────────────────────────
def test_provider_key_shapes_are_redacted() -> None:
    for secret, expected in [
        (FAKE_GROQ, "groq_key"),
        (FAKE_OPENAI, "openai_key"),
        (FAKE_ANTHROPIC, "anthropic_key"),
        ("ghp_" + "a" * 36, "github_token"),
        ("xoxb-1234567890-abcdefghij", "slack_token"),
        ("AKIA" + "ABCDEFGHIJKLMNOP", "aws_access_key"),
        ("AIza" + "b" * 35, "google_api_key"),
        ("sk_live_" + "c" * 24, "stripe_key"),
        ("lp_" + "d" * 40, "loupe_key"),
        ("-----BEGIN RSA PRIVATE KEY-----", "private_key"),
    ]:
        scrubbed, hits = scrub_text(f"failed with {secret} oops")
        assert secret not in scrubbed, f"{expected} leaked through"
        assert hits == [expected]


def test_anthropic_key_is_labelled_anthropic_not_openai() -> None:
    """`sk-ant-...` is also a valid `sk-...`; the specific pattern must win."""
    scrubbed, hits = scrub_text(FAKE_ANTHROPIC)
    assert hits == ["anthropic_key"]
    assert scrubbed == "[REDACTED:anthropic_key]"


def test_jwt_is_redacted() -> None:
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc123def456"
    scrubbed, hits = scrub_text(f"token={jwt}")
    assert jwt not in scrubbed
    assert hits == ["jwt"]


def test_postgres_password_is_redacted_but_host_survives() -> None:
    dsn = "postgresql+asyncpg://loupe:sup3rs3cret@db.example.com:5432/loupe"
    scrubbed, hits = scrub_text(dsn)
    assert "sup3rs3cret" not in scrubbed
    assert hits == ["postgres_url"]
    # the parts you need for debugging are still there
    assert "db.example.com:5432/loupe" in scrubbed


def test_unrecognised_bearer_token_still_redacted() -> None:
    """Catch-all: a house-format token presented as a bearer credential."""
    scrubbed, hits = scrub_text("Authorization: Bearer tok_x9fQ2mZ7pL4vB8nR3wK6")
    assert "tok_x9fQ2mZ7pL4vB8nR3wK6" not in scrubbed
    assert hits == ["bearer_token"]


# ── false positives: scrubbing real data is its own kind of loss ────────────
def test_ordinary_prose_is_untouched() -> None:
    for benign in [
        "The movie sk-fi genre is popular",
        "Use a Bearer token to authenticate",  # too short to be a credential
        "gsk_short",  # below the minimum length
        "Recommend a comedy from 2022",
        "sk-",
        "AKIA",
        "user asked about ghp_ prefixes",
    ]:
        scrubbed, hits = scrub_text(benign)
        assert scrubbed == benign, f"false positive on: {benign}"
        assert hits == []


def test_dict_keys_are_never_rewritten() -> None:
    payload = {FAKE_GROQ: "value", "normal": "text"}
    scrubbed, paths = scrub_json(payload)
    assert FAKE_GROQ in scrubbed  # the key itself is structure, not content
    assert paths == []


def test_non_string_leaves_survive_unchanged() -> None:
    payload = {"tokens": 163, "cost": 0.0004, "ok": True, "err": None, "tags": []}
    scrubbed, paths = scrub_json(payload)
    assert scrubbed == payload
    assert paths == []


def test_structure_and_ordering_are_preserved() -> None:
    payload = {
        "args": ["recommend a comedy", {"depth": [1, 2, {"k": "v"}]}],
        "n": 3,
    }
    scrubbed, paths = scrub_json(payload)
    assert scrubbed == payload
    assert paths == []


# ── idempotence: re-ingesting an already-scrubbed payload is stable ─────────
def test_scrubbing_is_idempotent() -> None:
    once, hits_one = scrub_text(f"Bearer {FAKE_GROQ}")
    twice, hits_two = scrub_text(once)
    assert twice == once
    assert hits_one == ["groq_key"]
    assert hits_two == []


def test_placeholder_is_not_re_redacted_as_a_bearer_token() -> None:
    """After the key is labelled, the text still reads `Bearer [REDACTED:...]`."""
    scrubbed, hits = scrub_text(f"Bearer {FAKE_GROQ}")
    assert scrubbed == "Bearer [REDACTED:groq_key]"
    assert hits == ["groq_key"]


# ── edges ───────────────────────────────────────────────────────────────────
def test_empty_and_scalar_inputs() -> None:
    assert scrub_json(None) == (None, [])
    assert scrub_json({}) == ({}, [])
    assert scrub_json([]) == ([], [])
    assert scrub_text("") == ("", [])


def test_multiple_distinct_secrets_in_one_string() -> None:
    text = f"groq={FAKE_GROQ} openai={FAKE_OPENAI}"
    scrubbed, hits = scrub_text(text)
    assert FAKE_GROQ not in scrubbed
    assert FAKE_OPENAI not in scrubbed
    assert sorted(hits) == ["groq_key", "openai_key"]


def test_repeated_secret_reports_pattern_once() -> None:
    scrubbed, hits = scrub_text(f"{FAKE_GROQ} and again {FAKE_GROQ}")
    assert FAKE_GROQ not in scrubbed
    assert hits == ["groq_key"]
    assert scrubbed.count("[REDACTED:groq_key]") == 2
