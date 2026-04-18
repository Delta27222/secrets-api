# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Tek Secrets** is a monorepo containing:
- **CLI** (`cli/`): Python CLI tool for managing secrets across projects and environments
- **API** (`api/`): FastAPI backend providing secrets management, integrations with GitHub/Render/Vercel, and logging

The project uses GitHub OAuth for authentication and integrates with multiple deployment platforms.

## Directory Structure

```
tek-secrets/
├── cli/                      # Typer CLI application
│   ├── tek_secrets/         # Main CLI package
│   ├── pyproject.toml       # Poetry configuration
│   └── README.md            # CLI command documentation
│
└── api/                      # FastAPI backend
    ├── app/
    │   ├── main.py          # FastAPI app initialization
    │   ├── api/v1/          # API v1 endpoints
    │   │   ├── endpoints/   # Route handlers (auth, users, projects, etc.)
    │   │   └── api.py       # Router aggregation
    │   ├── core/            # Configuration and utilities
    │   │   ├── config.py    # Environment config (GitHub, MongoDB, AWS, QuestDB)
    │   │   ├── auth.py      # GitHub OAuth logic
    │   │   ├── logging.py   # LoggingMiddleware for request/service tracing
    │   │   ├── context.py   # ContextVar for request tracking
    │   │   ├── questdb_orm.py  # QuestDB query builder
    │   │   └── security.py  # JWT/token utilities
    │   ├── models/          # Pydantic models + MongoDB collections
    │   │   ├── dbmodel.py   # Base MongoDB model
    │   │   ├── user.py, organization.py, project.py, etc.
    │   │   └── logs.py      # Logging models for QuestDB
    │   ├── services/        # Business logic layer
    │   │   ├── auth.py, users.py, organizations.py
    │   │   ├── sqs.py       # AWS SQS queue processing
    │   │   ├── logs.py      # QuestDB logging service
    │   │   └── vercel.py, render.py  # Deployment integrations
    │   └── db/              # Database connection utilities
    │       └── mongodb_utils.py
    └── requirements.txt
```

## Command Reference

### CLI Setup & Running
```bash
# Install dependencies (Poetry)
cd cli
poetry install

# Run CLI locally (dev mode)
poetry run tek-secrets [COMMAND]

# Build/install locally
cd cli && npm install  # Will auto-run pip install -e .
```

### API Setup & Running
```bash
# Setup virtual environment and install dependencies
cd api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run API locally
.venv/bin/fastapi dev app/main.py

# Deactivate virtual environment
deactivate
```

## Architecture & Key Concepts

### Authentication Flow
1. **GitHub OAuth**: User initiates login → CLI/API redirects to GitHub OAuth → GitHub returns access token
2. **Token Storage**: Tokens stored in OS keyring (CLI) or session (API)
3. **API Auth**: Endpoints protected by JWT token validation via `core/security.py`

### Database Layer
- **MongoDB**: Primary storage for users, organizations, projects, environments, and memberships
- **QuestDB**: Time-series database for API request/service logs and audit trails
- **Collections** (MongoDB):
  - `users`, `organizations`, `projects`, `environments`
  - `project_members`, `organization_members`
  - Tracked via models in `app/models/`

### Service Architecture
- **Endpoints** (`api/v1/endpoints/`): HTTP route handlers, request validation
- **Services** (`app/services/`): Business logic, database operations, external API calls
- **LoggingMiddleware** (`core/logging.py`): Automatically logs all HTTP requests and service calls to QuestDB
- **ContextVar** (`core/context.py`): Request-scoped context for distributed tracing

### External Integrations
- **GitHub**: OAuth + GraphQL queries for repository data
- **Render**: API for deployment environment management
- **Vercel**: API for project and environment variable sync
- **AWS SQS**: Queue for async log processing
- **QuestDB**: Logging endpoint at `EC2_INSTANCE_IP:EC2_INSTANCE_PORT` (default: 52.91.246.92:9000)

## Environment Variables

**API** (`api/.env`):
```
# Auth
GITHUB_CLIENT_ID=[clientId]
GITHUB_CLIENT_SECRET=[token]

# Database
MONGODB_URL=mongodb+srv://...
MONGO_DB=secrets-27222

# Deployments
RENDER_API_URL=https://api.render.com/v1
VERCEL_API_URL=https://api.vercel.com/v10/projects

# AWS SQS
SQS_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/...
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION_NAME=us-east-1

# QuestDB Logging
EC2_INSTANCE_IP=52.91.246.92
EC2_INSTANCE_PORT=9000

# General
SECRET_KEY=[jwt_secret]
MAX_CONNECTIONS_COUNT=10
MIN_CONNECTIONS_COUNT=10
```

**CLI** (`cli/.env`): GitHub client ID/secret (loaded from system keyring).

## Common Development Tasks

### Adding a New Endpoint
1. Create handler in `api/app/api/v1/endpoints/[resource].py`
2. Add business logic to `api/app/services/[resource].py`
3. Define Pydantic models in `api/app/models/[resource].py` if needed
4. Include router in `api/app/api/v1/api.py`
5. Requests automatically logged via `LoggingMiddleware`

### Adding a New Model/Collection
1. Define in `api/app/models/[resource].py` (inherit from `DBModel` if MongoDB)
2. Create service methods in `api/app/services/[resource].py`
3. Add CRUD endpoints if needed

### Debugging Requests
- Check `api.log` for request/service logs (populated by `LoggingMiddleware`)
- QuestDB stores logs in `http_logs` and `service_logs` tables
- Use `core/context.py` context variables to trace requests through multiple services

## Notes

- **GitHub OAuth credentials** are stored in `config.py` (see marked ✅ AVILA sections for production/staging toggles)
- **Logging**: All API requests and service calls automatically logged to QuestDB and `api.log` file
- **Async**: All database operations use async drivers (Motor for MongoDB, asyncpg for PostgreSQL)
- **Dependencies**: Keep `requirements.txt` (API) and `pyproject.toml` (CLI) in sync with actual imports
- **MongoDB indices**: Assumed to exist on collections; add migration code if needed
