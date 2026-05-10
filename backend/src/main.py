"""FastAPI app 入口。"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ktv_pipeline.config import settings
from ktv_pipeline.database import init_db
from api import api_router

app = FastAPI(title="Home KTV API", version="0.1.0", docs_url="/docs")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/")
def root():
    return {"status": "ok", "app": "ktv-backend"}


@app.get("/health")
def health():
    return {"status": "ok", "app": "ktv-backend", "version": "0.1.0"}


if __name__ == "__main__":
    import uvicorn
    init_db()
    uvicorn.run(app, host="0.0.0.0", port=settings.local_port)
