# TASKFLEX — Database Schema

All tables use **UUID primary keys** and store timestamps in **UTC**. SQLAlchemy 2.0
models live in `app/models/`; the Alembic baseline migration creates everything below.

---

## Entity-relationship overview

```
users (role: CUSTOMER|WORKER|ADMIN)
 ├── customer_profiles        1:1
 ├── worker_profiles          1:1
 │     ├── worker_skills      N:M with skills
 │     ├── worker_availability
 │     └── verification_documents (private)
 ├── saved_locations
 ├── wallets                  1:1
 │     └── transactions       1:N
 ├── conversations ↔ messages (conversation_participants via task/counterpart ids)
 ├── notifications
 ├── ratings (given/received) · reviews (worker ← customer)
 └── audit_logs (admin/system actions)

tasks
 ├── task_locations           1:1  (address + lat/lng + plus_code)
 ├── task_requirements        1:N  (parsed needs)
 ├── task_offers              1:N  (OFFERED → ACCEPTED/REJECTED/EXPIRED/CANCELLED)
 ├── task_assignments         1:N  (accepted worker; ACTIVE → COMPLETED/CANCELLED)
 ├── task_status_history      1:N  (full audit of transitions)
 ├── payments                 1:N
 ├── ratings                  1:N  (customer→worker, worker→customer)
 └── disputes                 1:N
```

## Table reference

### users
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| email | string unique | lowercased |
| phone | string | |
| hashed_password | string | bcrypt — **never returned by any endpoint** |
| full_name | string | |
| role | enum | CUSTOMER / WORKER / ADMIN |
| is_active | bool | deactivation blocks login |
| is_verified | bool | email verified |
| avatar_url | string nullable | public avatars only |
| last_seen_at | timestamptz | powers "online now" |
| created_at / updated_at | timestamptz | |

### customer_profiles
User's default address, city, emergency contact, notification preferences. 1:1 with users.

### worker_profiles
| Column | Type | Notes |
|--------|------|-------|
| user_id | UUID FK unique | |
| bio, hourly_rate, experience_years | | displayed publicly |
| service_radius_km | float | working radius used by matching |
| is_online | bool | availability gate for offers |
| is_verified | bool | set by admin verification decisions |
| rating_average / rating_count | | denormalized from ratings |
| tasks_completed | int | denormalized counter |
| total_earnings | numeric | denormalized counter |
| lat / lng | float | last known position for distance scoring |
| area_name, city | string | display |

### skills / worker_skills
Taxonomy of skills; N:M join with per-worker proficiency.

### worker_availability
Per-weekday windows (start/end time, weekday int) used by the availability score.

### verification_documents
| Column | Type | Notes |
|--------|------|-------|
| worker_user_id | UUID FK | owner |
| doc_type | enum | aadhaar / pan / license / etc. |
| file_path | string | **private storage path — never serialized to clients** |
| file_name / mime_type / file_size | | metadata only |
| status | enum | PENDING / APPROVED / REJECTED |
| reviewed_by / reviewed_at / rejection_reason | | admin decision trail |

### tasks
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| customer_id | UUID FK → users | owner |
| title / description | string | description is the original natural-language text |
| task_type | enum | 13-type taxonomy (see docs/ai.md) |
| status | enum | lifecycle (README) |
| priority | enum | low / normal / high / urgent |
| scheduled_start / scheduled_end | timestamptz nullable | requested window |
| budget_min / budget_max | numeric nullable | customer's range |
| final_price | numeric nullable | agreed price at completion |
| parsed_by_ai / ai_confidence / ai_raw_response | | provenance of the parse |
| cancellation_reason | text nullable | who/why when cancelled |
| completed_at | timestamptz nullable | |
| created_at / updated_at | timestamptz | |

### task_locations
1:1 with tasks: address lines, city, pincode, lat/lng, plus_code, landmark,
access_instructions. Lat/lng feed haversine distance in matching.

### task_requirements
Parsed structured requirements (label/value pairs from AI extraction).

### task_offers
| Column | Type | Notes |
|--------|------|-------|
| task_id / worker_user_id | UUID FKs | |
| status | enum | PENDING → ACCEPTED / REJECTED / EXPIRED / CANCELLED |
| score | float | match score when offered |
| offered_at / expires_at / responded_at | timestamptz | TTL = settings offer_ttl_minutes |

First ACCEPTED wins; competing offers are CANCELLED by the service.

### task_assignments
Accepted worker per task; state ACTIVE → COMPLETED/CANCELLED; started_at/completed_at.

### task_status_history
Append-only: task_id, from_status, to_status, changed_by (user id or "system"), reason, at.

### payments / wallets / transactions
- **payments**: task_id, customer_id, amount, commission_amount, worker_payout,
  provider (mock/razorpay), provider_payment_id, status PENDING → AUTHORIZED →
  CAPTURED / FAILED / REFUNDED, captured_at.
- **wallets**: 1:1 per user, balance numeric.
- **transactions**: append-only ledger — wallet_id, amount (signed), type
  (TASK_PAYMENT / COMMISSION / TASK_EARNING / WITHDRAWAL / REFUND / ADJUSTMENT),
  balance_after, description, task_id nullable.

### ratings / reviews
- **ratings**: task_id, rater_id, ratee_id, direction (CUSTOMER_TO_WORKER /
  WORKER_TO_CUSTOMER), score 1–5, tags[], comment. Unique (task_id, direction).
- **reviews**: worker-scoped written reviews (1:1 with a customer→worker rating).

### conversations / messages
Task-scoped chat between customer and assigned worker; messages carry
sender_id, body, read_at. WebSocket pushes on new messages.

### notifications
user_id, type, title, body, payload (JSON), read_at. Unread count powers badges.

### disputes
task_id, raised_by, reason (enum), description, status OPEN → UNDER_REVIEW →
RESOLVED / REJECTED, resolution_note, resolved_by/at.

### audit_logs
actor (user id or "system"), action, entity_type, entity_id, detail (JSON), ip.
Written by admin actions and sensitive flows; surfaced in the admin console.

### system_settings
Key/value store backing runtime-editable platform settings (commission %,
default radius, offer TTL, offer cap, budget bounds) with typed defaults in
`SettingsRepository.DEFAULTS`.

## Indexes

- `users.email` unique; `tasks.status + created_at`; `tasks.customer_id`;
  `task_offers (worker_user_id, status)`; `messages (conversation_id, created_at)`;
  `notifications (user_id, read_at)`; `transactions (wallet_id, created_at)`;
  `ratings (ratee_id)` for profile queries.

## Seeding

`backend/database/seed.py` builds a deterministic dataset (seeded RNG): 1 admin,
10 customers, 20 workers, 10 skills, 30 tasks across all statuses with matching
payments, wallets, transactions, ratings, reviews, conversations, notifications,
documents, audit logs and system settings — centred on Belagavi, Karnataka
(15.3647 N, 74.9980 E) so distance-based matching has realistic geography.
The seed is guarded: it never runs against a database that already has users.
