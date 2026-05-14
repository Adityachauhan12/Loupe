# Item 1 — Repo initialized, monorepo structure set up

Light on decisions but a few are worth defending in interviews.

---

## Sub-step A — Directory layout

**What changed**

Created the skeleton:

```
loupe/
├── sdk/loupe/                  (+ integrations/, tests/)
├── server/app/                 (+ routers/, alembic/versions/, tests/)
├── dashboard/                  (Next.js — populated in later items)
└── .github/workflows/          (CI — populated later)
```

`__init__.py` files placed in every Python package directory.

**Learnings**

- **Monorepo vs polyrepo for a small OSS project.** With three components (SDK, server, dashboard) that share a schema and ship together, a monorepo keeps them in lockstep. A breaking SDK change + matching server change are one PR, not two repos to coordinate. Tradeoff: tighter coupling means harder to extract one piece later, but Loupe isn't expecting that.
- **Why `__init__.py` everywhere.** Implicit namespace packages (PEP 420) work without them, but tooling (mypy, pytest discovery, alembic env.py imports) is more reliable when packages are explicit. Costs nothing.
- **Empty directories aren't tracked by git.** `dashboard/` and `.github/workflows/` are missing from the initial commit because git only tracks files. They'll be tracked once their content lands. Don't pad them with `.gitkeep` unless the empty dir itself is semantically meaningful.

**Interview questions**

1. Why monorepo vs polyrepo for a project like this? *(coordinated changes across SDK + server + dashboard; tradeoff is coupling)*
2. What's the difference between an implicit namespace package and a regular package in Python? *(PEP 420; regular packages have `__init__.py`, implicit do not; mixing them confuses tooling)*

---

## Sub-step B — Foundational files (`.gitignore`, `LICENSE`, `.python-version`, `README.md`)

**What changed**

- `.gitignore` — Python + Node + macOS + IDE patterns. `.venv/` ignored.
- `LICENSE` — MIT, © 2026 Aditya Chauhan.
- `.python-version` — `3.11`.
- `README.md` — minimal stub; full version comes later per the checklist.

**Learnings**

- **MIT for OSS dev tools is the path of least friction.** Companies have legal pre-clearance for MIT/BSD/Apache 2.0 deps. GPL-family licenses (especially AGPL) gate adoption — anyone embedding Loupe would have to reckon with copyleft. For a portfolio/adoption project, MIT removes friction.
- **Apache 2.0 is the other defensible choice.** Difference: Apache 2.0 has an explicit patent grant, useful if patent litigation is a real concern. Used by Kubernetes, OpenTelemetry. MIT is simpler and good enough.
- **Pinning Python version in `.python-version`.** Used by `pyenv` and most modern Python managers (`uv`, `rye`). Lets fresh clones get the same interpreter without trial-and-error. Pinning to a minor (3.11) — not patch (3.11.8) — is the right granularity: patches are forward-compatible, minor versions occasionally aren't.

**Interview questions**

1. MIT vs Apache 2.0 vs GPL — when do you pick which for an open-source library? *(MIT/BSD = permissive simplest; Apache 2.0 = permissive + patent grant; GPL/AGPL = copyleft, restricts proprietary embedding)*
2. Why pin Python to `3.11` and not `3.11.8`? *(reproducibility-vs-flexibility tradeoff; patch releases are bugfix-only and forward-compatible)*

---

## Sub-step C — `git init` + remote

**What changed**

- `git init -b main` (default branch `main`, not `master`).
- `git remote add origin https://github.com/Adityachauhan12/Loupe.git`.
- No push yet — initial commits stay local until item 2's stack is also in.

**Learnings**

- **`main` over `master`.** Industry default since ~2020. New repos default to `main`; older `master`-default repos slowly migrate.
- **Adding a remote without pushing.** Remotes are just named URLs locally. Adding one doesn't communicate over the network — it just lets you `git push origin main` later. Good for setting up the wiring before there's anything to share.

**Interview questions**

1. What's actually stored when you run `git remote add origin <url>`? *(an entry in `.git/config` — purely local metadata, no network traffic)*
