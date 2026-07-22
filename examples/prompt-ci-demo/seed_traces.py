"""Seed genre-extraction traces into a Loupe instance for the Prompt CI demo.

Each run makes one trace with a single LLM span: a Groq call that extracts the
genre a user is asking for as JSON, using the *current* contents of
``prompts/genre.txt`` as the system prompt. These are the "production" traces the
golden suite snapshots — later replayed against a changed prompt in a PR.

Usage:
    LOUPE_HOST=https://<your-loupe>.onrender.com \
    LOUPE_API_KEY=lp_... \
    GROQ_API_KEY=gsk_... \
    python3.11 examples/prompt-ci-demo/seed_traces.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import loupe
from groq import Groq

GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "genre.txt").read_text()

# Varied user queries, each clearly implying one of the allowed genres.
QUERIES = [
    "I want a mind-bending space movie about time travel",
    "Something that'll make me laugh out loud tonight",
    "A serious film about a family falling apart",
    "Give me explosions, car chases, and a big showdown",
    "I'm in the mood to be scared out of my wits",
    "A tense edge-of-your-seat spy story",
    "A sweet love story for date night",
    "Robots, aliens, and distant galaxies please",
    "A feel-good comedy with a lot of heart",
    "A gritty drama about addiction and recovery",
    "Non-stop action with a former soldier hero",
    "A haunted house that terrifies the family living in it",
    "A psychological thriller where nothing is as it seems",
    "Two people who fall in love against all odds",
    "A dystopian future ruled by artificial intelligence",
]

loupe.init(
    api_key=os.environ["LOUPE_API_KEY"],
    host=os.environ["LOUPE_HOST"],
)

client = Groq(api_key=os.environ["GROQ_API_KEY"])
loupe.instrument_groq(client)


@loupe.trace(name="genre_extract")
def extract_genre(query: str) -> dict:
    """One production run: free-text request -> {"genre": "..."} via the LLM."""
    resp = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": query},
        ],
        temperature=0.0,
    )
    raw = resp.choices[0].message.content or "{}"
    return json.loads(raw)


def main() -> None:
    for i, q in enumerate(QUERIES, 1):
        try:
            out = extract_genre(q)
            print(f"[{i:2}/{len(QUERIES)}] {q[:45]:45}  -> {out}")
        except Exception as e:  # noqa: BLE001 — seeding, keep going on a bad row
            print(f"[{i:2}/{len(QUERIES)}] {q[:45]:45}  -> ERROR {e}")
    # The SDK drains its send queue on process exit (atexit), so the traces
    # finish uploading as this script returns.
    print(f"\nSeeded {len(QUERIES)} traces to {os.environ['LOUPE_HOST']}")


if __name__ == "__main__":
    main()
