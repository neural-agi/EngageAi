# EngageAI System Overview

## Scope

This document is a codebase-level mental model of `engageai` as it exists in the repository today.

It is based on direct inspection of:

- all authored source files returned by `rg --files`
- root configuration and docs files
- runtime state files under `backend/data`
- the current frontend/backend entry points
- the existing pipeline test suite

Generated or vendor artifacts also present in the repository state were classified separately:

- `frontend/node_modules/`
- `frontend/.next/`
- `backend/.pytest_cache/`
- `backend/__pycache__/`
- `backend/sessions/`
- root `.env`

Those artifacts are part of the runtime/developer environment, but they are not application-authored logic, so they are documented as artifacts rather than unpacked line-by-line.

## 1. Product Summary

### What the product does

EngageAI is a full-stack system intended to automate LinkedIn engagement decisions and comment drafting.

In real-world terms, the product tries to do this:

1. load a saved LinkedIn session for an account
2. fetch candidate posts from a LinkedIn feed
3. decide which posts are relevant enough to engage with
4. draft multiple comment variants in different voices/styles
5. filter and rank those variants
6. simulate posting the selected comment
7. remember what was generated/executed so later runs are less repetitive

Today, the system is only partially real:

- the API, dashboard, orchestration, memory, persona, and scheduling layers are real
- the execution layer is simulation-only
- the scraper has a Playwright implementation, but real scraping falls back to placeholder data in common conditions
- Postgres/Redis/Celery are scaffolded but not operationally integrated into the runtime path

### Core architecture

- Frontend: Next.js 14 App Router dashboard
- Backend: FastAPI
- Agent pipeline: `AnalystAgent -> WriterAgent -> CriticAgent -> ExecutorAgent`
- Scraping: `LinkedInScraper` service
- Scheduling: CLI-driven `SchedulerService`
- State/memory: JSON file via `MemoryStore`
- AI access: low-level `AIProvider`

### Important architectural truth

The documented agent pipeline in `AGENTS.md` says `Scout -> Analyst -> Writer -> Critic -> Executor`.

The actual runtime pipeline is:

`SessionManager -> LinkedInScraper -> AnalyticsService -> AnalystAgent -> WriterAgent -> CriticAgent -> ExecutorAgent -> ExecutionService -> MemoryStore`

`ScoutAgent` exists but is not used.

## 2. System Diagram

### Main request path

```text
User
  |
  v
Next.js Dashboard --------------.
  |                             |
  | POST /run                   | CLI: backend/run_pipeline.py
  v                             |
FastAPI (app.main)              |
  |                             |
  v                             |
routers/campaigns.py            |
  |                             |
  v                             |
run_pipeline._run_pipeline <----'
  |
  v
EngagementPipeline
  |
  +--> SessionManager.get_session(account_id)
  |
  +--> LinkedInScraper.fetch_feed()
  |
  +--> AnalyticsService.compute_viral_score(post)
  |
  +--> AnalystAgent.analyze(post_text, niche_text, engagement_metrics)
  |
  +--> WriterAgent.draft(post_text, context)
  |
  +--> CriticAgent.review(variants)
  |
  +--> ExecutorAgent.execute(post_id, best_comment + persona)
          |
          v
      ExecutionService.simulate_post_comment(...)
          |
          v
      MemoryStore.remember_execution(...)
```

### Continuous mode path

```text
CLI --continuous
  |
  v
SchedulerService.run_forever(...)
  |
  +--> daily limit check
  +--> inactivity skip check
  +--> _run_pipeline(...)
  +--> persist last_run_timestamp
  +--> sleep with jitter
```

## 3. Entry Points And Control Plane

### Backend HTTP entry point

File: `backend/app/main.py`

Responsibilities:

- creates the FastAPI app
- configures structured logging on startup
- validates required environment variables on startup
- installs CORS middleware
- mounts the routers
- converts validation, HTTP, and unexpected exceptions into structured JSON

Routes mounted:

- `GET /`
- `GET /health`
- `POST /run`
- `POST /campaigns/run`
- `POST /campaigns/` placeholder

### API routing layer

File: `backend/app/routers/campaigns.py`

Actual runtime behavior:

- `/run` and `/campaigns/run` both call the same private helper `_execute_pipeline()`
- `_execute_pipeline()` delegates to `run_pipeline._run_pipeline(...)`
- this means the HTTP API and CLI share the same orchestration wrapper, including mock-mode monkeypatching and mock fallback behavior

### CLI entry point

File: `backend/run_pipeline.py`

Capabilities:

- single execution
- mock mode
- continuous mode
- persona selection

Important flags:

- positional `account_id`
- positional `niche_text`
- `--persona`
- `--mock`
- `--continuous`
- `--interval-minutes`
- `--daily-limit`

### Frontend entry point

File: `frontend/app/dashboard/page.tsx`

Responsibilities:

