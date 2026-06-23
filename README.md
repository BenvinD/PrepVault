# PrepVault

**The open-source, local-first interview-prep tracker.** Pull every problem you've
solved on **LeetCode, HackerRank, CodeChef and HelloInterview** into one place,
get AI-written key insights, and let a **smart spaced-repetition queue** decide
what to revise next — so you actually *retain* what you grind. Run it entirely on
your own machine, or host it in the cloud for a whole community. Same codebase,
swappable backends.

> **Why the name?** PrepVault is a private *vault* for your interview prep — every
> problem you've ever solved locked in one place, then resurfaced by spaced
> repetition right before you'd forget it. It's your prep, on your machine,
> never lost.

<p align="left">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white">
  <img alt="SQLite / Postgres" src="https://img.shields.io/badge/DB-SQLite%20%7C%20Postgres-336791?logo=postgresql&logoColor=white">
  <img alt="License" src="https://img.shields.io/badge/License-AGPLv3-blue">
  <img alt="Self-hosted" src="https://img.shields.io/badge/Self--hosted-yes-brightgreen">
</p>

---

## The problem

If you're grinding LeetCode-style problems for interviews, you quickly hit three
walls:

1. **Your progress is scattered.** Solved lists live on LeetCode, HackerRank,
   HelloInterview, NeetCode… with no single view of what you've actually done.
2. **Solving once isn't remembering.** You crack a hard DP problem on Monday and
   blank on the same pattern three weeks later in a real interview.
3. **The tools that fix this own your data.** Most trackers are paid SaaS, or a
   hand-maintained spreadsheet that's stale the moment you close it.

## The solution

PrepVault is a single, self-hostable app that:

- **Syncs your solved problems** from multiple judges via their APIs (or manual
  entry where no API exists) and **de-duplicates** them into one dashboard.
- **Schedules revision with spaced repetition** — your confidence per problem
  drives *when* it resurfaces, so you spend time on what you're about to forget.
- **Unifies everything** — difficulty, status, language and topics from every
  judge are normalized into one consistent shape, so the UI looks the same no
  matter where the problem came from.
- **Stays yours** — local-first SQLite by default; nothing leaves your machine.
  Flip one env var to run it multi-user on Postgres for a shared instance.

---

## Features

| | |
|---|---|
| **Dashboard** | Totals, difficulty breakdown, top topics, "due to revise", last-30-days activity. |
| **Problems** | Searchable / filterable table; edit confidence, mark revised, delete, one-click AI insight, view submissions + code. |
| **Smart revision queue** | A prioritized queue served in small batches (5 at a time): due problems are ranked by how overdue they are, your weakest topics, confidence and difficulty. It surfaces your weak topics for interview prep, and you grade confidence (1–5) inline after each problem to reschedule it. |
| **Activity** | A combined, GitHub-style contribution graph across **every** provider, with streaks and per-judge breakdowns. |
| **Sync** | Pull your full solved list from LeetCode (cookie), HackerRank or CodeChef (public username + optional cookie). Connect **multiple accounts per judge**, resync any of them, and **unsync** one cleanly — removing only that account's problems, submissions and activity. |
| **AI insights** | A short "key insight" per problem from any OpenAI-compatible LLM you configure. |
| **Unified judges** | LeetCode, HackerRank, CodeChef and HelloInterview behind one `JudgeProvider` interface — adding Codeforces/AtCoder is a small, self-contained adapter. |
| **Backup & transfer** | Export your data to a JSON file — all of it, or just a **date range** via a date picker — and import it on another machine. Problems, submissions and activity merge with no duplicates (cookies excluded). |

---

## Quickstart (local mode — 30 seconds)

```bash
git clone https://github.com/BenvinD/PrepVault.git
cd PrepVault
```

With [**uv**](https://docs.astral.sh/uv/) (recommended — creates the virtualenv
and installs pinned deps from `uv.lock` automatically):

```bash
uv run uvicorn app.main:app --reload
```

…or with plain **pip**:

