"""The failed run the killer demo starts from (U-006).

`agent.recommend` is the correct agent: it checks whether the search came back
empty and bails out politely. This module is the same agent *with that check
removed* — the single most common bug in tool-using agents, where the code
trusts that an LLM-chosen filter will match something.

What the trace looks like:

    llm  groq.chat        -> {"year": 1997}        <- the wrong upstream value
    tool search_movies    -> {"count": 0}          <- nothing in the catalogue
    (crash)               IndexError               <- trace status = error

The catalogue only holds 2022-2025 films, so a query about a 1997 movie makes
the parse step emit a year that cannot match. The parse call runs at
temperature 0, so the failure is reproducible rather than a lucky roll.

Why it is shaped this way: the branch button only appears on a span that has
something after it, so the wrong value has to land on the *first* LLM span with
a tool span behind it. Editing that span's output to a year the catalogue does
have is the fix the demo performs.

Run it from the repo root, with the server up:

    LOUPE_API_KEY=... python -m examples.cinerater.failing_demo
"""

from __future__ import annotations

import sys

import loupe

# Importing the agent runs loupe.init() + instrument_groq() for us, and gives
# us the exact same LLM steps — only the missing guard differs.
from examples.cinerater.agent import _parse_query, _write_recommendation
from examples.cinerater.tools import get_movie_details, search_movies

# A request for a film older than anything in the catalogue. The parse step
# faithfully turns it into year=1997; the catalogue starts at 2022.
FAILING_QUERY = "recommend me that sci-fi classic from 1997"


@loupe.trace(name="cinerater")
def recommend_unchecked(query: str) -> str:
    """CineRater without the empty-result guard — deliberately crashes.

    Do not "fix" this function. It exists to produce the failed trace that the
    branch demo repairs; `agent.recommend` is the corrected version.
    """
    filters = _parse_query(query)
    candidates = search_movies(**filters)

    # THE BUG: agent.recommend checks `if not candidates` here and returns a
    # polite message. Without that check, an empty search result walks straight
    # into an index lookup.
    detailed = [get_movie_details(m["id"]) for m in candidates[:2]]
    top = detailed[0]

    return _write_recommendation(query, [top])


if __name__ == "__main__":
    query = " ".join(sys.argv[1:]) or FAILING_QUERY
    print(f"\nQuery: {query}\n")
    try:
        print(recommend_unchecked(query))
    except IndexError as exc:
        # Re-raised by the trace decorator first, so the trace is already
        # recorded as an error by the time we get here.
        print(f"Agent crashed as intended: {type(exc).__name__}: {exc}")
        print("Open the trace in Loupe and branch from the first llm span.")
