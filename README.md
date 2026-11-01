# TASKFLEX

**Real-world tasks. Made simple.**

TASKFLEX is an AI-powered, on-demand marketplace for real-world errands — the kinds of tasks
that need a human to physically show up somewhere: getting a token at a hospital registration
desk, standing in a government queue, collecting a parcel, submitting documents at an office,
picking up groceries, or getting non-financial help at a bank.

A customer describes what they need in plain language. An AI service parses that into a
structured task (type, location, time window, budget) and — critically — **shows its
interpretation to the customer for confirmation before anything is dispatched**. Once
confirmed, a weighted matching engine finds suitable gig workers nearby, sends offers, and
the task moves through a full lifecycle all the way to completion, payment, and mutual
ratings.

---

## Table of contents

1. [Feature highlights](#feature-highlights)
2. [Tech stack](#tech-stack)
3. [Repository layout](#repository-layout)
4. [Quickstart with Docker (recommended)](#quickstart-with-docker-recommended)
5. [Quickstart without Docker](#quickstart-without-docker)
6. [Demo data (development only)](#demo-data-development-only)
7. [Environment variables](#environment-variables)
8. [The task lifecycle](#the-task-lifecycle)
9. [AI task parsing](#ai-task-parsing)
10. [Matching engine](#matching-engine)
11. [Payments & wallets](#payments--wallets)
12. [Real-time updates (WebSockets)](#real-time-updates-websockets)
13. [File uploads & privacy](#file-uploads--privacy)
14. [Admin console](#admin-console)
15. [API documentation](#api-documentation)
16. [Testing](#testing)
17. [Security model](#security-model)
18. [Deploying to production](#deploying-to-production)
19. [Further documentation](#further-documentation)

---

## Feature highlights

### Customer experience
- **Natural-language task creation** — "I need someone to collect my passport from the
  regional passport office tomorrow at 11am, my budget is ₹600" becomes a structured task.
  The AI returns confidence, detected fields, missing fields, and clarifying questions.
- **Explicit confirmation gate** — the customer always sees the parsed interpretation and
  must press *Confirm* before the task ever reaches the matching engine. **No automatic
  dispatch. Ever.**
- **Worker discovery** — browse/search verified workers by skill, distance, rating; view
  profiles, ratings, and reviews.
- **Live task tracking** — status timeline, worker assignment, in-app chat with the assigned
  worker, and real-time status pushes over WebSocket.
- **Completion + payment** — customer confirms completion, a mock payment is captured,
  commission is deducted, and the worker's wallet is credited.
- **Mutual ratings** — both sides rate each other after completion; workers get written
  reviews on their profiles.
- **Saved locations** — address book with geocoding (OpenStreetMap; no API key needed).
- **Wallet ledger** — every payment movement is recorded as an immutable transaction.
- **Disputes** — raise a dispute on a task; admins resolve with a written resolution note.

### Worker experience
- **Profile with skills** — up to N skills chosen from a taxonomy, service radius, hourly
  rate, bio, avatar.
- **Go online/offline** — availability participates directly in match scoring.
- **Job offers inbox** — offers expire (TTL configurable, default 15 minutes); accept or
  reject with one tap.
- **Earnings dashboard** — lifetime earnings, weekly earnings, completed task count, wallet
  balance, transaction ledger.
- **Navigation** — turn-by-turn map links for the task location.
- **Verification documents** — upload ID documents; admins review them; the files are
  **private** (never served by URL to other users).

### Admin console
- **Dashboard** — user/task/revenue KPIs plus a 30-day created-vs-completed trend chart.
- **User management** — search, filter by role/status, activate/deactivate accounts.
- **Worker oversight** — verification badges, ratings, earnings, online status.
- **Verification queue** — review uploaded ID documents (viewed as private downloads) and
  approve/reject with a mandatory reason.
- **Task oversight** — every task with AI-confidence badges; force-cancel with an audit
  reason.
- **Payments & transactions** — commission, worker payouts, per-user ledgers.
- **Dispute resolution** — resolve / mark-under-review / reject with notes.
- **Reports** — 7–90 day analytics: DAU/MAU series, task creation/completion, task-type and
  status distributions.
- **Platform settings** — commission %, default radius, offer TTL, budget limits — editable
  at runtime, no redeploy.
- **Audit log** — every privileged action recorded with actor, IP, and entity.

---

## Tech stack

| Layer      | Technology |
|------------|------------|
| Backend    | Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, Pydantic v2, PyJWT, bcrypt |
| Database   | PostgreSQL 16 (SQLite supported for quick local runs/tests) |
| AI         | Provider abstraction: **OpenAI**, **Anthropic**, or **Mock** (switchable via env) |
| Payments   | Provider abstraction: **Mock** (default) or **Razorpay** (stub) |
| Real-time  | Native WebSockets with per-user connection registry |
| Frontend   | React 18, TypeScript, Vite, TailwindCSS, React Router, TanStack Query, Zustand, React Hook Form + Zod, Recharts, lucide-react |
| Tests      | pytest (backend, 51 tests), Vitest + Testing Library (frontend) |
| Deploy     | Docker + docker compose (Postgres + API + nginx-served SPA) |

---

## Repository layout

```
taskflex/
├── docker-compose.yml          # local dev: db + backend + frontend, one command
├── docker-compose.prod.yml     # production stack (env-driven, guarded)
├── .env.example                # local configuration, documented
├── .env.prod.example           # production deployment template
├── DEPLOY.md                   # step-by-step deployment guide
├── docs/                       # architecture, API, database, AI docs
├── backend/
│   ├── Dockerfile
│   ├── docker-entrypoint.sh    # alembic upgrade + optional seed + uvicorn
│   ├── requirements.txt
│   ├── alembic/                # migrations
│   ├── app/
│   │   ├── main.py             # app factory, middleware, router mounting
│   │   ├── core/               # config, security, logging, envelopes
│   │   ├── models/             # SQLAlchemy ORM models (UUID PKs)
│   │   ├── schemas/            # Pydantic request/response schemas
│   │   ├── repositories/       # data access (service/repository split)
│   │   ├── services/           # business logic
│   │   ├── ai/                 # task parser, classifier, clarification, providers
│   │   ├── matching/           # weighted matching engine + haversine geo
│   │   ├── payments/           # mock + razorpay payment providers
│   │   ├── notifications/      # dispatcher + log/email/sms channels
│   │   ├── api/routes/         # all REST endpoints + websocket
│   │   ├── middleware/         # request logging, rate limit, secure headers
│   │   └── websocket/          # connection manager + event broadcaster
│   ├── database/seed.py        # deterministic demo dataset
│   └── tests/                  # pytest suite
└── frontend/
    ├── Dockerfile              # node build -> nginx runtime
    ├── nginx.conf              # SPA serving + /api,/ws,/uploads proxy
    └── src/
        ├── api/                # axios client, endpoint modules, WS client
        ├── components/ui/      # design system primitives
        ├── pages/public/       # landing, login, register
        ├── pages/customer/     # customer app
        ├── pages/worker/       # worker app
        ├── pages/admin/        # admin console
        ├── pages/shared/       # tasks, task details, messages, profile
        ├── stores/             # zustand (auth, toasts)
        └── test/               # vitest setup + tests
```

---

## Quickstart with Docker (recommended)

Prerequisite: Docker + the compose plugin. No API keys required — the default
configuration uses the mock AI, mock payments, log notifications, and OSM geocoding.

```bash
cp .env.example .env          # optional for compose (defaults are baked in)
docker compose up --build
```

When it's up:

| Service     | URL                                  |
|-------------|--------------------------------------|
| Frontend    | http://localhost:5173                |
| API         | http://localhost:8000/api/v1/...     |
| OpenAPI docs| http://localhost:8000/docs (ReDoc: `/redoc`) |
| Health      | http://localhost:8000/health         |

The backend entrypoint runs `alembic upgrade head`, seeds the demo dataset on first boot
(databases that already contain data are never re-seeded), then starts uvicorn.

To reset everything: `docker compose down -v` (drops the Postgres volume).

---

## Quickstart without Docker

### 1. Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp ../.env.example .env              # then edit if desired

# Option A — zero-setup SQLite
#   leave DATABASE_URL as sqlite:///./taskflex.db
# Option B — PostgreSQL
#   DATABASE_URL=postgresql+psycopg2://taskflex:taskflex@localhost:5432/taskflex

alembic upgrade head                 # create schema
python -m database.seed              # deterministic demo data (idempotent guard)

uvicorn app.main:app --reload --port 8000
```

With `SEED_ON_START=true` the API seeds itself on boot when the DB is empty, so the seed
step is optional.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev                          # http://localhost:5173
```

The Vite dev server proxies `/api`, `/ws`, and `/uploads` to `http://localhost:8000`, so no
CORS setup is needed in development.

---

## Demo data (development only)

For local development you can seed a deterministic dataset (10 customers, 20 workers,
30 tasks spanning the whole lifecycle, centred on Belagavi, Karnataka) so every screen
has realistic data immediately. All seeded accounts share the password **`Demo@1234`**.

| Role     | Email                        | Notes |
|----------|------------------------------|-------|
| Admin    | `admin@taskflex.dev`         | Full admin console |
| Customer | `customer1@demo.taskflex.dev`| Has task history, wallet, saved locations |
| Worker   | `worker1@demo.taskflex.dev`  | Verified, rated, has earnings history |

Seeding only runs when explicitly enabled (`SEED_ON_START=true` or
`python -m database.seed`) **and** the database is empty — it never touches existing
data, and the production compose file forces it off.

Signup requires email verification in every environment: new accounts receive a
6-digit one-time passcode. In development (without SMTP configured) the code is
returned in the API response for convenience; in production a real SMTP server must
be configured and no codes are ever exposed via the API.

---

## Environment variables

Copy `.env.example` to `.env` (backend reads `backend/.env` or the repo-root `.env`).
Everything has a sensible default for local/demo use. **Never commit real secrets.**

| Variable | Default | Purpose |
|----------|---------|---------|
| `ENVIRONMENT` | `development` | `production` toggles stricter cookie/security behaviour |
| `DEBUG` | `true` | Verbose error details in API responses |
| `DATABASE_URL` | `sqlite:///./taskflex.db` | SQLAlchemy URL (Postgres for compose) |
| `JWT_SECRET` / `JWT_REFRESH_SECRET` | dev placeholders | **Must be replaced in production — the app refuses to boot otherwise** |
| `GOOGLE_CLIENT_ID` | empty | OAuth Web Client ID for "Sign in with Google" ([docs/google-oauth-setup.md](docs/google-oauth-setup.md)); empty hides the buttons |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Access token TTL |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `14` | Refresh token TTL |
| `AI_PROVIDER` | `mock` | `openai` \| `anthropic` \| `mock` |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | empty | Provider keys (lazy import; mock used if absent) |
| `MAPS_PROVIDER` | `osm` | `osm` needs no key; `mock` for offline |
| `PAYMENT_PROVIDER` | `mock` | `mock` \| `razorpay` |
| `PLATFORM_COMMISSION_PERCENT` | `10.0` | Deducted from worker payout on capture |
| `DEFAULT_WORKER_RADIUS_KM` | `8.0` | Working-radius default for matching |
| `OFFER_TTL_MINUTES` | `15` | Offer expiry |
| `MAX_OFFERS_PER_TASK` | `6` | Offer fan-out cap per matching round |
| `EMAIL_PROVIDER` / `SMS_PROVIDER` | `log` | `log` \| `smtp` for real email (OTP delivery) |
| `SMTP_HOST` / `SMTP_PORT` | `smtp.gmail.com` / `587` | SMTP server for OTP emails (STARTTLS) |
| `SMTP_USER` / `SMTP_PASSWORD` | empty | Gmail address + 16-char **App Password** (2-Step Verification required) |
| `EMAIL_FROM` | empty | From-address; falls back to `SMTP_USER` |
| `OTP_EXPIRE_MINUTES` / `OTP_MAX_ATTEMPTS` / `OTP_RESEND_COOLDOWN_SECONDS` | `10` / `5` / `60` | One-time passcode rules |
| `UPLOAD_DIR` | `./uploads` | Private document storage root |
| `MAX_UPLOAD_SIZE_MB` | `10` | Upload cap |
| `SEED_ON_START` | `false` | Seed demo data on boot if DB empty |
| `CORS_ORIGINS` | `http://localhost:5173,...` | Comma-separated allowlist |

---

## The task lifecycle

```
DRAFT ──confirm──▶ PENDING_CONFIRMATION ──AI confirmed──▶ CONFIRMED
      ──match──▶ SEARCHING_WORKER ──offers──▶ OFFERED
      ──worker accepts──▶ ACCEPTED ──en route──▶ WORKER_ON_THE_WAY
      ──start──▶ IN_PROGRESS ──customer confirms──▶ COMPLETED
                                   │
                        (either party, with reason)
                                   ▼
                     CANCELLED  /  DISPUTED
```

- **Confirmation gate**: a task is never dispatched before the customer explicitly confirms
  the AI's interpretation (`POST /tasks/{id}/confirm`). This is enforced server-side, not
  just in the UI.
- **Offers expire** after `OFFER_TTL_MINUTES`; the customer can retry matching
  (`POST /tasks/{id}/retry-matching`).
- **Completion** requires the customer's explicit confirmation (`POST /tasks/{id}/complete`),
  which triggers payment capture → commission → worker wallet credit → both parties are
  notified.

## AI task parsing

`POST /tasks/parse` accepts free text plus optional customer location. The active provider
(OpenAI / Anthropic / Mock) returns a structured interpretation:

- task type (from a fixed taxonomy), title, description
- requested time window, budget estimate
- extracted address + geocoded coordinates
- per-field confidence, overall confidence
- missing-field list and follow-up clarification questions
- safety/eligibility flags (e.g. refuses financial or medical-advice tasks)

**LLM output is never trusted blindly.** Every response is validated against Pydantic
schemas, coordinates are sanity-checked, task types must exist in the taxonomy, and
low-confidence parses are surfaced to the user as clarification questions rather than being
dispatched. Full details: [docs/ai.md](docs/ai.md).

## Matching engine

When a confirmed task enters `SEARCHING_WORKER`, the engine:

1. Finds online workers whose skill set covers the task type and whose distance to the task
   is within their working radius.
2. Scores each candidate on configurable weights:
   `distance 0.30 · skill 0.25 · availability 0.15 · rating 0.15 · reliability 0.10 · workload 0.05`
3. Sends offers to the top `MAX_OFFERS_PER_TASK` workers; each offer expires after
   `OFFER_TTL_MINUTES`. First worker to accept wins the task.

## Payments & wallets

- **Capture flow**: on task completion the customer's payment is captured, commission is
  deducted, the remainder is credited to the worker's wallet, and three immutable ledger
  transactions are written (customer debit, commission, worker credit).
- **Providers**: `MockPaymentProvider` (always succeeds, deterministic ids) and a
  `RazorpayPaymentProvider` stub showing the integration seam. Switch via `PAYMENT_PROVIDER`.

## Real-time updates (WebSockets)

Clients connect to `wss?://host/ws` with their access token. The connection manager routes
per-user events: new task status, new offers, new messages, notifications. The frontend
reconnects automatically and TanStack Query caches are invalidated on relevant events, so
every screen stays live without polling.

## File uploads & privacy

- Worker verification documents are uploaded to a **private** storage root that is never
  part of any static mount.
- Downloads go through `GET /uploads/documents/{id}`, which authorizes the requesting user
  (owning worker or admin only) before streaming bytes.
- `DocumentOut` deliberately contains **no file URL** — other users can never obtain even
  the storage path.

## Admin console

Sign in as a user with the ADMIN role and the app routes to `/admin`: dashboard KPIs and
charts, user/worker management, the verification queue (view private docs inline),
task oversight with force-cancel, payments/transactions, dispute resolution, 7–90 day
reports, runtime platform settings, and the audit log. Admins can't self-register — the
deployment guide shows how to promote the first one.

## API documentation

- Live OpenAPI UI: **http://localhost:8000/docs**
- Human reference: [docs/api.md](docs/api.md) (every endpoint with method, path, auth,
  params, and example payloads)

All responses use a consistent envelope:

```json
{ "success": true,  "data": { ... }, "message": "optional" }
{ "success": false, "error": { "code": "not_found", "message": "..." } }
```

## Testing

```bash
# Backend
cd backend && pytest            # 51 tests: auth + OTP, tasks, matching, AI, payments, admin

# Frontend
cd frontend && npm test         # vitest: utils/logic tests, jsdom environment
npm run build                   # strict tsc + production bundle
```

## Security model

- Passwords hashed with bcrypt; JWTs (access + refresh) with configurable secrets/TTLs.
- **Authorization is enforced server-side on every endpoint** — role guards
  (CUSTOMER/WORKER/ADMIN) and object-ownership checks. The frontend never decides access.
- Never exposed in any response: password hashes, other users' private documents, private
  customer contact details beyond what a task requires.
- Uploads validated by MIME type and size; stored outside any public path; served only
  through an authorizing endpoint.
- Structured logging that **never logs** passwords, tokens, private documents, or sensitive
  personal information.
- Middleware: request logging with correlation ids, rate limiting, secure headers.

## Deploying to production

Production runs on `docker-compose.prod.yml`: one exposed port serves the whole app
(nginx serving the React bundle and proxying `/api`, `/ws`, `/uploads` to the backend),
Postgres and uploads stay in internal volumes, demo seeding is forced off, OpenAPI docs
are disabled, and the backend refuses to boot without real JWT secrets and SMTP
credentials.

Full step-by-step guide — configuration, first admin bootstrap, HTTPS with Caddy,
updates, and backups: **[DEPLOY.md](DEPLOY.md)**.

## Further documentation

- [docs/architecture.md](docs/architecture.md) — layering, request flow, design decisions
- [docs/api.md](docs/api.md) — complete endpoint reference
- [docs/database.md](docs/database.md) — schema, relationships, indexes
- [docs/ai.md](docs/ai.md) — provider abstraction, prompt design, validation gates
- [docs/google-oauth-setup.md](docs/google-oauth-setup.md) — enable "Sign in with Google"
