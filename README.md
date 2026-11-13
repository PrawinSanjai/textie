# Textie

Textie is a temporary chat application. PostgreSQL stores conversations and encrypted message history. Redis coordinates shared rate limits, live events, and expiring presence leases across backend workers. PostgreSQL remains authoritative; Redis Pub/Sub is deliberately ephemeral.

## Requirements

- Python 3.13+
- PostgreSQL
- Redis
- Node.js

## Backend

In `backend`, copy `.env.example` to `.env`, then set `DATABASE_URL`, `CRYPT_SECRET_KEY`, and `REDIS_URL`. Start the local Redis service from the `backend` directory:

```powershell
docker compose up -d redis
```

The Docker Desktop daemon must be running. The Compose service binds Redis to localhost only. Set `REDIS_URL=redis://localhost:6379/0` for this local service. Generate a Fernet key with:

```powershell
poetry run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Install dependencies, apply the database migrations, then start the API:

```powershell
poetry install
poetry run alembic upgrade head
poetry run uvicorn main:api --reload --host 127.0.0.1 --port 8000
```

Redis applies shared rolling-window limits for room creation (5/minute), join attempts (8/minute), and messages (30/10 seconds per participant). Set the corresponding `*_RATE_LIMIT` and `*_WINDOW_SECONDS` values in `backend/.env`. Rooms default to a two-participant cap and a one-hour hard expiry. Inactive rooms are deleted after the configured grace period. Message history uses ordered, paginated sequence cursors, and clients attach idempotency IDs so retries after reconnect do not create duplicates.

For multiple backend workers, disable reload and start multiple workers, for example:

```powershell
poetry run uvicorn main:api --host 0.0.0.0 --port 8000 --workers 4
```

Redis Pub/Sub broadcasts live events to sockets connected to every worker. Presence is represented by expiring Redis leases renewed by WebSocket heartbeats. Slow consumers are isolated behind bounded per-socket send queues. The browser authenticates a WebSocket using its participant credential in the first frame (never in the URL), acknowledges persisted messages, and requests missing pages after reconnecting.

Database connections per backend deployment are approximately `worker_count * (DB_POOL_SIZE + DB_MAX_OVERFLOW)`. Keep those settings within the PostgreSQL connection budget.

Run `poetry run alembic upgrade head` after upgrading to add durable message sequence and retry-idempotency columns. `/health/live` checks process liveness, `/health/ready` checks PostgreSQL and Redis, and `/metrics` exposes aggregate counters and pool wait statistics. Restrict metrics to your monitoring network at the proxy/firewall.

For production, terminate TLS at a trusted reverse proxy and expose only HTTPS/WSS. Configure Uvicorn proxy headers with the exact trusted proxy addresses (`--proxy-headers --forwarded-allow-ips="<trusted-proxy-ips>"`); never trust arbitrary forwarded client IP headers. Use private Redis/PostgreSQL endpoints and `rediss://` when Redis traffic crosses an untrusted network. This no-login app has no browser-side API secret: participant tokens are capabilities, so serve the frontend only over HTTPS and avoid logging request bodies or WebSocket frames.

## Frontend

In `frontend`, copy `.env.example` to `.env` if you need to change the API URL, then run:

```powershell
npm install
npm run dev
```

The frontend defaults to `http://localhost:8000`; Vite normally serves it at `http://localhost:5173`.
