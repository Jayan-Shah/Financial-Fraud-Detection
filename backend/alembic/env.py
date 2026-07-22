import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool
from alembic import context

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.database import Base
from app import models  # noqa: F401 - ensures models are registered on Base.metadata

config = context.config

# --- NEW RENDER-SAFE URL LOGIC ---
db_url = os.getenv("DATABASE_URL")

if db_url:
    # If on Render, grab the environment variable and strip the async driver
    db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
else:
    # If local, fall back to your Pydantic settings
    db_url = settings.sync_database_url

config.set_main_option("sqlalchemy.url", db_url)
# ---------------------------------

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()