- collect `account_id`
- collect `niche_text`
- toggle `mock` mode
- call backend `POST /run`
- display result cards

The frontend is a thin UI over the backend pipeline and does not contain business logic for the pipeline itself.

## 4. High-Level Data Flow

### HTTP flow

```text
Dashboard form
  -> frontend/lib/api-client.ts runPipeline()
  -> POST http://localhost:8000/run
  -> FastAPI request validation
  -> run_pipeline._run_pipeline()
  -> EngagementPipeline.run()
  -> response mapped into PipelineResponse
  -> dashboard renders cards
```

### Per-post flow inside the pipeline

For each scraped post:

1. extract `content`
2. compute viral score from metrics
3. compute relevance and engagement heuristic
4. skip if analyst returns `"ignore"`
5. generate comment variants
6. critique/filter/rank variants
7. pick one variant using weighted randomness from the top 3
8. simulate execution
9. persist execution/style/memory effects
10. return result record

### Result record shape

Each successful processed result in the pipeline is returned as:

```json
{
  "post": {
    "platform_post_id": "string",
    "author": "string",
    "content": "string",
    "likes": 0,
    "comments": 0,
    "hours_since_post": 0,
    "url": "string"
  },
  "analysis": {
    "relevance_score": 0.0,
    "engagement_score": 0.0,
    "final_score": 0.0,
    "decision": "engage"
  },
  "analytics": {
    "viral_score": 0.0
  },
  "best_comment": {
    "text": "string",
    "style": "string",
    "confidence": 0.0,
    "score": 0.0
  },
  "ranked_comments": [],
  "execution": {
    "status": "success | skipped | duplicate",
    "message": "string"
  }
}
```

## 5. Active Runtime Modules

This section distinguishes modules that materially affect runtime behavior from scaffolded files.

### Active backend runtime modules

- `backend/app/main.py`
- `backend/app/config.py`
- `backend/app/routers/health.py`
- `backend/app/routers/campaigns.py`
- `backend/app/schemas/common.py`
- `backend/app/schemas/campaign.py`
- `backend/app/orchestrator/pipeline.py`
- `backend/app/agents/analyst_agent.py`
- `backend/app/agents/writer_agent.py`
- `backend/app/agents/critic_agent.py`
- `backend/app/agents/executor_agent.py`
- `backend/app/core/memory_store.py`
- `backend/app/core/persona_engine.py`
- `backend/app/services/ai/provider.py`
- `backend/app/services/ai/embedding_service.py`
- `backend/app/services/scoring/relevance_scorer.py`
- `backend/app/services/analytics/analytics_service.py`
- `backend/app/services/scraping/linkedin_scraper.py`
- `backend/app/services/security/session_manager.py`
- `backend/app/services/behavior/execution_service.py`
- `backend/app/services/behavior/scheduler_service.py`
- `backend/app/observability/logging.py`
- `backend/run_pipeline.py`

### Active frontend runtime modules

- `frontend/app/layout.tsx`
- `frontend/app/dashboard/page.tsx`
- `frontend/components/app-shell.tsx`
- `frontend/components/nav-link.tsx`
- `frontend/components/page-header.tsx`
- `frontend/lib/api-client.ts`
- `frontend/app/globals.css`
- `frontend/tailwind.config.js`
- `frontend/postcss.config.js`

### Placeholder or mostly scaffolded backend modules

- `backend/app/agents/scout_agent.py`
- `backend/app/agents/orchestrator.py`
- `backend/app/core/safety_filter.py`
- `backend/app/core/risk_engine.py`
- `backend/app/core/trend_engine.py`
- `backend/app/core/decision_engine.py`
- `backend/app/services/analytics/engagement_analyzer.py`
- `backend/app/services/analytics/metrics_service.py`
- `backend/app/services/analytics/opportunity_scoring.py`
- `backend/app/services/behavior/tone_analyzer.py`
- `backend/app/services/behavior/engagement_policy.py`
- `backend/app/database.py`
- `backend/app/models/*`
- `backend/app/workers/*`
- `backend/app/observability/metrics.py`

These files mostly establish names and intended structure, not completed functionality.

## 6. Agent Pipeline Breakdown

## 6.1 Scraper Layer

### Actual runtime component

File: `backend/app/services/scraping/linkedin_scraper.py`

This is the real scraper layer. There is no separate runtime `ScoutAgent`.

### Responsibility

- launch a Playwright browser session
- apply session cookies
- load the LinkedIn feed or creator page
- collect post containers
- extract structured post fields
- optionally post a comment

### Inputs

Constructor:

- `session_cookies: list[dict[str, Any]]`
- `proxy: str | None`
- `selectors: dict[str, str] | None`
- `headless: bool`
- `timeout_ms: int`

Key method:

- `fetch_feed(max_posts: int = 20) -> list[dict[str, Any]]`

### Outputs

Structured post list shaped like:

