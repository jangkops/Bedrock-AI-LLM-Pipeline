---
inclusion: always
---

# Technology Stack & Conventions

## Architecture

Three-tier: React SPA → Flask microservices (Docker Compose) + serverless Bedrock gateway.

| Layer | Stack | Access |
|-------|-------|--------|
| Frontend | React 18, Vite, Tailwind CSS, React Router | nginx :80 |
| backend-admin | Flask (Python 3.x), Blueprint routes | :5000 |
| backend-cost | Flask (Python 3.x), Blueprint routes | :5001 |
| Bedrock Gateway | API Gateway (AWS_IAM) + Lambda (Python 3.12) + DynamoDB | Serverless — NOT Flask |

## Frontend Rules

- Vite build, source in `account-portal/frontend/`
- Tailwind CSS styling, Framer Motion animations, Heroicons, xlsx-js-style for Excel
- One page component per route in `src/pages/`; shared layout in `src/components/Layout.jsx`
- API client: `src/api.js`

## Backend Microservice Rules

- Two Flask services in Docker Compose: backend-admin (:5000), backend-cost (:5001)
- Blueprint per feature in `routes/`; registered in `app.py` with prefix `/api/<feature>`
- Flask-CORS enabled; JWT auth via PyJWT (HS256, secret from env `JWT_SECRET_KEY`)
- **All admin-plane routes MUST use `@admin_required` decorator** — no exceptions
- boto3 for AWS SDK, redis for caching, python-dotenv for env config
- DynamoDB `Decimal` values MUST be converted to int/float before JSON serialization

## Bedrock Gateway Rules

- Serverless control plane: API Gateway Regional REST API (AWS_IAM auth) → Lambda → Bedrock
- DynamoDB table naming: `bedrock-gw-{env}-{region}-{table}`
- IaC: Terraform only (`infra/bedrock-gateway/`). No SAM, no CDK.
- Ansible is for existing container/host ops — NOT for gateway infra
- backend-admin provides admin UI API only — it is NOT an inference proxy
- v1 scope: Converse API only. ConverseStream, InvokeModel deferred to v2.
- Full spec: `.kiro/specs/bedrock-access-gateway/`

### Quota Model

| Parameter | Value |
|-----------|-------|
| Default per-user limit | KRW 500,000/month |
| Hard cap | KRW 2,000,000/month |
| Approval increment | KRW 500,000 fixed |
| Global monthly budget | KRW 10,000,000 |
| Enforcement | Near-real-time via DynamoDB (not Cost Explorer) |
| Month boundary timezone | KST (UTC+9) |

### User Classification

| Type | Behavior |
|------|----------|
| Gateway-managed | Registered in `principal_policy`, subject to quota/approval enforcement |
| Exception (direct-use) | Direct Bedrock access, monitoring-only via CloudWatch Logs, listed in `EXCEPTION_USERS` dict |

Classification is an explicit operator decision. Never auto-promote users between types.

### Data Key Patterns

- Model pricing: strict `model_id` match, no normalization. Add every inference profile variant as a separate entry.
- Monthly usage PK: `{principal_id}#{YYYY-MM}`, SK: `model_id`
- Principal ID format: `{account_id}#BedrockUser-{username}`

## Route Organization

| Service | Directory | Pattern |
|---------|-----------|---------|
| backend-admin | `backend-admin/routes/` | One file per feature domain |
| backend-cost | `backend-cost/routes/` | Same pattern |
| Gateway read | `gateway_usage.py` | Read-only monitoring endpoints |
| Gateway approval | `gateway_approval.py` | Approval CRUD endpoints |

Each blueprint registered in its service's `app.py`.

## Infrastructure

- Docker Compose: `docker-compose-fixed.yml`
- Containers: `userportal-backend-admin`, `userportal-backend-cost`, `userportal-nginx`
- Nginx reverse proxy; Redis caching; AWS SSM for remote execution; IAM Identity Center for SSO

## AWS CLI Convention

Always inline credentials. Never assume prior `export` commands persist:
```bash
env AWS_PROFILE=virginia-sso AWS_REGION=us-west-2 AWS_DEFAULT_REGION=us-west-2 AWS_PAGER="" aws ...
```

## Common Commands

```bash
# Frontend dev
cd account-portal/frontend && npm run dev
# Frontend build
cd account-portal/frontend && npm run build
# Backend rebuild
cd account-portal && docker compose -f docker-compose-fixed.yml up -d --build
# Logs
docker logs userportal-backend-admin
docker logs userportal-backend-cost
docker logs userportal-nginx
# Ansible (from backend container)
cd /home/app/ansible && ansible-playbook -i regions/<region>/inventory <playbook>.yml
```

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `AWS_DEFAULT_REGION` | us-west-2 |
| `BEDROCK_GW_ENV` | dev (DynamoDB table prefix) |
| `JWT_SECRET_KEY` | Portal auth secret |

AWS credentials mounted from `~/.aws`. GitHub tokens in `.env` (not committed). Backend services use host network mode or exposed ports.

## Non-Disruption Policy

- Bedrock gateway is additive — do not modify existing shared infra
- Do not modify VPC, SG, EC2, nginx, docker-compose runtime, or backend service runtime paths without explicit approval
- FSx user environments (~/.aws, SSO bootstrap, shell init) require separate approval gate
- Full policy: `.kiro/steering/devops-operating-model.md`

## LLM Usage Budget

Default model: Claude Sonnet 4.6. Opus 4.6 only for explicitly approved architecture reviews, complex debugging, or large multi-file reasoning. Prefer targeted file reads over whole-repo scans. Keep RAG context under 8K tokens unless approved. Summarize prior context instead of replaying history.

| Model | Default | Detailed | Hard Ceiling |
|-------|---------|----------|-------------|
| Haiku | 100K | 150K | 200K |
| Sonnet | 120K | 200K | 300K |
| Opus | 150K | 250K | 400K |
