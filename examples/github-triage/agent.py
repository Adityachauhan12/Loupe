"""GitHub Issue Triage Agent — instrumented with Loupe.

For each open issue in GITHUB_REPO:
  1. Classify it as bug / feature / question (via Groq LLM)
  2. Post a one-line triage comment
  3. Add the classification label

Side effects: posts real comments + labels to GitHub.
This is intentionally "real" so failures are non-deterministic and hard to reproduce
without Loupe's replay — that's the whole point.
"""

import os
import json
from dotenv import load_dotenv
from groq import Groq
import loupe
from tools import list_open_issues, post_comment, add_label

load_dotenv()

loupe.init(
    api_key=os.environ["LOUPE_API_KEY"],
    host=os.environ.get("LOUPE_HOST", "http://localhost:8000"),
)

MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
MAX_ISSUES = int(os.environ.get("MAX_ISSUES", "10"))

SYSTEM_PROMPT = """You are a GitHub issue triage assistant.

Given an issue title and body, respond with JSON only — no explanation, no markdown.

Format:
{
  "label": "bug" | "feature" | "question",
  "comment": "<one sentence triage comment explaining your classification>"
}

Rules:
- bug: something is broken or not working as expected
- feature: a request for new functionality or enhancement
- question: asking how something works or for help
"""


@loupe.span(type="llm", name="classify_issue")
def classify_issue(client: Groq, issue: dict) -> dict:
    """Ask the LLM to classify a single issue. Returns {label, comment}."""
    user_msg = f"Title: {issue['title']}\n\nBody: {issue['body'] or '(no body)'}"
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content
    return json.loads(raw)


@loupe.trace
def triage_repo():
    """Top-level trace — one run = one full triage pass over the repo."""
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    loupe.instrument_groq(client)

    print(f"Fetching open issues from {os.environ['GITHUB_REPO']}...")
    issues = list_open_issues(max_issues=MAX_ISSUES)
    print(f"Found {len(issues)} issues to triage.")

    results = []
    for issue in issues:
        number = issue["number"]
        print(f"\n#{number}: {issue['title']}")

        # skip if already triaged by us
        if any(l in issue["labels"] for l in ("bug", "feature", "question")):
            print("  already labelled — skipping")
            continue

        classification = classify_issue(client, issue)
        label = classification["label"]
        comment = classification["comment"]

        print(f"  → {label}: {comment}")

        add_label(number, label)
        post_comment(number, f"**Loupe triage:** {comment}")

        results.append({"issue": number, "label": label})

    print(f"\nDone. Triaged {len(results)} issues.")
    return results


if __name__ == "__main__":
    triage_repo()
