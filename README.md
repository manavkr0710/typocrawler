# Typo Crawler

A crawler that reads the public READMEs of large open-source orgs, such as `google`, `facebook`,
`microsoft`, `aws` and friends, hunts for genuine typos, verifies them, and publishes the
findings to a static dashboard.

## How it works
One CLI, six checkpointed stages. A rate limit or a CI timeout just means the next run resumes.

<img width="1021" height="263" alt="image" src="https://github.com/user-attachments/assets/c2ad5ce8-c96b-49ff-a333-b41b63c2570a" />

Two independent spell-checkers (`codespell` + `typos`) feed a heuristic filter; only the few
survivors are sent to an LLM for a context check, which keeps the noise, and the cost down.

## Tech Stack

* **Language:** **Python 3.12**, CLI built with **Typer**
* **Data layer:** **SQLAlchemy Core** + **Alembic** migrations over **SQLite**
* **GitHub integration:** **httpx** + **tenacity**, GitHub **GraphQL** (repo discovery) and **REST** (README fetch, ETag-cached)
* **Text processing:** **markdown-it-py** for extraction, **codespell** + **typos** for spell-checking
* **LLM verification:** pluggable backends (Groq / Gemini / Ollama), local **Ollama** (`qwen2.5:7b`) ran the initial bulk verification, **Gemini** runs the nightly incremental automation*
* **Dashboard:** vanilla **HTML / CSS / JS**, no framework, no build step
* **CI/CD & hosting:** **GitHub Actions** (nightly cron) deploying to **GitHub Pages**
* **Testing:** **pytest** + **ruff**



## System Diagrams (C1-C3)

### C1 (System Context Diagram)

Who touches the system and which outside services it depends on. One software system, two kinds of people, three external systems, all of them free to use.

<img width="796" height="574" alt="image" src="https://github.com/user-attachments/assets/19445e8c-43d9-44a8-a8e0-df2dac1c0321" />


### C2 (Container Diagram)

Zoom into the system. GitHub Actions is the only compute: it runs the crawler, then the report builder, and restores/saves typos.db across runs via a dedicated git branch, since the runner itself keeps nothing between invocations.

<img width="654" height="544" alt="image" src="https://github.com/user-attachments/assets/ca7bed93-4dd4-476c-9163-10b4e27ad97a" />

### C3 (Component Diagram)
The pipeline. Each stage checkpoints to SQLite, so a run interrupted by a rate limit or a CI timeout resumes where it stopped. Two independent spell-checkers feed one heuristic filter; only the few survivors reach the LLM.

<img width="603" height="604" alt="image" src="https://github.com/user-attachments/assets/88552fb4-8e0d-4030-adf1-3485a066433c" />


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
access is enough (see [`.env.example`](.env.example)).

### Verification provider

`verify` needs an LLM. In order of preference:

| Provider | Setup | Notes |
|---|---|---|
| Groq | `GROQ_API_KEY` in `.env` | Fast; needs a small credit purchase as of 2025 |
| Gemini | `GEMINI_API_KEY` in `.env` | Free but ~20 requests/day on current models |
| Ollama | install [ollama](https://ollama.com), `ollama pull qwen2.5:7b` | Local, unlimited, $0. Use a 7B+ model, smaller ones misalign batched answers, so pass `--batch 1` with a 3B model |

`typocrawler verify` auto-picks whichever is configured. `--reset` clears all verdicts and starts over.

Configure targets in [`config/orgs.yml`](config/orgs.yml).

## Automation (nightly crawl + GitHub Pages)

[`.github/workflows/crawl.yml`](.github/workflows/crawl.yml) runs the whole pipeline
(`discover → fetch → check → verify → report`) every night and publishes `site/` to GitHub
Pages - free, no server. A big initial backlog (like the first full crawl) is still best run
locally with Ollama; the nightly job is sized for small incremental deltas, verified via Gemini's
free tier (~20 req/day is plenty once the backlog is cleared).

**`typos.db` lives on a `data` branch**, not `main`, each run force-pushes a single fresh commit
there instead of piling up binary diffs in the source history. The workflow restores it at the
start of each run and re-saves it at the end, so progress (discovery, fetches, verify verdicts)
persists between runs.

**One-time setup:**
1. **Settings → Pages → Build and deployment → Source → GitHub Actions.**
2. **Settings → Secrets and variables → Actions**, add:
   - `CRAWLER_GH_TOKEN` - a GitHub PAT with "Public Repositories (read-only)" access (same kind as your local `.env`'s `GITHUB_TOKEN`; the automatic `GITHUB_TOKEN` secret name is reserved by GitHub, hence the different name here)
   - `GEMINI_API_KEY` - from [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
3. Trigger it once by hand: **Actions → Crawl and publish → Run workflow**, or just wait for the nightly schedule.

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


## License

MIT

