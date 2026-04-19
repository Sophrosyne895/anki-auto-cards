"""FastAPI application: HTTP endpoints for the Anki auto-card pipeline."""
import logging
import logging.handlers
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import anki_connect
import job_status
import queue_store
import worker
from config import AUTH_TOKEN, LOG_FILE, PORT

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def _setup_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")

    # Rotating file handler (10MB × 5 files)
    fh = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # Console
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    root.addHandler(ch)


_setup_logging()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    worker.start_worker()
    logger.info("Anki pipeline server starting on port %d", PORT)
    yield
    logger.info("Anki pipeline server shutting down")


app = FastAPI(title="Anki Auto-Card Pipeline", lifespan=lifespan)

# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if request.url.path in ("/health", "/jobs"):
        return await call_next(request)
    if AUTH_TOKEN:
        token = request.headers.get("X-Token", "")
        if token != AUTH_TOKEN:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    return await call_next(request)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class SubmitRequest(BaseModel):
    url: str

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    anki_up = anki_connect.is_anki_running()
    pending = queue_store.peek_depth()
    return {
        "status": "ok",
        "anki_running": anki_up,
        "pending_cards": pending,
    }


@app.get("/jobs")
async def jobs():
    return {"jobs": job_status.get_all()}


@app.post("/submit")
async def submit(body: SubmitRequest):
    url = body.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="url is required")

    job_id = str(uuid.uuid4())[:8]
    worker.submit_job(url, job_id)

    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "job_id": job_id,
            "message": f"Processing started for: {url}",
        },
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, log_config=None)
