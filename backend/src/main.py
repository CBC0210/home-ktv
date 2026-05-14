"""FastAPI app 入口。"""
import logging
from contextlib import asynccontextmanager

# Ensure pipeline stages are visible in journald
logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ktv_pipeline.config import settings
from ktv_pipeline.database import init_db, check_db_connection, get_gpu_status, get_db_session
from api import api_router, ws_router, streaming_router

log = logging.getLogger(__name__)


def _recover_stuck_queue_items() -> None:
    """Reset queue items stuck in mid-pipeline states from a previous crash."""
    from ktv_pipeline.models import QueueItem
    stuck = ["processing", "downloading", "separating", "fetching_lyrics", "aligning", "packaging"]
    with get_db_session() as session:
        n = session.query(QueueItem).filter(
            QueueItem.status.in_(stuck)
        ).update({"status": "pending"}, synchronize_session=False)
        session.commit()
        if n:
            log.warning("Startup recovery: reset %d stuck queue items to pending", n)


async def _kick_all_pending_pipelines() -> None:
    """Re-trigger pipeline for every room's pending items (after recovery)."""
    import asyncio
    from ktv_pipeline.models import QueueItem
    from api.songs import _run_pipeline_task

    with get_db_session() as session:
        pending = (
            session.query(QueueItem)
            .filter(QueueItem.status == "pending")
            .order_by(QueueItem.position)
            .all()
        )
    started = 0
    for qi in pending:
        asyncio.create_task(_run_pipeline_task(qi.id, qi.room_id))
        started += 1
    if started:
        log.info("Startup: kicked %d pending pipelines", started)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    _recover_stuck_queue_items()
    await _kick_all_pending_pipelines()
    yield
    # Shutdown — nothing persistent to clean up for now


app = FastAPI(title="Home KTV API", version="0.1.0", docs_url="/docs", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
app.include_router(ws_router, tags=["websocket"])
app.include_router(streaming_router, tags=["streaming"])


@app.get("/")
def root():
    return {"status": "ok", "app": "ktv-backend"}


@app.get("/health")
def health():
    db_ok = check_db_connection()
    return {
        "status": "ok" if db_ok else "degraded",
        "app": "ktv-backend",
        "version": settings.version,
        "db": "connected" if db_ok else "disconnected",
    }


@app.get("/version")
def version():
    """Full version + GPU + DB status endpoint."""
    gpu = get_gpu_status()
    db_ok = check_db_connection()
    return {
        "app": "ktv-backend",
        "version": settings.version,
        "settings": {
            "whisperx_model": settings.whisperx_model,
            "demucs_model": settings.demucs_model,
            "enable_gpu": settings.enable_gpu,
            "data_dir": str(settings.data_dir),
        },
        "gpu": gpu,
        "db": {
            "connected": db_ok,
            "path": str(settings.db_path),
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.local_port)