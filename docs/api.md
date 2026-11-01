# TASKFLEX — API Reference

Base URL: **`/api/v1`** · Interactive docs: **http://localhost:8000/docs**

## Conventions

- **Envelope** — every JSON response:
  ```json
  { "success": true, "data": { ... }, "message": "optional" }
  { "success": false, "error": { "code": "not_found", "message": "human readable" } }
  ```
- **Auth** — `Authorization: Bearer <access_token>`. Refresh via `POST /auth/refresh`.
  Roles: `CUSTOMER`, `WORKER`, `ADMIN` (enforced server-side per endpoint).
- **Pagination** — list endpoints take `page` (1-based) and `page_size`, and return
  `{ items, total, page, page_size }` inside `data`.
- **Binary** — private document download (`GET /uploads/documents/{id}`) streams raw
  bytes, not the JSON envelope.
- **WebSocket** — `GET /ws?token=<access_token>` (native WS handshake), then JSON
  frames `{ event, payload }`.

---

## Auth — `/auth`

| Method | Path | Auth | Body / notes |
|--------|------|------|--------------|
| POST | `/auth/register` | — | `{email, password, full_name, phone, role}` → tokens + user |
| POST | `/auth/login` | — | `{identifier, password}` (identifier = email or phone) → `{access_token, refresh_token, user}` |
| POST | `/auth/refresh` | — | `{refresh_token}` → new token pair |
| POST | `/auth/forgot-password` | — | `{email}` → always 200 (no user enumeration) |
| POST | `/auth/reset-password` | — | `{token, new_password}` |
| POST | `/auth/resend-otp` | — | `{identifier}` (email or phone) → always 200 (no user enumeration) |
| POST | `/auth/verify-email` | — | `{identifier, code}` (identifier = email or phone) → tokens + user |
| GET | `/auth/me` | any | current user + role-specific profile summary |

## Users — `/users`

| Method | Path | Auth | Notes |
|--------|------|------|-------|
| GET | `/users/me` | any | full profile for current role |
| PATCH | `/users/me` | any | partial profile update |
| GET | `/users/me/wallet` | any | balance + recent transactions |
| GET | `/users/me/transactions` | any | paginated ledger |
| GET | `/users/me/locations` | CUSTOMER | saved address book |
| POST | `/users/me/locations` | CUSTOMER | `{label, address, lat, lng, …}` |
| DELETE | `/users/me/locations/{id}` | CUSTOMER | owner only |

## Tasks — `/tasks`

| Method | Path | Auth | Body / query |
|--------|------|------|--------------|
| POST | `/tasks/parse` | CUSTOMER | `{text, location?}` → AI interpretation (**persists nothing**) |
| POST | `/tasks` | CUSTOMER | confirmed interpretation → task in `PENDING_CONFIRMATION` |
| GET | `/tasks` | any | role-scoped list; `?status=&page=&page_size=` (admin: all) |
| GET | `/tasks/{id}` | participant / admin | includes viewer-specific fields (e.g. `my_offer_status` for workers) |
| GET | `/tasks/{id}/matches` | CUSTOMER owner | candidate workers + scores for the task |
| PATCH | `/tasks/{id}` | CUSTOMER owner | edit while DRAFT/PENDING_CONFIRMATION |
| POST | `/tasks/{id}/confirm` | CUSTOMER owner | → CONFIRMED, triggers matching (the **only** dispatch path) |
| POST | `/tasks/{id}/status` | participant | lifecycle advance (worker en-route / start / etc.) |
| POST | `/tasks/{id}/complete` | CUSTOMER owner | captures payment, credits worker, → COMPLETED |
| POST | `/tasks/{id}/cancel` | participant | `{reason}` → CANCELLED |
| POST | `/tasks/{id}/retry-matching` | CUSTOMER owner | re-run matching (e.g. after offers expired) |

## Workers — `/workers`

| Method | Path | Auth | Notes |
|--------|------|------|-------|
| GET | `/workers` | — | public directory: `?search=&city=&skill=&online_only=&page=&page_size=` (verified only) |
| GET | `/workers/{user_id}` | — | public profile + reviews summary |
| GET | `/workers/me/profile` | WORKER | own profile |
| PATCH | `/workers/me/profile` | WORKER | bio, hourly rate, radius, skills, avatar… |
| PUT | `/workers/me/availability` | WORKER | weekly windows |
| POST | `/workers/me/online` | WORKER | `{is_online}` toggle |
| GET | `/workers/me/offers` | WORKER | pending + history offers |
| POST | `/workers/offers/{id}/accept` | WORKER | first accept wins → task ACCEPTED |
| POST | `/workers/offers/{id}/reject` | WORKER | offer REJECTED |
| GET | `/workers/me/earnings` | WORKER | totals, weekly series, wallet |
| GET | `/workers/me/documents` | WORKER | own verification docs (no file URLs by design) |
| POST | `/workers/me/documents` | WORKER | multipart upload (mime/size validated, private) |
| DELETE | `/workers/me/documents/{id}` | WORKER | owner only |

