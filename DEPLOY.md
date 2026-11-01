# Deploying TASKFLEX to production

This guide takes TASKFLEX from this repository to a live site on a single
server using Docker. Everything runs in three containers:

```
browser ──> frontend (nginx :80)      static React app
                 │  proxies /api  /ws  /uploads
                 ▼
            backend (uvicorn :8000)   FastAPI — runs DB migrations on start
                 │
                 ▼
            db (postgres 16)          data only reachable inside the stack
```

Uploads live in a Docker volume (`uploads`), the database in `pgdata`.
The frontend's nginx config already forwards `/api`, `/ws` and `/uploads`
to the backend, so the whole site is served from ONE port.

---

## What you need

- A Linux server (Ubuntu 22.04+ is fine) with **Docker** installed
  (`curl -fsSL https://get.docker.com | sh`), and ports 80/443 reachable.
- The code on the server: `git clone <your-repo>` (or copy the folder over).
- A **Gmail account with an App Password** — signup requires real OTP emails.
  1. Enable 2-Step Verification on the account
  2. Create an app password: https://myaccount.google.com/apppasswords
  3. Keep the 16-character password for step 2 below.
- (For HTTPS) a domain whose DNS `A` record points at the server's IP.

---

## 1. Configure

In the repo root:

```bash
cp .env.prod.example .env
nano .env    # or any editor
```

Fill in every REQUIRED value:

| Variable | What to put |
| --- | --- |
| `FRONTEND_ORIGIN`, `CORS_ORIGINS` | Your public URL, e.g. `https://tasks.example.com` (same value in both) |
| `POSTGRES_PASSWORD` | Long random string — `python3 -c "import secrets; print(secrets.token_urlsafe(24))"` |
| `JWT_SECRET`, `JWT_REFRESH_SECRET` | Two DIFFERENT long random strings — `python3 -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `OTP_PEPPER` | A third long random string (peppers the start/completion task handshake codes) — `python3 -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_FROM` | The Gmail address, its 16-char app password, and the address again |

Leave `HTTP_PORT=80` unless something else owns port 80 (see HTTPS below).
The backend **refuses to boot** in production if JWT secrets, `OTP_PEPPER`
or SMTP credentials are missing — that guard is there to protect you.

> `AI_PROVIDER=mock` works fine in production: the built-in parser structures
> tasks without an AI key. For payments, see the note below — real money needs
> Razorpay.

### Taking real payments (Razorpay)

Set `PAYMENT_PROVIDER=razorpay` and fill `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`
and `RAZORPAY_WEBHOOK_SECRET` (all three REQUIRED — the backend refuses to boot
otherwise). Then add the webhook in the Razorpay dashboard:

- URL: `https://yourdomain.com/api/v1/payments/webhook/razorpay`
- Secret: the same value as `RAZORPAY_WEBHOOK_SECRET`
- Events: `payment.authorized`, `payment.captured`, `payment.failed`

Step-by-step walkthrough (test mode → live mode): **docs/razorpay-setup.md**.
Money flow: confirming a task opens a Razorpay order; the customer pays in the
hosted checkout; funds are captured and the runner is paid only when the
customer confirms completion; cancellations refund automatically.

## 2. Start

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

First build takes a few minutes. The backend applies database migrations
automatically before starting.

## 3. Verify

```bash
curl http://localhost/health
# {"success":true,"data":{"status":"ok","app":"TASKFLEX"}}
```

Then open `http://<server-ip>` (or your domain) in a browser:

- The landing page loads and `/docs` is **disabled** (production mode).
- Register a real account with a real email — the 6-digit code arrives by
  email (there is no on-screen demo code in production).

### Create the first admin

Admins can't self-register. Sign up normally in the UI, then promote the
account and sign in again:

```bash
docker compose -f docker-compose.prod.yml exec db \
  psql -U taskflex -d taskflex -c "UPDATE users SET role='ADMIN' WHERE email='you@example.com';"
```

## 4. HTTPS (strongly recommended)

The simplest option is [Caddy](https://caddyserver.com) on the host — it
obtains and renews certificates automatically.

1. In `.env` set `HTTP_PORT=8080`, then `docker compose -f docker-compose.prod.yml up -d`
   (recreates the frontend on the new port).
2. Install Caddy and create `/etc/caddy/Caddyfile`:

   ```
   yourdomain.com {
       reverse_proxy localhost:8080
   }
   ```

3. `sudo systemctl reload caddy`

Cloud alternatives: terminate TLS on a load balancer (AWS ALB, Render,
Railway) that forwards to the server on `HTTP_PORT`.

## 5. Day-to-day operations

```bash
# logs
docker compose -f docker-compose.prod.yml logs -f backend

# deploy an update (migrations run automatically)
git pull
docker compose -f docker-compose.prod.yml up -d --build

# database backup
docker compose -f docker-compose.prod.yml exec db \
  pg_dump -U taskflex taskflex > taskflex-$(date +%F).sql

# uploaded files backup
docker run --rm -v taskflex-prod_uploads:/data -v "$PWD":/backup alpine \
  tar czf /backup/uploads-$(date +%F).tar.gz -C /data .
```

Schedule both backups with cron and copy them off the server.

## 6. Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| Backend exits with "Refusing to start in production with default JWT secrets" | `JWT_SECRET`/`JWT_REFRESH_SECRET` missing or still start with `dev-` — set real ones in `.env` |
| Backend exits with "Refusing to start in production without SMTP" | `SMTP_USER`/`SMTP_PASSWORD` empty — add the Gmail app password |
| Signup OTP never arrives | Wrong app password, or Gmail flagged it — check `docker compose logs backend`, check spam folder |
| `429` errors during testing | Built-in auth rate limit (20 requests/min/IP) — expected |
| Start completely fresh | `docker compose -f docker-compose.prod.yml down -v` **deletes all data** — usually you never want this |

## 7. Security notes

- `.env` holds every secret — never commit or share it (`.gitignore` already excludes it).
- The database has no published ports; only the frontend port is exposed.
- The app sets secure headers and HSTS in production; TLS terminates at Caddy/your LB.
- Auth rate limiting is per-process — if you later run multiple backend replicas,
  move rate limiting to a shared store first.
