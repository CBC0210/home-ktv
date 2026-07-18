"""conftest.py — test environment setup."""
import os
import tempfile

import pytest

# ── Test isolation: NEVER touch the production data dir ──────────────────────
# Settings loads backend/.env, whose DATA_DIR points at the live deployment
# (/data/ktv). Without this override, every pytest run wrote its fixture rows
# into the REAL database — "Test Song N" entries polluted the 曲庫 until
# scripts/cleanup_test_data.py scrubbed them. Real env vars beat .env values
# in pydantic-settings, and this runs before any ktv_pipeline import
# constructs the Settings singleton.
_TEST_DATA_DIR = tempfile.mkdtemp(prefix="ktv-test-data-")
os.environ["DATA_DIR"] = _TEST_DATA_DIR
os.environ["LOG_DIR"] = os.path.join(_TEST_DATA_DIR, "logs")

# Ensure CUDA libraries are on the path before any module that imports torch runs.
# This mirrors what config.py does, but needs to happen at pytest collection time
# before the torch import in test_demucs.py is resolved.
base = "/home/cbc/.local/lib/python3.12/site-packages"
extra = ":".join([
    f"{base}/nvidia/cudnn/lib",
    f"{base}/nvidia/cusparselt/lib",
    f"{base}/nvidia/nccl/lib",
])
existing = os.environ.get("LD_LIBRARY_PATH", "")
os.environ["LD_LIBRARY_PATH"] = f"{extra}:{existing}" if existing else extra


@pytest.fixture(scope="session", autouse=True)
def _init_isolated_db():
    """Create the schema in the throwaway test DB.

    Historically tests piggybacked on the production DB where tables already
    existed; with the isolated DATA_DIR the schema must be created explicitly
    for tests that don't call init_db() themselves.
    """
    from ktv_pipeline.database import init_db
    init_db()
