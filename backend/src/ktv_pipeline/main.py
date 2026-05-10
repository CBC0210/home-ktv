from contextlib import asynccontextmanager

from fastapi import FastAPI


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="Home KTV API", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


def run():
    import uvicorn
    uvicorn.run("ktv_pipeline.main:app", host="0.0.0.0", port=8000, reload=False)
