"""FastAPI app 入口。"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ktv_pipeline.config import settings
from ktv_pipeline.database import init_db, check_db_connection, get_gpu_status
from api import api_router, ws_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
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