from logging.config import fileConfig
import sys
from pathlib import Path

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# ── ensure ktv_pipeline is importable ──────────────────────────────────────────
_backend_src = Path(__file__).parents[1] / "src"
if str(_backend_src) not in sys.path:
    sys.path.insert(0, str(_backend_src))

# ── load settings (configures LD_LIBRARY_PATH etc.) ───────────────────────────
from ktv_pipeline.config import settings
from ktv_pipeline.database import Base

# Import ALL models so they register with Base.metadata.
# The models module imports Base from database.py and attaches __table__ to each.
from ktv_pipeline import models as _models  # noqa: F401

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# provide models metadata for autogenerate
target_metadata = Base.metadata

# Override sqlalchemy.url from settings (ignore the placeholder in alembic.ini)
config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{settings.db_path}")


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()