# TASKFLEX — Architecture

This document explains how the backend and frontend are structured, why the layers are
split the way they are, and how a request flows end-to-end.

---

## 1. High-level topology

```
┌──────────────────────┐         ┌───────────────────────────────┐
│  React SPA (nginx /   │  REST   │  FastAPI (uvicorn)            │
│  Vite dev server)     │ ──────▶ │  /api/v1/*                    │
│  customer / worker /  │  WS     │  /ws (websocket)              │
│  admin                │ ──────▶ │  /uploads/* (authorizing DL)  │
└──────────────────────┘         └──────────────┬────────────────┘
                                                │ SQLAlchemy 2.0
                                 ┌──────────────▼────────────────┐
                                 │  PostgreSQL (SQLite for dev)  │
                                 └───────────────────────────────┘
        Swappable providers (dependency-injected, chosen by env):
        AI  ──▶ OpenAI | Anthropic | Mock
        Pay ──▶ Mock | Razorpay(stub)
        Maps ─▶ OSM | Mock
        Notify ▶ log | console
```

## 2. Backend layering

```
Request
  │
  ▼
middleware/          RequestLogging (correlation id) → RateLimit → SecureHeaders
  │
  ▼
api/routes/          Thin HTTP layer: auth guards, request validation, envelopes.
  │                  NO business logic here — routes call services and serialize.
  ▼
services/            Business logic: task lifecycle, matching orchestration,
  │                  payment capture + ledger writes, dispute rules, analytics.
  ▼
repositories/        Data access only — SQLAlchemy queries, no business rules.
  │
  ▼
models/              ORM models (UUID PKs, timezone-aware UTC datetimes).
```

Supporting pillars sit beside this spine:

- **`ai/`** — task parser + classifier + clarification generator behind an
  `AIProvider` interface (`openai_provider.py`, `anthropic_provider.py`,
  `mock_provider.py`). Selected at startup via `AI_PROVIDER`.
- **`matching/`** — `engine.py` (weighted scoring + offer fan-out), `geo.py`
  (haversine, bounding boxes), `config.py` (weights, read from system settings).
- **`payments/`** — `PaymentProvider` interface; mock provider implements the
  authorize/capture/refund state machine deterministically.
- **`notifications/`** — dispatcher fans out to channels (log/console) — the seam
  for real email/SMS later.
- **`websocket/`** — connection manager keyed by user id; services call
  `broadcast_to_user(user_id, event, payload)`.
- **`core/`** — settings (pydantic-settings), JWT/password security, the
  success/error envelope helpers, structured logging, exception hierarchy.

### Why service/repository separation?

- Routes stay thin and are trivial to review for **authorization** (the security-
  critical concern lives in exactly one layer).
- Business rules (e.g. "only the customer can confirm completion") are unit-testable
  without HTTP.
- Repositories keep SQLAlchemy details out of services, so the storage layer can
  evolve (Postgres tuning, read replicas) without touching business logic.

## 3. Request flow: task creation (the core path)

```
POST /api/v1/tasks/parse          { text, location? }
  │  route: auth(CUSTOMER)
  ▼
TaskService.parse
  │  AIProvider.parse(text) ──▶ validated TaskInterpretation schema
  │  (never trusts raw LLM output — see docs/ai.md)
  ▼  response: interpretation + confidence + clarifying questions
     (NOT saved as a task yet)

POST /api/v1/tasks                { interpretation confirmed by user }
  │  route: auth(CUSTOMER)
  ▼
TaskService.create                status = DRAFT → PENDING_CONFIRMATION
  │  writes Task + TaskLocation + requirements
  ▼  response: TaskOut

POST /api/v1/tasks/{id}/confirm
  │  ownership check: current_user == task.customer
  ▼
TaskService.confirm               status → CONFIRMED
  │
  ▼
MatchingEngine.run(task)
  │  candidates = online workers within radius, skill match
  │  score = 0.30·distance + 0.25·skill + 0.15·availability
  │         + 0.15·rating + 0.10·reliability + 0.05·workload
  │  top MAX_OFFERS_PER_TASK workers get TaskOffers
  │  status → SEARCHING_WORKER → OFFERED
  │  websocket: "offer:new" per worker, "task:status" to customer
  ▼
worker accepts (POST /workers/offers/{id}/accept)
  │  first-accept-wins transaction; other offers cancelled
  │  status → ACCEPTED; assignment created
  ▼
… WORKER_ON_THE_WAY → IN_PROGRESS …

POST /tasks/{id}/complete   (customer only)
  │  PaymentService.capture  ──▶ commission + wallet credit + 3 ledger rows
  │  status → COMPLETED; both parties notified; rating window opens
  ▼
POST /ratings  (both parties, once each)
```

