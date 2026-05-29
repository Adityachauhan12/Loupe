"""Tool functions exposed to the CineRater agent.

Each tool is wrapped in a `loupe.span(type="tool")` so it shows up in the
dashboard as a distinct tool-call span, separate from the LLM spans that
the Groq instrumentation records automatically.
"""

from __future__ import annotations

import loupe

from examples.cinerater.data import MOVIES


def search_movies(
    genre: str | None = None,
    year: int | None = None,
    min_rating: float | None = None,
    limit: int = 5,
) -> list[dict]:
    """Filter the catalogue by genre / year / rating. Returns at most `limit` rows."""
    inputs = {"genre": genre, "year": year, "min_rating": min_rating, "limit": limit}
    with loupe.span("search_movies", type="tool", input=inputs) as s:
        results = MOVIES
        if genre:
            results = [m for m in results if m["genre"].lower() == genre.lower()]
        if year is not None:
            results = [m for m in results if m["year"] == year]
        if min_rating is not None:
            results = [m for m in results if m["rating"] >= min_rating]

        # Sort by rating, highest first — agent will get the best matches first.
        results = sorted(results, key=lambda m: m["rating"], reverse=True)[:limit]

        s.output = {"count": len(results), "movies": results}
        return results


def get_movie_details(movie_id: int) -> dict | None:
    """Fetch the full record for a single movie."""
    with loupe.span("get_movie_details", type="tool", input={"movie_id": movie_id}) as s:
        movie = next((m for m in MOVIES if m["id"] == movie_id), None)
        s.output = movie
        return movie