```json
{
  "author": "string",
  "content": "string",
  "likes": 0,
  "comments": 0,
  "hours_since_post": 1,
  "url": "string",
  "platform_post_id": "string"
}
```

### Dependencies

- Playwright async API if installed
- session cookies from `SessionManager`
- selector map passed at runtime

### Real behavior today

`fetch_feed()` falls back to `fetch_placeholder_real_data()` when:

- Playwright is not installed
- required selectors are missing
- scraping throws an exception

Since the repository does not provide selector configuration anywhere, and `backend/requirements.txt` does not declare `playwright`, the common behavior in a clean environment is fallback, not live scraping.

### Failure points

- missing Playwright dependency
- missing browser binaries
- missing selectors
- invalid or expired LinkedIn cookies
- LinkedIn DOM changes
- page timeout
- anti-bot detection

### Additional note

`post_comment()` exists but `ExecutorAgent` does not use it. Live posting is not wired.

## 6.2 AnalystAgent

File: `backend/app/agents/analyst_agent.py`

### Responsibility

- determine whether a post is worth engaging with
- combine semantic relevance and a lightweight engagement heuristic

### Input

```json
{
  "post_text": "string",
  "niche_text": "string",
  "engagement_metrics": {
    "likes": 0,
    "comments": 0,
    "time": 0
  }
}
```

### Output

```json
{
  "relevance_score": 0.0,
  "engagement_score": 0.0,
  "final_score": 0.0,
  "decision": "engage | ignore"
}
```

### Dependencies

- `RelevanceScorer`
  - `EmbeddingService`
    - `AIProvider`

### Logic

- relevance score comes from cosine similarity between embeddings
- engagement score is `(likes + comments * 2) / max(time, 1)`
- engagement score is normalized by dividing by `25.0` and clamped to `0..1`
- final score is `0.7 * relevance + 0.3 * engagement`
- decision threshold is `final_score >= 0.5`

### Failure points

- if embeddings are unavailable, relevance becomes `0.0`
- with relevance at `0.0`, final score cannot exceed `0.3`, so no real post can naturally reach `"engage"`
- this means real-mode usefulness is heavily dependent on OpenAI embedding availability

### Missing pieces

- no tone analysis
- no intent analysis
- no niche taxonomy
- no risk/safety scoring

## 6.3 WriterAgent

File: `backend/app/agents/writer_agent.py`

### Responsibility

- generate multiple candidate comments
- vary style and tone
- avoid repetition within the current run and across previous runs
- inject persona context into prompt/fallback generation

### Input

- `post_text: str`
- `context: dict`

The pipeline currently passes:

- `topic`
- `author`
- `url`
- `viral_score`
- `persona`
- `persona_prompt`
- `style_usage`

### Output

List of variant dicts shaped like:

```json
{
  "text": "string",
  "style": "question | insight | contrarian | bold statement | storytelling",
  "confidence": 0.0,
  "reference_terms": []
}
```

### Dependencies

- `AIProvider`
- `MemoryStore`

### Generation path

1. build a prompt that asks for 5 styles exactly once
2. call `AIProvider.generate_structured(prompt)`
3. normalize structured variants if present
4. deduplicate against:
   - `_generated_comment_texts` for this process/run
   - `MemoryStore.get_generated_comments()` across runs
5. adjust confidence using style rotation + persona preferred styles
6. if fewer than 5 variants survive, generate deterministic persona-aware fallback variants
7. persist all returned variant texts into memory

### Persona influence

Persona affects:

- prompt wording
- preferred styles
- fallback template wording
- vocabulary and signature

### Failure points

- `AIProvider.generate_structured()` may return only `{"content": prompt}` in fallback mode, producing no structured variants
- fallback variants are deterministic enough that repetition risk still exists, especially with narrow niches
- memory is global, so deduplication affects all accounts, not just one account/campaign

### Design weakness

Writer persists all generated variants, not just chosen comments. That means candidate text is “burned” even if it was never executed.

## 6.4 CriticAgent

File: `backend/app/agents/critic_agent.py`

### Responsibility

- filter unsafe/spammy comments
- score comment quality
- rank variants
- choose one final comment with slight randomness

### Input

List of variant dicts from `WriterAgent`

### Output

```json
{
  "best_variant": {
    "text": "string",
    "style": "string",
    "confidence": 0.0,
    "reference_terms": [],
    "score": 0.0
  },
  "ranked_variants": []
}
```

### Dependencies

No service dependencies. Entirely local heuristics.

### Logic

Filters:

- reject empty or very short text
- reject obvious spam markers
- reject repeated punctuation patterns
- reject comments already selected earlier in the same process via `_selected_comment_texts`

Scoring:

- length quality
- clarity
- confidence
- originality
- specificity

Selection:

- sort descending by score
- choose from top 3 via weighted random selection

### Failure points

- no toxicity model
- no semantic safety check
- no persona/brand fit enforcement
- repeat blocking only tracks comments selected in the current process, not across restarted processes

## 6.5 ExecutorAgent

