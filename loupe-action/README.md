# loupe-action — Prompt regression check for PRs

A GitHub Action that replays a **Loupe golden suite** against a changed prompt and
**blocks the PR on any regression**. It's a thin composite wrapper over the
`loupe suite run` CLI — one engine (the CLI), two entry points (human + CI).

## What it does

On a PR that changes your prompt file, the action:

1. installs the Loupe SDK,
2. runs `loupe suite run <suite-id> --prompt <prompt-file>` against your Loupe server,
3. posts a PR comment with the pass/regress summary + per-regression diff links,
4. **fails the check (red ❌) if any trace regressed** — the CLI's non-zero exit code
   is the status check. Zero regressions → green ✅.

## Usage

```yaml
# .github/workflows/prompt-ci.yml
name: Prompt CI
on:
  pull_request:
    paths:
      - "prompts/genre.txt"   # run only when the prompt changes

jobs:
  loupe:
    runs-on: ubuntu-latest
    permissions:
      pull-requests: write     # for the PR comment
    steps:
      - uses: actions/checkout@v4
      - uses: Adityachauhan12/loupe/loupe-action@main
        with:
          suite-id: ${{ vars.LOUPE_SUITE_ID }}
          prompt-file: prompts/genre.txt
          loupe-host: ${{ secrets.LOUPE_HOST }}
          api-key: ${{ secrets.LOUPE_API_KEY }}
          # backend: claude/claude-sonnet-4-6   # optional; default is the free Groq/Llama judge
```

## Inputs

| Input | Required | Description |
|---|---|---|
| `suite-id` | ✅ | The Loupe suite to run. |
| `prompt-file` | ✅ | Path to the changed prompt file (its PR-branch content is tested). |
| `loupe-host` | ✅ | Loupe server URL. GitHub-hosted runners can't reach `localhost` — use your deployed instance. |
| `api-key` | ✅ | `LOUPE_API_KEY` (pass a repo secret). |
| `backend` | ❌ | Judge backend override (default: free Groq/Llama). |
| `comment` | ❌ | Post a PR comment (default `true`). |

## Notes

- **Cost:** the default judge is the free Groq/Llama backend; a small suite (~10–15
  traces) keeps a run ~$0. Set `backend: claude/...` for stronger verdicts.
- **Gate policy:** zero-tolerance — any regression blocks. See
  [ARCHITECTURE_DECISIONS.md](../ARCHITECTURE_DECISIONS.md) B8.5 (D5).
- Requires a `loupe-sdk` version that ships the `suite` CLI (v2.2+).