## 4. The confirmation guarantee

**The system never dispatches work without explicit human confirmation.**

- `POST /tasks/parse` returns an interpretation only — it persists nothing.
- A task created from an interpretation sits in `PENDING_CONFIRMATION`.
- `POST /tasks/{id}/confirm` is the only transition into `CONFIRMED`, and it is
  the only path into the matching engine. There is no automatic or scheduled
  dispatch anywhere in the codebase.
- The server enforces this (state machine validation), independent of the UI.

## 5. Frontend architecture

```
src/
├── api/          axios instance (envelope unwrapping, JWT attach, refresh-on-401),
│                 one module per backend area, typed helpers, WS client
├── stores/       zustand: auth store (tokens + user), toast store
├── lib/          utils (cn, formatters), constants (labels, styles), zod schemas
├── components/   ui primitives (Button, Card, Badge, Modal, Input, Select,
│                 Avatar, EmptyState, PageLoader, SkeletonList, Stat…)
└── pages/
    ├── public/   landing, login, register
    ├── customer/ dashboard, create task (AI flow), tasks, worker browse/profile,
    │             wallet, ratings
    ├── worker/   dashboard, offers, earnings, settings (profile/docs/availability)
    ├── admin/    layout + 10 screens (dashboard, users, workers, verifications,
    │             tasks, payments, disputes, reports, settings, audit logs)
    └── shared/   task list/details, messages, profile (role-aware)
```

- **TanStack Query** owns all server state: keys like `["admin-tasks", filters]`,
  invalidation after mutations, WebSocket events trigger invalidations so screens
  update live.
- **React Router** with role-aware guards: unauthenticated → `/login`; wrong-role
  users are redirected to their own home; `/admin/*` requires ADMIN.
- **Zod + react-hook-form** validate every form before it touches the network;
  the backend re-validates everything (never trust the client).

## 6. Cross-cutting concerns

| Concern        | Implementation |
|----------------|----------------|
| Config         | pydantic-settings `Settings`, `.env` backed, fail-fast validators |
| Errors         | Typed exception hierarchy → one handler set → consistent error envelope; unexpected errors are logged with correlation id and never leak internals |
| Logging        | Structured JSON-ish records with request id, method, path, status, duration; sensitive values are never logged |
| Security       | bcrypt hashes, JWT access+refresh, role guards, object-ownership checks, rate limiting, secure headers |
| Time           | All storage in UTC (`timezone-aware`), converted for display in the client |
| IDs            | UUID primary keys everywhere |
| Migrations     | Alembic, one baseline migration; entrypoint runs `upgrade head` |
| Seeding        | `database/seed.py` — deterministic (seeded RNG), guarded so it never duplicates data |

## 7. Deployment shape

`docker-compose.yml` runs three services:

- **db** — postgres:16-alpine with a healthcheck; data in a named volume.
- **backend** — python:3.12-slim; non-root user; entrypoint = migrations →
  (optional seed) → uvicorn; uploads in a named volume.
- **frontend** — multi-stage node build → nginx:alpine serving hashed assets and
  proxying `/api`, `/ws`, `/uploads` to the backend; SPA fallback for routing.

Scaling out later: the API is stateless (WS registry is per-process — move to
Redis pub/sub when running multiple replicas).