File: `backend/app/agents/executor_agent.py`

### Responsibility

- validate the selected comment payload
- enforce per-run execution limit
- call the execution layer
- retry transient failures

### Input

```json
{
  "post_id": "string",
  "comment": {
    "text": "string",
    "style": "string",
    "confidence": 0.0,
    "persona": {}
  }
}
```

### Output

```json
{
  "status": "success | skipped | duplicate",
  "message": "string"
}
```

Additional fields are included when `ExecutionService` returns them.

### Dependencies

- `ExecutionService`
- `MemoryStore`

### Runtime behavior

- default mode is simulation-only
- max attempts: `3`
- retry delay: `1s`
- max comments per run: `5`

### Failure points

- real posting is not implemented at all
- any final failure returns `status="skipped"` rather than a distinct failure state
- per-run limit is enforced only for one pipeline instance, not globally

## 7. Memory System

File: `backend/app/core/memory_store.py`

### Storage model

The active memory system is JSON-file based, not database-backed.

Storage file:

- `backend/data/engagement_memory.json`

Default schema:

```json
{
  "generated_comments": [],
  "style_usage": {},
  "last_persona_id": null,
  "execution_history": [],
  "last_run_timestamp": null
}
```

### What is stored

- normalized generated comments
- style usage counters
- last selected persona id
- execution history
- last scheduler run timestamp

### Read/write flow

#### Generated comment memory

- writer loads historical normalized comments during initialization
- writer persists returned variants with `remember_generated_comments()`

#### Style rotation memory

- pipeline records the selected `best_variant.style` with `increment_style_usage()`

#### Persona persistence

- persona engine stores `last_persona_id`

#### Execution persistence

- execution service writes a record only when simulated execution succeeds
- duplicate prevention uses `has_execution_for_post(post_id)`

#### Scheduler persistence

- scheduler reads `last_run_timestamp`
- scheduler writes `last_run_timestamp` after a successful scheduled run

### Duplicate prevention logic

- comments: based on normalized text
- executions: based on exact `post_id`

### Limitations

1. single JSON file for multiple concerns
2. only in-process `threading.Lock`
3. no cross-process locking
4. no file-transaction safety
5. no per-account partitioning
6. no per-campaign partitioning
7. no TTL or cleanup beyond last-2000 truncation
8. memory is globally shared across all users/runs in the same repo

### Scaling risk

If this service is ever run with:

- multiple API workers
- multiple containers
- both API and scheduler active at once

then memory consistency becomes unreliable.

## 8. Scheduler System

File: `backend/app/services/behavior/scheduler_service.py`

### What it is

This is not a job scheduler in the queueing sense. It is an in-process async loop.

It is only used from:

- `backend/run_pipeline.py --continuous`

It is not exposed through FastAPI and it is not backed by Celery.

### How jobs are created

No job objects are created. The CLI passes a lambda:

```text
lambda: _run_pipeline(...)
```

The scheduler repeatedly calls that function.

### Trigger model

`run_forever(run_once, interval_minutes)`:

1. check daily limit
2. maybe skip for inactivity
3. otherwise execute one run
4. sleep for jittered interval
5. repeat forever

### Randomness and humanization

- interval jitter ratio default: `0.2`
- actual next interval: base interval * random between `0.8` and `1.2`
- inactivity probability default: `0.2`

### Daily limit

- default `daily_comment_limit = 20`
- implemented as count of execution records for the current day
- only applies when using the scheduler
- does not apply to API-triggered or one-shot CLI runs

### Last-run persistence

- stored via `MemoryStore.set_last_run_timestamp()`

### Failure handling

- if `run_once()` raises, scheduler logs and continues
- there is no circuit breaker
- there is no escalating backoff
- there is no alerting
- there is no overlap control beyond single-threaded loop execution

### Operational limitations

- no distributed locking
- no cron expression support
- no job persistence
- no retry queue
- no worker fleet

## 9. Execution Layer

Files:

- `backend/app/agents/executor_agent.py`
- `backend/app/services/behavior/execution_service.py`

### What execution means today

Execution means simulated posting, not real posting.

`ExecutionService.simulate_post_comment(...)`:

1. checks if the `post_id` already exists in execution history
2. if yes, returns `status="duplicate"`
3. otherwise waits a random `2-10` seconds
4. stores execution record in memory
5. returns `status="success"`

### What gets logged/stored

- `post_id`
- `comment_text`
- `persona`
- `timestamp`

### Duplicate prevention

Duplicate prevention is exact-match on `post_id`.

This prevents re-executing the same stored post id, but does not protect against:

- equivalent posts with different ids
- URL aliases
- repost/quote variants

### Limits and safeguards

Per pipeline instance:

- max comments per run: `5`
- validation for `post_id`, `text`, `style`, `confidence`
- retry attempts: `3`

Global safety:

- none beyond simulation and duplicate check

### Important constraint

