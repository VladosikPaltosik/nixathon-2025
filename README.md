# api

FastAPI project with health check endpoint.

## Run

```bash
uvicorn src/main:app --reload
```

Or:

```bash
fastapi dev src/main.py
```

## Endpoints

- `GET /` - Root endpoint
- `GET /health` - Health check endpoint

Access API docs at `http://localhost:8000/docs`
