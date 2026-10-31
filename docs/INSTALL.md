# Installation Guide

## 1. Docker Compose (recommended)

### Requirements
* Docker Engine 24+ with the Compose plugin
* 4 vCPU / 8 GB RAM minimum; scale workers for large bundles
* Disk: roughly **2–3×** the size of the largest `get_logs` you expect to hold at once (upload + extracted working set), plus exports. Mount a large volume at the `qhc_data` volume location.

### Steps
```bash
git clone https://github.com/saket3108/qradar-healthcheckup.git
cd qradar-healthcheckup
cp .env.example .env
```
Edit `.env` (compose refuses to start if the required values are missing):

| Variable | Purpose |
|---|---|
| `POSTGRES_PASSWORD` | database password |
| `QHC_SECRET_KEY` | JWT signing key – `openssl rand -hex 32` |
| `QHC_ADMIN_EMAIL`, `QHC_ADMIN_PASSWORD` | first administrator (created on first start) |
| `QHC_HTTP_PORT` | published port (default 8080) |
| `QHC_WORKER_CONCURRENCY` | parallel jobs per worker container (default 2) |
| `QHC_MAX_UPLOAD_BYTES` | upload ceiling (default 100 GiB) |
| `QHC_LLM_*` | optional OpenAI-compatible endpoint for the assistant |

```bash
docker compose up -d --build
docker compose ps          # all services should become healthy
```
The API container runs `alembic upgrade head` on every start. Open `http://localhost:8080`.

### Scaling and operations
```bash
docker compose up -d --scale worker=4      # more parallel analysis jobs
docker compose logs -f worker              # follow processing
docker compose restart worker              # safe: interrupted jobs are re-queued and resume from the last finished stage
```
* Jobs are `acks_late`; a worker crash redelivers the job, and on API/worker start any job stuck in *processing* beyond `QHC_STALE_JOB_SECONDS` is re-queued.
* Users can also click **Resume** on a failed assessment to restart from the failed stage.

### TLS
The `web` container serves plain HTTP. Put it behind your TLS terminator (corporate load balancer, Traefik, Caddy, or an nginx/HAProxy in front). Forward `X-Forwarded-Proto`. Because download links use a `?token=` query parameter, **do not expose the service over plain HTTP outside a trusted network**.

### Backups
* Database: `docker compose exec postgres pg_dump -U qhc qhc > qhc-$(date +%F).sql`
* Files (uploads, extracted data, exports, logos): back up the `qhc_data` volume.
* Restore the database before starting the API; migrations are applied automatically.

### Upgrades
```bash
git pull
docker compose up -d --build     # migrations run automatically
```

## 2. Local development (no Docker)

Requirements: Python 3.12, Node 20+. Redis and PostgreSQL are optional (SQLite + in-process workers are the defaults).

```bash
# backend
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
(cd pptx_gen && npm install)                       # PowerPoint generator
export QHC_ADMIN_EMAIL=admin@example.com QHC_ADMIN_PASSWORD='ChangeMe12345'
uvicorn app.main:create_app --factory --reload --port 8000

# frontend (separate shell) – Vite proxies /api to :8000
cd frontend
npm ci
npm run dev                                         # http://localhost:5173
```

Use PostgreSQL + Celery locally:
```bash
export QHC_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/qhc
alembic upgrade head
export QHC_RUN_MODE=celery QHC_REDIS_URL=redis://localhost:6379/0
celery -A app.pipeline.celery_app worker --loglevel=INFO
```

SQLite creates its tables automatically at start-up; **PostgreSQL always uses Alembic**.

## 3. Roles

| Role | View | Upload | Edit comments / report | Export | Delete | Audit | Manage users |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| Administrator | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |
| IBM Consultant | ✔ | ✔ | ✔ | ✔ | | | |
| Manager | ✔ | | | ✔ | | ✔ | |
| Read Only | ✔ | | | | | | |

## 4. Configuration reference (backend)

All settings use the `QHC_` prefix (see `backend/app/core/config.py`): `DATABASE_URL`, `STORAGE_DIR`, `SECRET_KEY`, `ACCESS_TOKEN_MINUTES`, `RUN_MODE` (`inline`|`celery`), `REDIS_URL`, `INLINE_WORKERS`, `PARSE_WORKERS`, `STALE_JOB_SECONDS`, `MAX_UPLOAD_BYTES`, `UPLOAD_CHUNK_BYTES`, `MAX_ARCHIVE_FILES`, `MAX_EXTRACTED_MEMBER_BYTES`, `MAX_TOTAL_EXTRACTED_BYTES`, `MAX_COMPRESSION_RATIO`, `MAX_NESTED_DEPTH`, `MAX_ROWS_PER_TABLE`, `LOGIN_MAX_FAILURES`, `LOGIN_LOCKOUT_MINUTES`, `CORS_ORIGINS`, `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `NODE_BIN`.

## 5. Troubleshooting

| Symptom | Check |
|---|---|
| Compose says a variable is required | fill the value in `.env` |
| API exits with "QHC_SECRET_KEY must be set" | production mode needs a non-default secret |
| Upload stalls at the proxy | ensure any extra reverse proxy has `client_max_body_size 0`, `proxy_request_buffering off` and long timeouts (see `frontend/nginx.conf`) |
| Assessment *partial* | one or more stages produced warnings (e.g. a dump file not present in that QRadar version); open the assessment to see the stage messages, fix and **Resume** |
| PPTX export fails | Node is missing from the API image/host, or `pptx_gen` dependencies are not installed |
| Everything parses but sections are empty | the bundle layout differs from what the parsers expect; see the note in the README and `app/ingestion/classify.py` |