Even in “real mode,” execution is still simulated. There is no live posting integration.

## 10. Persona System

File: `backend/app/core/persona_engine.py`

### Persona inventory

There are 35 personas total across 4 archetypes:

- analytical expert: 9 personas
- bold contrarian: 9 personas
- friendly storyteller: 9 personas
- industry insider: 8 personas

Each persona contains:

- `id`
- `name`
- `archetype`
- `tone`
- `phrasing`
- `vocabulary`
- `preferred_styles`
- `signature`

### How a persona is assigned

`EngagementPipeline.run(..., persona_name=None)` calls:

```text
selected_persona = persona_engine.select_persona(persona_name)
```

Behavior:

- if `persona_name` matches by id or name, that persona is used
- otherwise a random persona is selected
- the engine tries not to reuse the last persona id if more than one persona exists
- selected persona id is persisted in memory as `last_persona_id`

### Where persona is injected

Pipeline passes persona context into writer via `_build_writer_context()`:

- `persona`
- `persona_prompt`

Writer then uses persona in:

- prompt generation
- style rotation bias
- deterministic fallback comment templates

Execution also receives persona:

- pipeline passes `{**best_variant, "persona": selected_persona}` into executor
- execution history stores persona name

### Whether persona persistence exists

Yes, but only minimally:

- persisted field: `last_persona_id`
- scope: global repository state
- not scoped per account
- not scoped per campaign

### Limitation

Persona persistence influences next selection but does not create a persistent identity model for an account over time.

## 11. Frontend <-> Backend Interaction

## API structure

Frontend client file: `frontend/lib/api-client.ts`

Configured base URL:

```text
process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"
```

Implemented client calls:

- `getHealth() -> GET /health`
- `runPipeline(...) -> POST /run`

### Request contract

```json
{
  "account_id": "string",
  "niche_text": "string",
  "mock": true
}
```

### Response contract

```json
{
  "account_id": "string",
  "niche_text": "string",
  "mock": true,
  "result_count": 0,
  "results": []
}
```

### Frontend rendering behavior

The dashboard renders:

- result count
- per-result author
- post content
- likes
- comments
- best comment text
- viral score

It does not render:

- ranked comment details
- execution status explicitly
- persona used
- analysis scores

### Pages status

- `dashboard`: functional
- `campaigns`: placeholder
- `analytics`: placeholder
- `settings`: placeholder
- root `/`: placeholder landing page

## 12. Security And Safety

## Authentication

There is no user authentication or authorization.

Implications:

- any caller that can reach the backend can invoke `/run`
- there is no account ownership check
- there is no session-level authorization model

## CORS

FastAPI adds `CORSMiddleware` with origins from environment. Default example:

- `http://localhost:3000`

Methods and headers are fully open.

## Session handling

File: `backend/app/services/security/session_manager.py`

What it does:

- stores cookie payloads on local disk under `./sessions`
- derives a per-account key using PBKDF2-HMAC-SHA256
- encrypts cookies using a custom XOR keystream derived from SHA256

Important security observation:

- this is custom encryption, not authenticated encryption
- no integrity tag or MAC is stored
- ciphertext tampering is not cryptographically detected
- fallback secret source is `username:hostname` if `SESSION_MANAGER_SECRET` is absent

This is not production-grade cryptography.

## Safety/risk enforcement

Stated in docs:

- `AGENTS.md` says safety first, risk gating, no blind automation

Actual code:

- `safety_filter.py`, `risk_engine.py`, and `decision_engine.py` are not wired into the runtime pipeline
- critic performs only basic phrase filtering
- executor only simulates, which is currently the main safety barrier

## Rate limiting / anti-ban

Exists partially:

- scraper human-like delays
- typing delays in Playwright
- scheduler interval jitter
- scheduler inactivity skips
- execution delay simulation

Missing:

- request rate limiting at API layer
- account-level quotas for API-triggered runs
- dynamic ban detection
- proxy/session rotation strategy
- user-agent strategy
- robust risk gating before execution

## Vulnerabilities and weak points

- unauthenticated public pipeline trigger
- silent fallback from real mode to mock mode
- custom crypto
- global shared memory file
- no audit boundary between accounts

## 13. Deployment Readiness

## Environment handling

File: `backend/app/config.py`

Required variables enforced by startup validation:

- `OPENAI_API_KEY`
- `SESSION_MANAGER_SECRET`

Optional for now:

- `DATABASE_URL`

Other important config:

- `BACKEND_CORS_ORIGINS`
- `NEXT_PUBLIC_API_BASE_URL`
- OpenAI model/base URL/timeouts/retries

### Where validation happens

- FastAPI startup (`main.py`)
- CLI startup (`run_pipeline.main()`)

### Where validation does not happen automatically

- direct import/use of internal classes outside the app/CLI entrypoints

## Backend startup

Backend Docker command:

```text
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Dev compose command:

```text
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Import/path layout is consistent with running from `backend/` or from Docker `WORKDIR /app`.