```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open **http://localhost:8000**. No login, no config — it just works on SQLite.

Go to the **Sync** tab, paste your `LEETCODE_SESSION` cookie (DevTools →
Application → Cookies → `leetcode.com`), and your solved problems flow into the
dashboard.

## Hosted mode (cloud, multi-user)

Accounts + Postgres via Docker:

```bash
cp .env.example .env          # set a strong SECRET_KEY (and LLM_API_KEY if you want AI)
docker compose up --build
```

Open **http://localhost:8000** → **Sign in / up** to create an account. Each
user's problems are isolated by `user_id`.

| Setting | Local | Cloud |
|---|---|---|
| `APP_MODE` | `local` | `cloud` |
| Storage | SQLite file (`prepvault.db`) | PostgreSQL |
| Auth | none (single user) | email + password (JWT) |
| Best for | personal use | shared / hosted instance |

The same codebase serves both — only configuration changes (the "BYO-backend"
philosophy popularized by tools like LangChain).

---

## Supported judges

| Judge | Auto-sync | Code tracking | How |
|---|---|---|---|
| **LeetCode** | Yes | Submissions + code fetched automatically | `LEETCODE_SESSION` cookie |
| **HackerRank** | Yes | Submissions + code with `_hrank_session` cookie | public **username** (+ optional cookie) |
| **CodeChef** | Yes | — (activity calendar only) | public **username** |
| **HelloInterview** | No public API | Manual — add a problem and paste your code | `+ Add problem` |

- **HackerRank** exposes no official public API, but its profile is backed by
  unauthenticated REST endpoints. Enter your public **username** to import your
  full solved list, real difficulty levels, topics and a daily activity
  calendar. Add your **`_hrank_session`** cookie and it behaves just like
  LeetCode — per-problem submissions load on click and you can view your code.
- **CodeChef** has no official public API either; its redesigned profile lists
  only contest problems by name. PrepVault instead walks the public recent-activity
  feed (`/recent/user`), which paginates through your whole submission history, to
  import every **accepted** problem with first-solved dates and languages, plus
  your daily contribution calendar. Only a public **username** is required (very
  prolific accounts may be limited to what the feed exposes).
- **HelloInterview** runs a private internal API with no public progress
  endpoint, so you track those by clicking **+ Add problem**, picking
  HelloInterview, and pasting your solution. Each manual solution is stored as a
  submission with its code, exactly like a synced one.

---

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| **API / web** | [FastAPI](https://fastapi.tiangolo.com/) + Uvicorn | Async Python, automatic OpenAPI docs at `/docs`. |
| **ORM / DB** | SQLAlchemy 2.x → **SQLite** (local) / **PostgreSQL** (cloud) | One model layer, two backends; zero-setup locally. |
| **Validation / config** | Pydantic v2 + pydantic-settings | Typed request/response schemas and `.env`-driven config. |
| **Auth** | bcrypt + JWT (`python-jose`) | Single implicit user locally; token auth in cloud. |
| **Frontend** | Zero-build SPA — HTML + Tailwind (CDN) + vanilla JS | No bundler, no `node_modules`; ships as static files. |
| **AI** | Any OpenAI-compatible chat API (OpenAI, OpenRouter, Groq, local) | Pluggable insights; entirely optional. |
| **Packaging / deps** | [uv](https://docs.astral.sh/uv/) (or pip) · Docker + docker-compose | `pyproject.toml` + `uv.lock` for reproducible installs; one command to stand up the cloud stack. |

---

## Architecture

```
app/
  main.py            FastAPI app, /api/* meta endpoints, serves the SPA
  config.py          APP_MODE / DATABASE_URL / REDIS_URL / LLM gateway / vault (env-driven)
  db.py              engine + session; runs Alembic migrations on startup
  migrations/        Alembic env + versioned migrations (baseline, …)
  models.py          User, Problem, Submission, JudgeCredential, ActivityDay, Job
  schemas.py         Pydantic request/response contracts
  auth.py            local single-user  ·  cloud JWT
  security/
    vault.py           envelope encryption for secrets (pluggable; KMS-backed)
  providers/         pluggable judge adapters
    base.py            JudgeProvider interface + capability flags
    leetcode.py        LeetCode (GraphQL)
    hackerrank.py      HackerRank (REST)
    codechef.py        CodeChef (recent-activity feed)
    hellointerview.py  manual-entry provider
    languages.py       canonical language normalization (cpp -> C++, …)
  services/
    sync.py            fetch solved problems, dedupe, enrich metadata
    submissions.py     fetch/store submissions + code, unified backfill
    activity.py        build the combined contribution calendar
    revision.py        spaced-repetition scheduling + smart priority queue + weak-topic scoring
    transfer.py        export/import with de-dup + newest-wins merge
    insights.py        AI key insights (via the LLM gateway only)
    stats.py           dashboard aggregates
    presentation.py    unification layer -> one shape for the frontend
    resilience.py      per-judge rate limit + circuit breaker + backoff
    jobs.py            background-job lifecycle helpers
    llm/               LLM gateway boundary (gateway.py + types.py)
  workers/           Arq queue, tasks, dispatcher (inline fallback when no Redis)
  routers/           REST API (problems, sync, submissions, auth, jobs, revision, transfer)
  static/            zero-build SPA (index.html + styles.css + app.js)
```

**Request flow**

```
Browser (SPA)  ─HTTP/JSON─▶  FastAPI routers ─▶ services ─▶ SQLAlchemy ─▶ SQLite/Postgres
                                   │
                                   ├─ providers/*  ──▶ LeetCode / HackerRank / CodeChef APIs
                                   └─ insights      ──▶ OpenAI-compatible LLM
```

**Two ideas do the heavy lifting:**

- **Provider pattern** (`providers/`): every judge implements a common
  `JudgeProvider` interface and advertises capabilities (`syncable`,
  `supports_submissions`, `supports_activity_calendar`, `supports_metadata`).
  Sync, dedup, scheduling, stats and the API don't care which judge produced a
  problem.
- **Unification layer** (`services/presentation.py`): raw judge data is
  normalized into one consistent shape — canonical difficulty/status/colors,
  unified language names (`cpp`/`python3` → `C++`/`Python`), split topics — so
  the frontend renders LeetCode and HackerRank problems identically.

### Data model (essentials)

- **User** — local sentinel user, or a real account in cloud mode.
- **Problem** — slug, title, difficulty, topics, confidence, `revisit`,
  `first_solved_at`, `last_revised`, `next_revision`, the source judge and the
  `account` it was synced from (so multiple accounts per judge unsync cleanly).
- **Submission** — per-attempt status, language, timestamp and code.
- **JudgeCredential** — per-user, per-judge session tokens (git-ignored, only
  ever sent to that judge's API).
- **ActivityDay** — per-day, per-judge counts powering the contribution graph.

---

## How spaced repetition works

Each problem carries a **confidence** score (1–5). When you mark a problem
revised you grade your confidence, and PrepVault computes the next review date —
low confidence resurfaces in days, high confidence in weeks. `last_revised`
automatically tracks your most recent accepted submission, and `next_revision`
is derived from it.

The **Revision** tab is a *smart, prioritized queue* rather than a flat due
list. It serves problems in small batches (5 at a time) ordered by a score that
blends:

- **Overdue-ness** — how long past `next_revision` the problem is.
- **Topic weakness** — topics where your average confidence is low (and topics
  flagged for revisit) are weighted up, so interview-critical weak spots come
  first. The queue response also returns your **weakest topics**.
- **Confidence** — lower-confidence problems rank higher.
- **Difficulty** — harder problems get a small boost.

You clear the queue batch by batch until it's empty, grading confidence inline
as you go.

---

## API

Interactive docs at **`/docs`**. Key endpoints:

```
GET    /api/config                       app mode + feature flags
GET    /api/stats                        dashboard aggregates
GET    /api/providers                    available judges + capabilities
GET    /api/activity                     combined contribution calendar
GET/POST/PATCH/DELETE /api/problems      problem CRUD
POST   /api/problems/{id}/revised        mark revised + grade confidence (reschedules)
POST   /api/problems/{id}/insight        enqueue an AI key insight (returns a job)
GET    /api/problems/{id}/submissions    submissions + code
GET    /api/revision/queue               prioritized due batch + weakest topics
POST   /api/sync                         pull solved problems from a judge (returns a job)
POST   /api/sync/backfill                backfill submissions/activity (returns a job)
GET    /api/jobs/{id}                    poll a background job's status + result
GET    /api/export[?from=&to=]           download your data as JSON (optional solved-date range)
POST   /api/import                       merge an exported file (de-duplicated)
POST   /api/auth/{register,login}        accounts (cloud mode)
```

Slow/external work (sync, backfill, insights) is dispatched as a **background
job**. In local mode the job runs inline and the response already carries the
result; in cloud mode (with `REDIS_URL`) it returns a queued job id and the
client polls `GET /api/jobs/{id}`.

---

## Configuration

All settings come from environment variables (or a `.env` file — see
`.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `APP_MODE` | `local` | `local` (SQLite, no auth) or `cloud` (Postgres, JWT). |
| `DATABASE_URL` | `sqlite:///prepvault.db` | Any SQLAlchemy URL; use a `postgresql+psycopg://…` for cloud. |
| `REDIS_URL` | unset | Enables the background worker. Unset → sync/backfill/insights run inline (local-friendly). |
| `SECRET_KEY` | dev value | JWT signing key — **set a strong one in cloud mode**. |
| `LLM_API_KEY` | unset | Enables AI insights (OpenAI-compatible). |
| `LLM_GATEWAY_URL` | `https://api.openai.com/v1` | LLM gateway base URL. Point at OpenRouter / Groq / a local server / our gateway. (`LLM_BASE_URL` still honored.) |
| `LLM_MODEL` | `gpt-4o-mini` | Model used for insights. |
| `LLM_EMBED_MODEL` | `text-embedding-3-small` | Embedding model (for the future second brain). |
| `VAULT_BACKEND` | `none` | `none` (store as-is) or `fernet` (encrypt judge cookies at rest). |
| `VAULT_KEY` | unset | Fernet key (from a KMS/secret manager) when `VAULT_BACKEND=fernet`. |

Schema is managed by **Alembic** — migrations run automatically on startup, and a
pre-Alembic database is adopted seamlessly with no manual steps.

---

## Adding a new judge

Implement `JudgeProvider`, return normalized `ProblemData`, and register it:

```python
class CodeforcesProvider(JudgeProvider):
    name = "codeforces"
    label = "Codeforces"
    color = "#1f8acb"

    def fetch_solved(self, credentials: dict) -> list[ProblemData]:
        ...
```

Register it in `app/providers/__init__.py`. Everything else — dedup, scheduling,
stats, the unified UI and the API — works unchanged.

---

## Security & privacy

Git-ignored and never committed: `cookies.json`, `.env`, `*.db`. Judge session
cookies are stored per-user and sent **only** to that
judge's API to fetch your data. In cloud mode, set a strong `SECRET_KEY` and put
it behind HTTPS.

---

## Roadmap

- More judges (Codeforces, AtCoder, NeetCode import).
- More export formats (Anki, Notion, CSV) on top of the built-in JSON backup/transfer.
- Configurable spaced-repetition policies (SM-2 / FSRS).
- Richer analytics: pattern mastery and progress trends (weak-topic detection
  already powers the smart revision queue).

## Contributing

Issues and PRs welcome — new judge providers, exports, and UI improvements are
great first contributions.

## License

[GNU AGPLv3](LICENSE). PrepVault is open-core: the self-hostable core is licensed
under the AGPLv3. Because the AGPL covers network use, anyone running a modified
*hosted* version must offer their source to its users.
