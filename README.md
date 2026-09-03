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

typocrawler init-db              # create the SQLite schema (typos.db)
typocrawler orgs                 # show the resolved target org list
typocrawler discover             # (stint 2) enumerate org repos
```

Configure targets in [`config/orgs.yml`](config/orgs.yml).

## Project layout

| Path | Purpose |
|---|---|
| `config/orgs.yml` | Target orgs + per-org overrides |
| `src/typocrawler/config.py` | Config schema and loader |
| `src/typocrawler/db/` | SQLAlchemy Core schema + engine |
| `src/typocrawler/cli.py` | `typocrawler` CLI (Typer) |
| `migrations/` | Alembic migrations |
| `tests/` | pytest suite |

## Build status

Built in sequential "stints", one branch/PR each:

- [x] **Stint 1 — skeleton:** tooling, config, DB schema, CLI stubs
- [ ] Stint 2 — repo discovery (GitHub GraphQL)
- [ ] Stint 3 — README fetch + text extraction
- [ ] Stint 4 — spell-checkers
- [ ] Stint 5 — heuristic filter
- [ ] Stint 6 — LLM verification
- [ ] Stint 7 — static dashboard
- [ ] Stint 8 — GitHub Actions automation
- [ ] Stint 9 — polish

## License

MIT