## Frontend startup

Frontend scripts:

- `npm run dev`
- `npm run build`
- `npm run start`

API base URL is configurable via:

- `NEXT_PUBLIC_API_BASE_URL`

## Docker support

Files:

- `docker-compose.yml`
- `docker-compose.prod.yml`
- `backend/Dockerfile`
- `frontend/Dockerfile`

Compose services declared:

- `postgres`
- `redis`
- `backend`
- `frontend`

### Operational reality

- Postgres and Redis start, but the active runtime path does not use them in application logic
- there is no Celery worker service in the compose files
- backend requirements do not include Playwright
- backend Dockerfile does not install browser binaries

That means the deployment shape looks more production-ready than the runtime implementation actually is.

## Health check

`GET /health` returns:

```json
{
  "status": "ok",
  "service": "EngageAI API"
}
```

This is a shallow app liveness check. It does not verify:

- OpenAI connectivity
- session storage
- scraper readiness
- Postgres
- Redis
- Celery

## Error handling

Backend returns structured JSON for:

- request validation errors
- HTTP exceptions
- unexpected exceptions

This is good for API cleanliness, but there is no structured error taxonomy yet.

## Missing production components

- real database integration
- migrations
- real queue/worker integration
- auth
- secret management
- Playwright installation + browser provisioning
- selector configuration
- metrics/alerts/tracing
- account isolation
- immutable frontend prod image build

## 14. Testing Status

File: `backend/tests/test_engagement_pipeline.py`

What is covered:

- pipeline filters irrelevant posts
- pipeline generates comments
- critic ranking result is used
- execution result is included
- one post failing does not stop later posts

How tests work:

- they monkeypatch `LinkedInScraper`
- they replace session manager, analytics, analyst, writer, critic, executor with fakes
- they stub `pydantic_settings` if unavailable

What is not covered:

- FastAPI routes
- frontend rendering
- scheduler behavior
- session encryption
- memory store consistency
- scraper behavior
- real OpenAI provider behavior

## 15. Architectural Gaps Between Intent And Reality

### Intended architecture from repo naming

- FastAPI backend
- Next.js frontend
- Postgres
- Redis
- Celery
- multi-agent safety-aware system

### Actual operational architecture today

- FastAPI backend: active
- Next.js dashboard: active
- AI provider wrapper: active
- scraper service: partially active, often placeholder-backed
- persona/memory/execution simulation: active
- Postgres: not used by app logic
- Redis: not used by app logic
- Celery: scaffold only
- safety/risk/trend/decision engines: scaffold only

The system is best described as a file-backed single-process prototype with a functional UI/API shell, not a production multi-service automation platform yet.

## 16. Top 10 Critical Issues And Risks

Ordered by severity.

### 1. Real mode silently degrades into mock mode

Location:

- `backend/run_pipeline.py`

Behavior:

- if `mock=false` and the real pipeline returns no results or raises, `_run_pipeline()` recursively reruns in mock mode

Risk:

- operators cannot trust whether results came from real data
- API consumers may believe they are acting on live LinkedIn content when they are not

### 2. Mock mode uses global monkeypatching and is not concurrency-safe

Location:

- `backend/run_pipeline.py`

Behavior:

- replaces `pipeline_module.LinkedInScraper`
- replaces `pipeline_module.SessionManager`
- replaces `pipeline_module.AnalystAgent`

Risk:

- concurrent API requests or scheduler/API overlap can cross-contaminate each other
- one request can alter global behavior for another request

### 3. Real scraping is not deployable from the declared dependency stack

Location:

- `backend/app/services/scraping/linkedin_scraper.py`
- `backend/requirements.txt`
- `backend/Dockerfile`

Evidence:

- scraper expects Playwright
- requirements do not list `playwright`
- Dockerfile does not install browsers
- selectors are not configured anywhere in the repo

Risk:

- “real mode” will almost always use placeholder data in a clean deployment

### 4. Memory is a single JSON file with only in-process locking

Location:

- `backend/app/core/memory_store.py`

Risk:

- unsafe for multi-worker FastAPI
- unsafe for multi-container deployments
- race conditions and lost writes are likely under concurrency

### 5. Session encryption is custom and unauthenticated

Location:

- `backend/app/services/security/session_manager.py`

Risk:

- cryptographic design is weaker than standard AEAD approaches
- tampering is not explicitly detected
- security posture is not acceptable for production credential/session storage

### 6. There is no authentication or authorization boundary

Location:

- backend API as a whole

Risk:

- any reachable client can invoke engagement runs
- there is no account ownership model
- severe misuse risk if deployed beyond local development

### 7. Safety/risk modules exist but are not enforced

Location:

- `backend/app/core/safety_filter.py`
- `backend/app/core/risk_engine.py`
- `backend/app/core/decision_engine.py`

Risk:

- repo documentation implies safer automation than the code actually provides
- comment generation/execution has no true policy gate

