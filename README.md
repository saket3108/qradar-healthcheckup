# QRadar Health Checkup Platform

Upload an IBM QRadar `get_logs` package and get a customer-ready health assessment in one workflow: executive dashboard, deployment diagram, notification / log source / WinCollect / application / performance / licensing analysis, a weighted health score, an AI assistant grounded in the uploaded data, and PDF, Word and PowerPoint exports.

Built for IBM Sales, Technical Sales, Consultants, Lab Services, QRadar Support and Business Partners.

> **Status and honesty note.** The platform is feature-complete against the original specification and is covered by automated tests (backend 109 tests / 91 % coverage, frontend 64 tests / 94 % line coverage). The parsers and tests were developed against a **synthetic** bundle produced by [`tools/make_sample_getlogs.py`](tools/make_sample_getlogs.py), which mirrors the layout the parsers expect. **Real `get_logs` packages vary by QRadar version and fix pack and have not yet been validated here.** Run it against a few real, non-sensitive bundles before using it in a customer engagement, and expect to adjust parser path/column mappings in `backend/app/parsers/` and `backend/app/pipeline/collect.py`. The Docker images and Compose stack were written but not executed on the author's machine (no Docker available), and the CI workflow in `docs/ci/github-actions-ci.yml` has not been run. To enable CI, copy it to `.github/workflows/ci.yml` (pushing workflow files needs a token with the `workflow` scope); it runs the backend tests against PostgreSQL, the frontend typecheck/tests/build, and builds both images.

## What you get

| Area | Capability |
|---|---|
| Ingestion | `.tar`, `.tar.gz`, `.tgz`, `.gz`, `.zip`; chunked **resumable** upload (>10 GB), multiple uploads, hardened streaming extraction |
| Security | Zip Slip / path traversal, absolute paths, symlink/hardlink/device entries, decompression-bomb limits (size, ratio, file count, nesting), magic-byte validation, duplicate members |
| Pipeline | 11 checkpointed stages, per-stage progress, resume from the failed stage, stale-job recovery after a crash, Celery + Redis workers (or in-process pool for dev) |
| Dashboard | Overall score /100, 7 category scores, critical/high/medium/low counts, top-10 recommendations, executive summary |
| Overview | Version / fix pack / deployment type, appliances (CPU, RAM, disk, managed host ID), licence gauges, log source / WinCollect / notification / application / auto-update / hardware summaries |
| Deployment | React Flow topology (Console, EP, EC, FP, DN, App Host, Extension, Unknown), HA analysis, validation checks (PASS / WARNING / CRITICAL) |
| Notifications | Every notification from `notification_view` with root cause, impact, risk, recommendation, IBM best practice and an editable consultant comment |
| Log sources | Status, EPS, protocol analysis (bar/pie/treemap), problematic and silent sources, WinCollect agents and version distribution, editable recommendations |
| Applications | `installed_application` / `installed_application_instance`; detects restart loops, outdated versions, memory / storage / permission issues |
| Performance | CPU, memory, disk (incl. `await`, `r_await`, `w_await`, `avgrq-sz`, `avgqu-sz`), network, SAR metrics, top-10 processes, per-metric AI assessment |
| Licensing | EPS and FPM licensed / current / peak, consumption %, growth trend, forecast, days-to-limit, utilisation risk |
| Health score | Weighted category scoring, overall grade, risk score, maturity level; changing a finding re-scores the assessment |
| AI assistant | Chat over the assessment ("Why is health score low?", "What should the customer fix first?", "Explain this notification" …); optional OpenAI-compatible LLM augmentation |
| Reports | Report Builder (customer, consultant, logo, sections, notes, next steps) → **PDF**, editable **DOCX**, 13-slide **PPTX** |
| Knowledge base | 40 QRadar-specific entries (DSM, parsing, licence, disk, HA, app framework, search, SAR, WinCollect, deployment, storage, backup, app containers), each mapped to description / impact / risk / recommendation / IBM best practice / priority |
| Access & audit | Email + password, RBAC (Administrator, IBM Consultant, Manager, Read Only), audit trail for report creation, modification, comment updates and exports |
| UX | Dark by default with light mode, glass surfaces, animated charts, responsive |

## Quick start (Docker)

```bash
cp .env.example .env
# edit .env: set POSTGRES_PASSWORD, QHC_SECRET_KEY (openssl rand -hex 32), QHC_ADMIN_EMAIL, QHC_ADMIN_PASSWORD
docker compose up -d --build
open http://localhost:8080
```

Sign in with the administrator from `.env`, drop a `get_logs` archive on **Assessments**, and watch the stages run. See [docs/INSTALL.md](docs/INSTALL.md) for production notes, scaling workers, TLS, backups and local (non-Docker) development, and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for design details.

## Try it without a real bundle

```bash
python tools/make_sample_getlogs.py sample_data/troubled.tar.gz --profile troubled
python tools/make_sample_getlogs.py sample_data/healthy.tar.gz  --profile healthy
```

The data is fabricated; no customer information is involved.

## Repository layout

```
backend/    FastAPI app, Alembic migrations, parsers, analysis, reports, pptxgenjs generator, tests
frontend/   React 19 + Vite + Tailwind SPA, Vitest tests, nginx config
tools/      synthetic get_logs generator
docs/       installation guide, architecture
docker-compose.yml, .env.example
docs/ci/     GitHub Actions workflow (copy to .github/workflows/ to enable)
```

## Testing

```bash
# backend (SQLite by default; set QHC_TEST_DATABASE_URL for PostgreSQL after `alembic upgrade head`)
cd backend && pip install -r requirements.txt -r requirements-dev.txt && (cd pptx_gen && npm install) && python -m pytest

# frontend
cd frontend && npm ci && npm run typecheck && npm test && npm run build
```

Backend coverage is gated at 80 % in `backend/pytest.ini`; frontend gates are in `frontend/vite.config.ts` (lines/statements 80 %, functions/branches 70 %).

## Security notes

* Set a strong `QHC_SECRET_KEY`; in `production` the API refuses to start with the development default.
* Passwords are bcrypt-hashed; repeated failed logins are throttled and locked out.
* Download links accept a `?token=` so the browser can stream large exports; serve the app over HTTPS so tokens are not exposed in transit, and note tokens can appear in proxy access logs.
* `get_logs` bundles contain sensitive customer data. Restrict access to the host/volume, define a retention policy, and delete assessments when engagements end (Administrator role).
* Uploaded archives are treated as hostile: only whitelisted member types are extracted, with hard size/ratio/count limits.
