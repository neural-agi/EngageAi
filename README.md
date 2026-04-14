# EngageAI

EngageAI is a full-stack multi-agent system for LinkedIn engagement automation. The repo includes:
- `backend/`: FastAPI API, orchestration pipeline, agents, scheduling, and execution simulation
- `frontend/`: Next.js 14 dashboard
- `docker-compose.yml`: one-command local stack for backend, frontend, Postgres, and Redis

## Prerequisites

- Python 3.12+
- Node.js 20+
- npm
- Docker and Docker Compose (optional, recommended for full-stack local runs)

## Environment Setup

1. Copy the example env file:

```bash
cp .env.example .env
```

2. Set the required variables in `.env`:
- `OPENAI_API_KEY`
- `SESSION_MANAGER_SECRET`

`DATABASE_URL` is optional for now, but the Docker setup provides a working default.

## Backend Setup

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Backend endpoints:
- `GET /`
- `GET /health`
- `POST /run`

The backend validates required env vars at startup and exits early if they are missing.

## Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Frontend env:
- `NEXT_PUBLIC_API_BASE_URL`

If unset, the frontend defaults to `http://localhost:8000`.

## Run Everything with Docker

```bash
docker compose up --build
```

This starts:
- FastAPI backend on `http://localhost:8000`
- Next.js frontend on `http://localhost:3000`
- Postgres
- Redis

Production-style compose:

```bash
docker compose -f docker-compose.prod.yml up --build
```

## Health Check

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{
  "status": "ok",
  "service": "EngageAI API"
}
```

## Notes

- Logs are structured JSON on the backend.
- The pipeline logs startup, persona selection, and execution results.
- API errors return structured JSON instead of raw tracebacks.
