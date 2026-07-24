from contextlib import asynccontextmanager

from fastapi import FastAPI

from .database import init_db
from api import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Home KTV API", version="0.1.0", lifespan=lifespan)
app.include_router(api_router)


@app.get("/health")
async def health():
    return {"status": "ok", "app": "ktv-backend", "version": "0.1.0"}


def run():
    import uvicorn
    uvicorn.run("ktv_pipeline.main:app", host="0.0.0.0", port=8000, reload=False)
