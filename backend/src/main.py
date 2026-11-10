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


def _seed_default_room() -> None:
    """First-run: create the default 'home' room if NO rooms exist yet.

    Without this a fresh deploy lands every URL on "Room not found" and the
    deployer has to hand-insert a row. Password comes from
    DEFAULT_ROOM_PASSWORD (empty = open room, fine on a private LAN)."""
    from ktv_pipeline.models import Room
    from ktv_pipeline.auth import hash_password
    with get_db_session() as session:
        if session.query(Room.id).first():
            return
        pw = settings.default_room_password
        session.add(Room(
            id="home",
            name="Home",
            is_default=True,
            password_hash=hash_password(pw) if pw else None,
        ))
        session.commit()
        log.info("First run: seeded default room 'home' (password %s)",
                 "set" if pw else "not set")


def _migrate_admin_password_column() -> None:
    """Idempotently add the rooms.admin_password_hash column (SQLite ALTER)."""
    from sqlalchemy import text
    with get_db_session() as session:
        cols = session.execute(text("PRAGMA table_info(rooms)")).fetchall()
        names = {c[1] for c in cols}
        if "admin_password_hash" not in names:
            session.execute(text("ALTER TABLE rooms ADD COLUMN admin_password_hash VARCHAR(256)"))
            session.commit()
            log.info("Added rooms.admin_password_hash column")


def _seed_default_admin_passwords() -> None:
    """Disable predictable historical room-admin passwords, never seed one."""
    from ktv_pipeline.models import Room
    from ktv_pipeline.auth import verify_password
    with get_db_session() as session:
        for room in session.query(Room).all():
            if room.admin_password_hash and verify_password(f"{room.id}admin", room.admin_password_hash):
                room.admin_password_hash = None
        session.commit()


async def _kick_all_pending_pipelines() -> None:
    """Re-trigger pipeline for every room's pending items (after recovery).

    Items whose Song is ALREADY processed are promoted straight to 'ready'
    instead of re-running the orchestrator: the redundant run was the trigger
    for the status-stomp bug (its final write raced the playback flow marking
    the same item 'playing'), and it churned broadcasts for no benefit.
    """
    import asyncio
    from ktv_pipeline.models import QueueItem, Song
    from api.songs import _run_pipeline_task

    to_kick = []
    promoted = 0
    with get_db_session() as session:
        pending = (
            session.query(QueueItem)
            .filter(QueueItem.status == "pending")
            .order_by(QueueItem.position)
            .all()
        )
        for qi in pending:
            song = session.query(Song).filter_by(id=qi.song_id).first()
            if song and song.status == "ready":
                qi.status = "ready"
                promoted += 1
            else:
                to_kick.append((qi.id, qi.room_id))
        session.commit()
    for qi_id, room_id in to_kick:
        asyncio.create_task(_run_pipeline_task(qi_id, room_id))
    if promoted or to_kick:
        log.info("Startup: promoted %d already-ready items, kicked %d pipelines",
                 promoted, len(to_kick))


# Rooms with zero connected clients for longer than this get their queue
# cleared and go to standby — stops pipeline/playback churn on idle rooms.
IDLE_CLEANUP_MINUTES = 30
_room_empty_since: dict = {}


async def _idle_room_cleanup_loop() -> None:
    """Every 5 min: any room with no WS clients for >30 min → clear its
    active queue + reset playback → standby. Saves resources."""
    import asyncio
    from datetime import datetime, timezone
    from ktv_pipeline.ws_manager import manager
    from ktv_pipeline.models import QueueItem, Room
    from ktv_pipeline.queue_manager import QueueManager

    while True:
        await asyncio.sleep(300)
        try:
            now = datetime.now(timezone.utc)
            with get_db_session() as s:
                room_ids = [r.id for r in s.query(Room.id).all()]
            for rid in room_ids:
                has_clients = len(manager.get_room_clients(rid)) > 0
                if has_clients:
                    _room_empty_since.pop(rid, None)
                    continue
                with get_db_session() as s:
                    active = (
                        s.query(QueueItem)
                        .filter(QueueItem.room_id == rid)
                        .filter(QueueItem.status.in_(QueueManager.ACTIVE_STATUSES))
                        .count()
                    )
                if active == 0:
                    _room_empty_since.pop(rid, None)
                    continue
                since = _room_empty_since.setdefault(rid, now)
                if (now - since).total_seconds() < IDLE_CLEANUP_MINUTES * 60:
                    continue
                # Idle long enough — clear the room's queue
                with get_db_session() as s:
                    n = (
                        s.query(QueueItem)
                        .filter(QueueItem.room_id == rid)
                        .filter(QueueItem.status.in_(QueueManager.ACTIVE_STATUSES))
                        .update({"status": "done"}, synchronize_session=False)
                    )
                    s.commit()
                _room_empty_since.pop(rid, None)
                manager.update_playback_state(rid, is_playing=False, position_sec=0)
                await manager.broadcast_song_ended(rid, -1)
                await manager.broadcast_queue_updated(rid, [])
                log.info("Idle cleanup: room %s cleared %d items → standby", rid, n)
        except Exception as exc:
            log.warning("idle cleanup loop error: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    _migrate_admin_password_column()
    _seed_default_room()
    _recover_stuck_queue_items()
    if settings.admin_password in ("admin", "") or "change" in settings.admin_cookie_secret:
        log.warning(
            "SECURITY: ADMIN_PASSWORD / ADMIN_COOKIE_SECRET still at defaults — "
            "set real values in .env before exposing this server beyond your LAN"
        )
    # Heavy bcrypt-hashing seed runs in a background thread so it doesn't
    # block startup (test fixtures left ~500 orphan rooms in DB).
    import asyncio
    asyncio.create_task(asyncio.to_thread(_seed_default_admin_passwords))
    await _kick_all_pending_pipelines()
    asyncio.create_task(_idle_room_cleanup_loop())
    yield
    # Shutdown — nothing persistent to clean up for now


app = FastAPI(title="Home KTV API", version="0.1.0", docs_url="/docs", lifespan=lifespan)

# CORS: pin to the public origin (from PUBLIC_BASE_URL) plus LAN/private
# origins via regex, instead of reflecting ANY origin. In the tunnel
# deployment the page and API share one origin so CORS isn't exercised; the
# regex only matters for the zero-config LAN mode (page :3002 → API :8000).
_LAN_ORIGIN_RE = (
    r"^https?://(localhost|127\.0\.0\.1|"
    r"(?:10|127)(?:\.\d{1,3}){3}|"
    r"(?:192\.168|169\.254)(?:\.\d{1,3}){2}|"
    r"172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}|"
    r"[A-Za-z0-9-]+\.local)(:\d+)?$"
)
_allowed_origins = [o for o in [settings.public_base_url] if o]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_origin_regex=_LAN_ORIGIN_RE,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _security_headers(request, call_next):
    """Baseline security response headers on every HTTP response (the tunnel
    can't inject them, and nginx isn't in the live path)."""
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return resp

from ktv_pipeline.security import security_guard, RedactSessionTokens
for _logger_name in ("uvicorn.error", "uvicorn.access"):
    logging.getLogger(_logger_name).addFilter(RedactSessionTokens())
app.middleware("http")(security_guard)

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