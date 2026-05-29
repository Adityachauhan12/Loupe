"""CineRater — a small movie-recommendation agent instrumented with Loupe.

Flow:
    1. LLM parses the user query into structured filters {genre, year, min_rating}
    2. Tool: search_movies(...)
    3. Tool: get_movie_details(...) for the top 2 candidates
    4. LLM writes the final natural-language recommendation

Loupe records the whole run as a single trace, with each LLM call and tool
call as a span underneath it.
"""

from __future__ import annotations

import json
import os
import sys

import loupe
from dotenv import load_dotenv
from groq import Groq

from examples.cinerater.tools import get_movie_details, search_movies

load_dotenv()

GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# Initialise Loupe — points the SDK at the local server.
loupe.init(
    api_key=os.environ["LOUPE_API_KEY"],
    host=os.getenv("LOUPE_HOST", "http://localhost:8000"),
)

# Build the Groq client and let Loupe wrap its chat-completion method.
# Every `client.chat.completions.create(...)` call now becomes an llm span.
groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])
loupe.instrument_groq(groq_client)


PARSE_SYSTEM_PROMPT = """You convert movie-recommendation requests into filters.

Return a single JSON object with these optional keys:
  - genre: one of Action, Drama, Thriller, Comedy, Sci-Fi, Horror, Romance, Animation, Crime, Mystery
  - year: integer (e.g. 2023)
  - min_rating: float between 0 and 10

Only include keys the user clearly implies. If unclear, omit the key.
Return only the JSON object, no prose.
"""

WRITE_SYSTEM_PROMPT = """You are CineRater, a concise movie-recommendation assistant.

Given the user's request and a shortlist of candidate movies (with plots and ratings),
recommend ONE movie and justify it in 2-3 sentences. Mention the title, year, and director.
Do not mention movies that were not in the shortlist.
"""


def _parse_query(query: str) -> dict:
    """LLM step 1: turn free text into structured filters."""
    response = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": PARSE_SYSTEM_PROMPT},
            {"role": "user", "content": query},
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
    )
    raw = response.choices[0].message.content or "{}"
    return json.loads(raw)


def _write_recommendation(query: str, candidates: list[dict]) -> str:
    """LLM step 4: turn the shortlist into a natural-language recommendation."""
    user_msg = (
        f"User request: {query}\n\n"
        f"Shortlist (JSON):\n{json.dumps(candidates, indent=2)}"
    )
    response = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": WRITE_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.7,
    )
    return response.choices[0].message.content or ""


@loupe.trace(name="cinerater")
def recommend(query: str) -> str:
    """Top-level agent entry — recorded as a single Loupe trace."""
    filters = _parse_query(query)
    candidates = search_movies(**filters)

    if not candidates:
        return "Sorry, nothing in the catalogue matches that request."

    detailed = [get_movie_details(m["id"]) for m in candidates[:2]]
    detailed = [m for m in detailed if m is not None]

    return _write_recommendation(query, detailed)


if __name__ == "__main__":
    query = " ".join(sys.argv[1:]) or "recommend a thriller from 2023"
    print(f"\nQuery: {query}\n")
    print(recommend(query))
