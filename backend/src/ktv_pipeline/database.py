"""資料庫 engine、session 工廠。"""
from contextlib import contextmanager
from typing import Generator, Optional
import subprocess
import re

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker, declarative_base

from .config import settings

Base = declarative_base()
_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(
            f"sqlite+pysqlite:///{settings.db_path}",
            connect_args={"check_same_thread": False},
            pool_size=5,
            max_overflow=10,
        )
    return _engine


def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _SessionLocal


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    SessionLocal = get_session_factory()
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_db_connection() -> bool:
    """Ping the database — returns True if SQLite responds."""
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def init_db() -> None:
    """Create all tables and configure SQLite WAL mode."""
    from . import models as _models  # noqa: F401 — registers all ORM classes with Base
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    # Enable WAL mode for better concurrent read performance
    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))
        conn.execute(text("PRAGMA synchronous=NORMAL"))
        conn.commit()


def get_gpu_status() -> dict:
    """Query nvidia-smi for GPU name, memory, temperature.
    
    Returns a dict with available GPU info.  If nvidia-smi is absent or
    the driver is not loaded, returns {"available": False, "reason": ...}.
    """
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.used,memory.total,temperature.gpu,utilization.gpu",
                "--format=csv,noheader,nospace",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return {"available": False, "reason": "nvidia-smi non-zero exit"}
        line = result.stdout.strip()
        # format: "name,memory.used MiB,memory.total MiB,temperature.gpu C,utilization.gpu %"
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 5:
            return {"available": False, "reason": f"unexpected nvidia-smi output: {line}"}
        name, used_mib, total_mib, temp_c, util_pct = parts[:5]
        total_gb = int(re.sub(r"[^0-9]", "", total_mib)) / 1024
        used_gb = int(re.sub(r"[^0-9]", "", used_mib)) / 1024
        return {
            "available": True,
            "name": name,
            "memory_total_gb": round(total_gb, 1),
            "memory_used_gb": round(used_gb, 1),
            "memory_free_gb": round(total_gb - used_gb, 1),
            "temperature_c": int(re.sub(r"[^0-9]", "", temp_c)),
            "utilization_pct": int(re.sub(r"[^0-9]", "", util_pct)),
        }
    except FileNotFoundError:
        return {"available": False, "reason": "nvidia-smi not in PATH"}
    except subprocess.TimeoutExpired:
        return {"available": False, "reason": "nvidia-smi timed out"}
    except Exception as exc:
        return {"available": False, "reason": str(exc)}