### 8. Global memory contaminates all accounts and campaigns

Location:

- `MemoryStore`
- writer/ persona / execution usage

Risk:

- generated comment reuse prevention is global
- style rotation is global
- last persona id is global
- execution history is global

This means one account’s activity influences another account’s behavior.

### 9. API request latency grows with inline execution delays

Location:

- `ExecutionService.simulate_post_comment()`
- pipeline path through `/run`

Behavior:

- each execution sleeps `2-10` seconds inside the request path

Risk:

- slow API responses
- poor UX on dashboard
- risk of timeouts under larger result sets

### 10. Database, Redis, and Celery create a false sense of readiness

Location:

- compose files
- requirements
- worker/database scaffolds

Risk:

- infra complexity is present without actual workload integration
- new engineers may assume persistence/queueing exists when the live system is still file-backed and synchronous

## 17. Recommended Mental Model For Future Work

Treat the current system as:

- a functional orchestration prototype
- with a real API/UI shell
- a real persona/memory/comment-selection loop
- but placeholder-heavy data acquisition and action execution

Safe assumptions for future engineering:

- pipeline behavior is mostly governed by `backend/run_pipeline.py` and `backend/app/orchestrator/pipeline.py`
- memory side effects are global and file-backed
- anything named safety/risk/trend/decision/database/celery is mostly structure, not runtime logic
- the frontend is a thin client over `/run`

## 18. Suggested Immediate Refactor Priorities

If the next engineer needs to harden this system, the highest-leverage sequence is:

1. remove mock monkeypatching from shared runtime paths
2. separate real-mode and mock-mode into explicit strategy objects
3. replace `MemoryStore` JSON file with a proper persistent store scoped by account
4. install and configure Playwright plus selector configuration, or explicitly disable real scraping until ready
5. introduce auth and account isolation before any non-local deployment
6. replace session crypto with standard authenticated encryption
7. move execution and scheduling off request path into background workers
8. wire real safety/risk gates before enabling live actions

## 19. File Inventory

This appendix classifies every authored source/config file currently present in the repository inventory.

### Root

| File | Role | Status |
|---|---|---|
| `README.md` | setup and usage documentation | active, partially accurate |
| `AGENTS.md` | intended agent architecture document | incomplete and drifts from code |
| `.env.example` | env template | active |
| `.gitignore` | ignore rules | active |
| `docker-compose.yml` | local/dev stack | active |
| `docker-compose.prod.yml` | production-style stack | active but optimistic |

### Backend runtime and config

| File | Role | Status |
|---|---|---|
| `backend/Dockerfile` | backend container image | active |
| `backend/requirements.txt` | python deps | active, missing Playwright |
| `backend/run_pipeline.py` | CLI/shared orchestration wrapper | active, high-risk monkeypatching |
| `backend/app/__init__.py` | package marker | structural |
| `backend/app/main.py` | FastAPI entry | active |
| `backend/app/config.py` | settings/env validation | active |
| `backend/app/database.py` | DB skeleton | placeholder |

### Backend agents

| File | Role | Status |
|---|---|---|
| `backend/app/agents/__init__.py` | package marker | structural |
| `backend/app/agents/scout_agent.py` | scout skeleton | unused placeholder |
| `backend/app/agents/analyst_agent.py` | relevance/engagement scoring | active |
| `backend/app/agents/writer_agent.py` | comment generation | active |
| `backend/app/agents/critic_agent.py` | filtering/ranking | active |
| `backend/app/agents/executor_agent.py` | execution guard + retries | active |
| `backend/app/agents/orchestrator.py` | orchestrator skeleton | unused placeholder |

### Backend core

| File | Role | Status |
|---|---|---|
| `backend/app/core/__init__.py` | package marker | structural |
| `backend/app/core/safety_filter.py` | safety skeleton | placeholder |
| `backend/app/core/risk_engine.py` | risk skeleton | placeholder |
| `backend/app/core/trend_engine.py` | trend skeleton | placeholder |
| `backend/app/core/persona_engine.py` | persona registry and prompting | active |
| `backend/app/core/memory_store.py` | JSON-backed memory | active |
| `backend/app/core/decision_engine.py` | decision skeleton | placeholder |

### Backend routers and schemas

| File | Role | Status |
|---|---|---|
| `backend/app/routers/__init__.py` | package marker | structural |
| `backend/app/routers/health.py` | health endpoint | active |
| `backend/app/routers/campaigns.py` | pipeline endpoints | active |
| `backend/app/schemas/__init__.py` | package marker | structural |
| `backend/app/schemas/common.py` | common API schemas | active |
| `backend/app/schemas/campaign.py` | pipeline request/response + campaign skeletons | mixed |

### Backend orchestration

| File | Role | Status |
|---|---|---|
| `backend/app/orchestrator/__init__.py` | package marker | structural |
| `backend/app/orchestrator/pipeline.py` | central engagement pipeline | active |