## Ratings & reviews — `/ratings`

| Method | Path | Auth | Notes |
|--------|------|------|-------|
| POST | `/ratings` | participant | rate counterpart on a completed task; unique per task+direction |
| GET | `/tasks/{id}/ratings` | participant | both ratings for the task |
| GET | `/workers/{user_id}/reviews` | — | paginated written reviews |
| GET | `/workers/{user_id}/rating-summary` | — | average, count, distribution |

## Messaging — `/conversations`

| Method | Path | Auth | Notes |
|--------|------|------|-------|
| GET | `/conversations` | any | own conversations (task-scoped) |
| POST | `/conversations` | participant | `{task_id}` → find-or-create with counterpart |
| GET | `/conversations/{id}/messages` | member | paginated, `?before=` cursor |
| POST | `/conversations/{id}/messages` | member | `{body}` → persisted + WS push |

## Notifications — `/notifications`

| Method | Path | Auth | Notes |
|--------|------|------|-------|
| GET | `/notifications` | any | `?unread_only=&page=` |
| GET | `/notifications/unread-count` | any | `{count}` |
| POST | `/notifications/{id}/read` | owner | |
| POST | `/notifications/read-all` | any | |

## Payments — `/payments`

| Method | Path | Auth | Notes |
|--------|------|------|-------|
| GET | `/payments` | any | own payments (admin sees all via /admin) |
| GET | `/payments/for-task/{task_id}` | participant | payment for one task |

## Disputes — `/disputes`

| Method | Path | Auth | Notes |
|--------|------|------|-------|
| POST | `/disputes` | participant | `{task_id, reason, description}` → OPEN |
| GET | `/disputes` | any | own disputes; admin sees all; `?status=` |
| GET | `/disputes/{id}` | participant / admin | |
| POST | `/disputes/{id}/resolve` | ADMIN | `{status: RESOLVED\|UNDER_REVIEW\|REJECTED, resolution_note}` |

## Location — `/location`

| Method | Path | Auth | Notes |
|--------|------|------|-------|
| POST | `/location/geocode` | any | `{query}` → matches (OSM; mock fallback offline) |
| GET | `/location/map-url` | any | `?lat=&lng=` → directions deep link |

## Uploads — `/uploads`

| Method | Path | Auth | Notes |
|--------|------|------|-------|
| GET | `/uploads/documents/{document_id}` | owner worker / ADMIN | **authorizing binary download** of a private document |

## WebSocket — `/ws`

Connect: `new WebSocket("ws://host/ws?token=" + accessToken)`.

Server → client frames:

| Event | Payload | When |
|-------|---------|------|
| `task:status` | `{task_id, status}` | any lifecycle change on your task |
| `offer:new` | `{offer_id, task}` | matched to you as a worker |
| `message:new` | `{conversation_id, message}` | chat message in your conversation |
| `notification:new` | notification object | any notification |

## Admin — `/admin` (ADMIN only)

| Method | Path | Notes |
|--------|------|-------|
| GET | `/admin/dashboard` | KPI metrics (users, tasks, revenue, rates, disputes) |
| GET | `/admin/analytics?days=7..90` | DAU/MAU, created/completed series, distributions |
| GET | `/admin/users?role=&search=&is_active=&page=` | user directory |
| PATCH | `/admin/users/{id}/status?is_active=` | activate/deactivate (query param) |
| GET | `/admin/verifications/pending` | verification queue with document metadata |
| POST | `/admin/verifications/{document_id}/decision?approve=&reason=` | approve/reject (reject requires reason) |
| GET | `/admin/workers?search=&verified=&online=` | worker oversight |
| GET | `/admin/tasks?status=&task_type=&search=&page=` | all tasks incl. AI confidence |
| POST | `/admin/tasks/{id}/cancel?reason=` | force cancel any non-terminal task |
| GET | `/admin/payments?status=&page=` | payment ledger |
| GET | `/admin/transactions?user_id=&page=` | wallet transactions |
| GET | `/admin/settings` | effective platform settings |
| PUT | `/admin/settings` | `{settings: {key: value}}` — partial update |
| GET | `/admin/audit-logs?action=&page=` | privileged action trail |

## System

| Method | Path | Notes |
|--------|------|-------|
| GET | `/health` | `{success: true, data: {status: "ok"}}` |
| GET | `/openapi.json` | machine-readable schema |
| GET | `/docs`, `/redoc` | interactive documentation |
