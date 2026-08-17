"""Tests for credential redaction (B11 / L-013).

Every key below is synthetic — pattern-shaped, never a real credential.

The second half asserts against what actually landed in Postgres, read back in a
fresh session. A 201 response proves nothing about what was persisted, and "what
was persisted" is the entire point of this feature.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models import Span, Trace
from app.services.redact import REDACTION_MARKER, scrub_json, scrub_text
from tests.conftest import make_engine, make_span_payload, make_trace_payload

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


# ── ingest: what actually reaches Postgres ──────────────────────────────────
async def _stored(trace_id: str) -> tuple[Trace, list[Span]]:
    """Read the persisted rows back in a fresh session."""
    engine = make_engine()
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        trace = (
            await session.execute(select(Trace).where(Trace.id == uuid.UUID(trace_id)))
        ).scalar_one()
        spans = list(
            (
                await session.execute(
                    select(Span).where(Span.trace_id == uuid.UUID(trace_id))
                )
            ).scalars().all()
        )
    await engine.dispose()
    return trace, spans


async def test_ingest_scrubs_the_l013_incident_end_to_end(client):
    """The real shape: httpx raises with the Authorization header in the message."""
    payload = make_trace_payload(
        status="error",
        error={
            "type": "LocalProtocolError",
            "message": f"Illegal header value b'Bearer {FAKE_GROQ}\\n'",
        },
    )
    assert (await client.post("/v1/traces", json=payload)).status_code == 201

    trace, _ = await _stored(payload["id"])
    assert FAKE_GROQ not in str(trace.error)
    assert "[REDACTED:groq_key]" in trace.error["message"]
    assert trace.error["type"] == "LocalProtocolError"
    assert trace.extra_metadata[REDACTION_MARKER] == ["error.message"]


async def test_ingest_scrubs_span_payloads(client):
    """The leaked key lived in span errors too — scrubbing only the trace is not enough."""
    span = make_span_payload("groq.chat", "llm")
    span["error"] = {"message": f"Bearer {FAKE_GROQ}"}
    span["input"] = {"headers": {"Authorization": f"Bearer {FAKE_OPENAI}"}}
    payload = make_trace_payload(spans=[span])

    assert (await client.post("/v1/traces", json=payload)).status_code == 201

    _, spans = await _stored(payload["id"])
    stored = spans[0]
    assert FAKE_GROQ not in str(stored.error)
    assert FAKE_OPENAI not in str(stored.input)
    assert sorted(stored.extra_metadata[REDACTION_MARKER]) == [
        "error.message",
        "input.headers.Authorization",
    ]


async def test_ingest_scrubs_trace_input_output_and_metadata(client):
    payload = make_trace_payload(
        input={"token": FAKE_GROQ},
        output={"echo": FAKE_OPENAI},
        metadata={"env": "prod", "auth": FAKE_ANTHROPIC},
    )
    assert (await client.post("/v1/traces", json=payload)).status_code == 201

    trace, _ = await _stored(payload["id"])
    blob = f"{trace.input}{trace.output}{trace.extra_metadata}"
    for secret in (FAKE_GROQ, FAKE_OPENAI, FAKE_ANTHROPIC):
        assert secret not in blob
    assert sorted(trace.extra_metadata[REDACTION_MARKER]) == [
        "input.token",
        "metadata.auth",
        "output.echo",
    ]
    # the user's own metadata survives alongside the marker
    assert trace.extra_metadata["env"] == "prod"


async def test_clean_payload_gets_no_marker(client):
    """Redaction must be invisible when there is nothing to redact."""
    payload = make_trace_payload(spans=[make_span_payload()])
    assert (await client.post("/v1/traces", json=payload)).status_code == 201

    trace, spans = await _stored(payload["id"])
    assert trace.extra_metadata is None
    assert spans[0].extra_metadata is None
    # and the payload is byte-for-byte what was sent
    assert trace.input == {"query": "test input"}
    assert trace.output == {"result": "test output"}


async def test_redacted_trace_is_readable_over_the_api(client):
    """A scrubbed trace still renders — fail open means the trace survives."""
    payload = make_trace_payload(
        status="error", error={"message": f"Bearer {FAKE_GROQ}"}
    )
    await client.post("/v1/traces", json=payload)

    resp = await client.get(f"/v1/traces/{payload['id']}")
    assert resp.status_code == 200
    body = resp.json()
    assert FAKE_GROQ not in resp.text
    assert body["status"] == "error"
    assert body["metadata"][REDACTION_MARKER] == ["error.message"]
