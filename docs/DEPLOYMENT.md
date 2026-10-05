# Deployment

## Local development (no Docker)

See the [README](../README.md) for the quick start guide. This is the recommended way to
run the demo locally — it uses SQLite and the mock provider, so no external services or
API keys are needed.

## Docker Compose (PostgreSQL + pgvector)

The `docker/docker-compose.yml` file defines a three-service stack:

1. **db** — PostgreSQL 16 with the pgvector extension
2. **backend** — FastAPI application (runs migrations, seeds, starts uvicorn)
3. **frontend** — Nginx serving the built SPA, proxying `/api` to the backend

### Prerequisites

- Docker Engine 24+
- Docker Compose v2+

### Starting the stack

```bash
# From the repository root:
make docker-up

# Or directly:
docker compose -f docker/docker-compose.yml up -d
```

- Frontend: http://localhost
- Backend API: http://localhost:8000/docs
- PostgreSQL: localhost:5432 (bankops / bankops_dev_only)

### Stopping the stack

```bash
make docker-down
```

### Viewing logs

```bash
make docker-logs
```

### Environment variables

Set these in a `.env` file at the repository root before starting the stack:

| Variable | Default | Description |
|---|---|---|
| `POSTGRES_PASSWORD` | `bankops_dev_only` | PostgreSQL password |
| `DEMO_PASSWORD` | `BankOpsDemo!2026` | Local-only demo password |
| `JWT_SECRET_KEY` | `dev_only_secret_change_in_production` | JWT signing key |
| `VITE_API_BASE_URL` | (none) | Backend URL for Vercel deployment |

> **Important:** Change `JWT_SECRET_KEY` and `POSTGRES_PASSWORD` for any non-local deployment.

## Vercel (frontend only)

The `vercel.json` file configures the frontend for Vercel deployment:

1. Build command: `cd frontend && npm ci && npm run build`
2. Output directory: `frontend/dist`
3. API proxy: `/api/*` → `${VITE_API_BASE_URL}/*`

The backend must be hosted separately (e.g., Railway, Fly.io, Render, or any container platform).
Set `VITE_API_BASE_URL` in Vercel environment variables to the backend's public URL.

### Steps

1. Push the repository to GitHub.
2. Import the project in Vercel.
3. Set `VITE_API_BASE_URL` to the backend URL.
4. Deploy.

## Production hardening (not implemented in this demo)

This is a portfolio/interview demonstration. For a production system:

- Use a managed PostgreSQL with pgvector (e.g., Supabase, Neon, RDS).
- Use a secrets manager (e.g., AWS Secrets Manager, HashiCorp Vault).
- Implement mTLS between services.
- Add a WAF and DDoS protection.
- Use a managed container orchestration platform (e.g., ECS, GKE, Cloud Run).
- Set up Prometheus + Grafana for metrics.
- Set up OpenTelemetry + Jaeger/Tempo for distributed tracing.
- Implement log aggregation (e.g., ELK, Loki).
- Add field-level encryption for PII.
- Conduct a formal penetration test.
- Implement a CI/CD pipeline with automated security scanning.
- Use HSM-backed key management for JWT signing.
- Add a SIEM integration for audit events.
- Implement data retention policies with automated purging.
- Add canary deployment and automated rollback.

## Docker daemon availability

The Docker daemon was unavailable during development on this machine. Therefore:

- Dockerfiles and Compose configuration are written and syntax-validated.
- Docker image builds were NOT verified locally.
- The PostgreSQL + pgvector path was NOT verified locally.
- The SQLite + mock provider path (local development) IS fully verified.

To verify the Docker path, run `make docker-up` on a machine with Docker available.
