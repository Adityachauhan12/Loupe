# Prompt CI/CD demo — the killer flow

This demo wires the [loupe-action](../../loupe-action) into a PR so a prompt change is
regression-tested against a golden suite before it can merge. It reuses the
[cinerater](../cinerater) agent (genre extraction).

> **Reachability:** GitHub-hosted runners can't reach `localhost`, so this demo points at
> a **deployed** Loupe instance (Render) via repo secrets. A small suite (~10–15 traces) on
> the free Groq/Llama judge keeps a run ~$0.

## One-time setup

1. **Seed traces** (if the instance has none): run the cinerater agent a handful of times
   against the deployed Loupe so there are real production traces to snapshot.

2. **Create a golden suite** from recent traces:
   ```bash
   LOUPE_HOST=https://<your-loupe>.onrender.com LOUPE_API_KEY=lp_... \
     python3.11 -m loupe.cli suite create --name "genre-golden" --from last:15
   # → ✓ suite created: <SUITE_ID>  (15 traces)
   ```

3. **Configure the consuming repo:**
   - copy [`prompt-ci.yml`](prompt-ci.yml) to `.github/workflows/prompt-ci.yml`
   - repo **secrets:** `LOUPE_HOST`, `LOUPE_API_KEY`
   - repo **variable:** `LOUPE_SUITE_ID` = the `<SUITE_ID>` from step 2

## The demo (what a reviewer sees)

1. Open a PR that edits [`prompts/genre.txt`](prompts/genre.txt) — e.g. the classic
   "innocent reword" that breaks the JSON contract:
   ```diff
   - Extract the genre the user wants as JSON: {"genre": "..."}.
   + Figure out what kind of movie the user is in the mood for and tell me.
   ```

2. The **Prompt CI** action runs (~30s). Under the hood it just calls
   `loupe suite run <SUITE_ID> --prompt prompts/genre.txt`.

3. A **PR comment** appears:
   ```
   ### 🔍 Loupe — prompt regression check
   ❌ 13/15 passed · 0 improved · 2 regressed · 0 errored
     - regressed  trace <id>  New output is prose, not the expected {"genre": ...} JSON
         diff: https://<your-loupe>/traces/<new_id>/diff
   ```

4. The check is **red ❌** (the CLI exited non-zero) → the merge is blocked.

5. Click **diff** → land in the Loupe dashboard with the broken trace side-by-side.
   Fix the prompt (keep the JSON contract), push → the action re-runs → **green ✅**.

## Why this is the whole point

Production trace → saved as a test → run on every prompt PR → block bad merges. A prompt
string now has the same green/red safety net real code has. See
[docs/concepts-explained.md](../../docs/concepts-explained.md) §1 for the full rationale.
