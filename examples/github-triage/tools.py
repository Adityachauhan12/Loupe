"""GitHub tools — each function is a side-effecting tool the agent can call.

These are wrapped as loupe spans so every input/output is captured.
Side effects: post_comment and add_label write to GitHub (real API calls).
"""

import os
import loupe
from github import Github

_gh = None


def _client() -> Github:
    global _gh
    if _gh is None:
        _gh = Github(os.environ["GITHUB_TOKEN"])
    return _gh


def _repo():
    return _client().get_repo(os.environ["GITHUB_REPO"])


@loupe.span(type="tool", name="list_open_issues")
def list_open_issues(max_issues: int = 10) -> list[dict]:
    """Fetch open issues (excludes PRs). Read-only."""
    issues = []
    for issue in _repo().get_issues(state="open"):
        if issue.pull_request:
            continue
        issues.append({
            "number": issue.number,
            "title": issue.title,
            "body": (issue.body or "")[:1000],
            "labels": [l.name for l in issue.labels],
            "comments": issue.comments,
        })
        if len(issues) >= max_issues:
            break
    return issues


@loupe.span(type="tool", name="post_comment")
def post_comment(issue_number: int, comment: str) -> dict:
    """Post a triage comment on an issue. SIDE EFFECT: writes to GitHub."""
    issue = _repo().get_issue(issue_number)
    posted = issue.create_comment(comment)
    return {"comment_id": posted.id, "url": posted.html_url}


@loupe.span(type="tool", name="add_label")
def add_label(issue_number: int, label: str) -> dict:
    """Add a label to an issue. Creates the label if it doesn't exist. SIDE EFFECT."""
    repo = _repo()
    # ensure label exists
    existing = [l.name for l in repo.get_labels()]
    if label not in existing:
        colors = {"bug": "d73a4a", "feature": "0075ca", "question": "e4e669"}
        repo.create_label(label, colors.get(label, "ededed"))
    issue = repo.get_issue(issue_number)
    issue.add_to_labels(label)
    return {"issue": issue_number, "label": label}
