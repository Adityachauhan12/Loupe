"""Credential redaction for ingested trace payloads (B11).

Instrumentation captures everything — that is the whole value, and the whole risk.
An exception message in particular tends to carry the request that raised it, headers
included, so a provider key lands in `error` on a perfectly ordinary failure and is
then rendered on the dashboard. That is not hypothetical: it happened here (L-013).

Design, in short:

*Fail open.* A payload that looks like it contains a secret is scrubbed and stored,
never rejected. Rejecting would drop the trace, and it would drop it precisely on the
unattended production runs nobody is watching — breaking the one promise an
observability tool makes. So we redact and keep going, and record *what* we redacted
in `metadata` so the user can see their own leak and fix it upstream.

*Walk the structure, not the serialised text.* Scrubbing `json.dumps(payload)` would
burn CPU on payloads that are mostly non-strings, would rewrite dict *keys* as well as
values, and risks corrupting the document through escape sequences. We recurse instead
and only ever touch `str` leaves, so the shape is preserved exactly.

*Best effort, not a guarantee.* We match known credential shapes. A house-format token
(`tok_x9f…`) will sail straight through. This lowers risk; it does not remove it, and
the README says so.
"""
from __future__ import annotations

import re
from typing import Any

PLACEHOLDER = "[REDACTED:{name}]"

# Ordered: the first pattern to match a span of text wins, so more specific shapes
# must precede the general ones. `sk-ant-` before `sk-` (Anthropic keys are valid
# OpenAI-shaped strings); every provider prefix before the bare `Bearer <token>`
# catch-all, so a recognised key is labelled by provider rather than as a header.
#
# Minimum lengths are deliberate. A short prefix like `sk-` appears in ordinary prose,
# and wrongly scrubbing a user's real output is its own kind of data loss — so every
# pattern demands a long, key-shaped run of characters before it fires.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("groq_key", re.compile(r"gsk_[A-Za-z0-9]{20,}")),
    ("anthropic_key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("openai_key", re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}")),
    ("github_token", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("slack_token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("google_api_key", re.compile(r"AIza[0-9A-Za-z_-]{35}")),
    ("stripe_key", re.compile(r"[rs]k_(?:live|test)_[A-Za-z0-9]{20,}")),
    ("loupe_key", re.compile(r"lp_[A-Za-z0-9_-]{30,}")),
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]*")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("postgres_url", re.compile(r"(?<=://)[^\s:/@]+:[^\s/@]+(?=@)")),
    # Last: anything still presented as a bearer credential. The placeholder written
    # by an earlier pattern starts with "[", which is outside this character class,
    # so an already-labelled key is not matched a second time.
    ("bearer_token", re.compile(r"(?<=Bearer )[A-Za-z0-9._~+/=-]{16,}")),
)


def scrub_text(text: str) -> tuple[str, list[str]]:
    """Replace credential-shaped runs in `text`.

    Returns the scrubbed text and the names of the patterns that fired, in order,
    once per pattern (not once per occurrence).
    """
    hits: list[str] = []
    for name, pattern in _PATTERNS:
        text, n = pattern.subn(PLACEHOLDER.format(name=name), text)
        if n:
            hits.append(name)
    return text, hits


def scrub_json(value: Any, _path: str = "") -> tuple[Any, list[str]]:
    """Recursively scrub string leaves of a JSON-shaped value.

    Returns the scrubbed value and the paths that were changed, e.g.
    `["error.message", "input.args[0]"]`. Dict keys, numbers, booleans and None are
    returned untouched — only `str` leaves are ever rewritten.
    """
    if isinstance(value, str):
        scrubbed, hits = scrub_text(value)
        return scrubbed, ([_path or "."] if hits else [])

    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        paths: list[str] = []
        for key, item in value.items():
            child = f"{_path}.{key}" if _path else str(key)
            out[key], found = scrub_json(item, child)
            paths.extend(found)
        return out, paths

    if isinstance(value, list):
        items: list[Any] = []
        paths = []
        for index, item in enumerate(value):
            child = f"{_path}[{index}]"
            scrubbed_item, found = scrub_json(item, child)
            items.append(scrubbed_item)
            paths.extend(found)
        return items, paths

    return value, []
