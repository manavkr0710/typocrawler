# opensource-readme-typo-crawler

A crawler that reads the public READMEs of large open-source orgs — `google`, `facebook`,
`microsoft`, `aws` and friends — hunts for genuine typos, verifies them, and publishes the
findings to a static dashboard.

Design goal: **run the whole thing on free tiers.** No server, no managed database, no paid API.
A nightly GitHub Actions job builds a SQLite file and a static site, and GitHub Pages serves it.

## How it works

```
org list  ->  discover repos  ->  fetch READMEs  ->  extract prose  ->  spell-check  ->  heuristics  ->  LLM verify  ->  store  ->  build report
config     GraphQL + filters    ETag-cached       strip code/links   codespell +      allowlists,     free-tier       SQLite    Jinja + datasette-lite
                                                                     typos            CamelCase, ...   (batched)
```

Two independent spell-checkers (`codespell` + `typos`) feed a heuristic filter; only the few
survivors are sent to an LLM for a context check, which keeps the noise — and the cost — down.

Full architecture, including C4 diagrams and the SQLite-vs-Postgres rationale, is in
[`docs/architecture.md`](docs/architecture.md).

## Quickstart

```bash
pip install -e ".[dev]"
cp .env.example .env             # then fill in GITHUB_TOKEN

typocrawler init-db              # create the SQLite schema (typos.db)
typocrawler orgs                 # show the resolved target org list
typocrawler discover             # enumerate org repos (needs GITHUB_TOKEN)
typocrawler fetch                # pull READMEs + extract prose (resumable, --limit N)
typocrawler check                # run codespell + typos + heuristic filter (resumable)
typocrawler filter               # re-run heuristics after editing config/allowlist.txt
typocrawler verify               # LLM confirms each survivor (needs GROQ_API_KEY / GEMINI_API_KEY / Ollama)
typocrawler findings --confirmed # the final list of genuine typos
typocrawler report               # build the static dashboard into site/
```

Preview the dashboard locally: `python -m http.server -d site` then open <http://localhost:8000>.

If you have an existing `typos.db` from an earlier stint, run `alembic upgrade head` once to
pick up new columns.

`GITHUB_TOKEN` is read from `.env` automatically (gitignored, never commit it), or from a real
environment variable, or via `--token`. A fine-grained PAT with "Public Repositories (read-only)"
access is enough — see [`.env.example`](.env.example).

### Verification provider

`verify` needs an LLM. In order of preference:

| Provider | Setup | Notes |
|---|---|---|
| Groq | `GROQ_API_KEY` in `.env` | Fast; needs a small credit purchase as of 2025 |
| Gemini | `GEMINI_API_KEY` in `.env` | Free but ~20 requests/day on current models |
| Ollama | install [ollama](https://ollama.com), `ollama pull qwen2.5:7b` | Local, unlimited, $0. Use a 7B+ model — smaller ones misalign batched answers, so pass `--batch 1` with a 3B model |

`typocrawler verify` auto-picks whichever is configured. `--reset` clears all verdicts and starts over.

Configure targets in [`config/orgs.yml`](config/orgs.yml).

## Automation (nightly crawl + GitHub Pages)

[`.github/workflows/crawl.yml`](.github/workflows/crawl.yml) runs the whole pipeline
(`discover → fetch → check → verify → report`) every night and publishes `site/` to GitHub
Pages — free, no server. A big initial backlog (like the first full crawl) is still best run
locally with Ollama; the nightly job is sized for small incremental deltas, verified via Gemini's
free tier (~20 req/day is plenty once the backlog is cleared).

**`typos.db` lives on a `data` branch**, not `main` — each run force-pushes a single fresh commit
there instead of piling up binary diffs in the source history. The workflow restores it at the
start of each run and re-saves it at the end, so progress (discovery, fetches, verify verdicts)
persists between runs.

**One-time setup:**
1. **Settings → Pages → Build and deployment → Source → GitHub Actions.**
2. **Settings → Secrets and variables → Actions**, add:
   - `CRAWLER_GH_TOKEN` — a GitHub PAT with "Public Repositories (read-only)" access (same kind as your local `.env`'s `GITHUB_TOKEN`; the automatic `GITHUB_TOKEN` secret name is reserved by GitHub, hence the different name here)
   - `GEMINI_API_KEY` — from [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
3. Trigger it once by hand: **Actions → Crawl and publish → Run workflow** — or just wait for the nightly schedule (07:11 UTC).

## Project layout

| Path | Purpose |
|---|---|
| `config/orgs.yml` | Target orgs + per-org overrides |
| `src/typocrawler/config.py` | Config schema and loader |
| `src/typocrawler/db/` | SQLAlchemy Core schema + engine + upsert/query layers |
| `src/typocrawler/github/` | GitHub client + repo discovery + README fetch |
| `src/typocrawler/text/` | Markdown → prose extraction |
| `src/typocrawler/check/` | codespell + typos runners, cross-referencing, heuristic filters |
| `src/typocrawler/verify/` | pluggable LLM back-ends + prompt/parse for verification |
| `src/typocrawler/report/` | static dashboard generator + HTML/CSS/JS assets |
| `src/typocrawler/cli.py` | `typocrawler` CLI (Typer) |
| `migrations/` | Alembic migrations |
| `tests/` | pytest suite |

## Build status

Built in sequential "stints", one branch/PR each:

- [x] **Stint 1 — skeleton:** tooling, config, DB schema, CLI stubs
- [x] **Stint 2 — repo discovery:** GitHub GraphQL client, pagination, filtering, DB upserts
- [x] **Stint 3 — README fetch + extraction:** ETag-cached REST fetch, resumable, markdown → prose
- [x] **Stint 4 — spell-checkers:** codespell + typos over the prose, cross-referenced into findings
- [x] **Stint 5 — heuristic filter:** drop acronyms, identifiers, table fragments, allowlisted words
- [x] **Stint 6 — LLM verification:** pluggable Groq/Gemini/Ollama pass confirms real typos in context
- [x] **Stint 7 — static dashboard:** `report` builds a filterable, theme-aware site into `site/`
- [x] **Stint 8 — automation:** nightly GitHub Actions run + Pages deploy, `typos.db` persisted on a `data` branch
- [ ] Stint 9 — polish

## License

MIT