### Backend AI/scoring/scraping/security/services

| File | Role | Status |
|---|---|---|
| `backend/app/services/__init__.py` | package marker | structural |
| `backend/app/services/ai/__init__.py` | package marker | structural |
| `backend/app/services/ai/provider.py` | low-level OpenAI wrapper | active |
| `backend/app/services/ai/embedding_service.py` | embedding cache wrapper | active |
| `backend/app/services/scoring/__init__.py` | package marker | structural |
| `backend/app/services/scoring/relevance_scorer.py` | cosine similarity scoring | active |
| `backend/app/services/scraping/__init__.py` | package marker | structural |
| `backend/app/services/scraping/linkedin_scraper.py` | LinkedIn scraping | active but placeholder-heavy |
| `backend/app/services/security/session_manager.py` | local encrypted session storage | active |

### Backend analytics/behavior services

| File | Role | Status |
|---|---|---|
| `backend/app/services/analytics/__init__.py` | package marker | structural |
| `backend/app/services/analytics/analytics_service.py` | viral score + dashboard stats | active |
| `backend/app/services/analytics/engagement_analyzer.py` | analytics skeleton | placeholder |
| `backend/app/services/analytics/metrics_service.py` | analytics skeleton | placeholder |
| `backend/app/services/analytics/opportunity_scoring.py` | analytics skeleton | placeholder |
| `backend/app/services/behavior/__init__.py` | package marker | structural |
| `backend/app/services/behavior/execution_service.py` | simulated execution | active |
| `backend/app/services/behavior/scheduler_service.py` | continuous run loop | active |
| `backend/app/services/behavior/tone_analyzer.py` | behavior skeleton | placeholder |
| `backend/app/services/behavior/engagement_policy.py` | behavior skeleton | placeholder |

### Backend models, observability, workers

| File | Role | Status |
|---|---|---|
| `backend/app/models/__init__.py` | package marker | structural |
| `backend/app/models/base.py` | model mixin skeleton | placeholder |
| `backend/app/models/campaign.py` | campaign model skeleton | placeholder |
| `backend/app/observability/__init__.py` | package marker | structural |
| `backend/app/observability/logging.py` | structured logging | active |
| `backend/app/observability/metrics.py` | metrics skeleton | placeholder |
| `backend/app/workers/__init__.py` | package marker | structural |
| `backend/app/workers/celery_app.py` | Celery scaffold | placeholder |
| `backend/app/workers/tasks.py` | task scaffold | placeholder |

### Backend data and tests

| File | Role | Status |
|---|---|---|
| `backend/data/engagement_memory.json` | runtime memory state | active runtime artifact |
| `backend/tests/test_engagement_pipeline.py` | pipeline orchestration tests | active |

### Frontend app

| File | Role | Status |
|---|---|---|
| `frontend/Dockerfile` | frontend container image | active |
| `frontend/package.json` | frontend scripts/deps | active |
| `frontend/package-lock.json` | dependency lockfile | active generated dependency artifact |
| `frontend/tsconfig.json` | TS config | active |
| `frontend/next.config.mjs` | Next config | active minimal |
| `frontend/next-env.d.ts` | Next generated typing file | framework artifact |
| `frontend/tailwind.config.js` | Tailwind config | active |
| `frontend/postcss.config.js` | PostCSS config | active |
| `frontend/app/layout.tsx` | shared app layout | active |
| `frontend/app/page.tsx` | root page placeholder | placeholder UI |
| `frontend/app/dashboard/page.tsx` | dashboard control panel | active |
| `frontend/app/campaigns/page.tsx` | placeholder page | placeholder |
| `frontend/app/analytics/page.tsx` | placeholder page | placeholder |
| `frontend/app/settings/page.tsx` | placeholder page | placeholder |
| `frontend/app/globals.css` | global CSS + Tailwind directives | active |

### Frontend components and client

| File | Role | Status |
|---|---|---|
| `frontend/components/app-shell.tsx` | layout shell/nav | active |
| `frontend/components/nav-link.tsx` | nav link wrapper | active |
| `frontend/components/page-header.tsx` | page header | active |
| `frontend/components/placeholder-panel.tsx` | generic UI helper | present, lightly used or unused |
| `frontend/components/stat-card.tsx` | generic UI helper | present, lightly used or unused |
| `frontend/lib/api-client.ts` | browser API client | active |

## 20. Runtime Artifacts Present In The Working Tree

These are present in the repo state but are not authored source modules:

- `.env`
- `frontend/node_modules/`
- `frontend/.next/`
- `backend/.pytest_cache/`
- `backend/__pycache__/`
- `backend/sessions/`

Their presence matters operationally:

- `.env` may change behavior locally
- `node_modules` and `.next` indicate frontend has been installed/built
- `.pytest_cache` indicates tests were run
- `sessions/` is where local account cookies would be stored

They should not be treated as stable source-of-truth architecture.
