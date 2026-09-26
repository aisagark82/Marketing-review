"""Bring the SQLite database up to the latest schema at start-up."""

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Connection, Engine, inspect

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
# Databases created by step 1 (before migrations existed) have this schema.
PRE_ALEMBIC_REVISION = "0001"

log = logging.getLogger(__name__)


def _config(connection: Connection) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.attributes["connection"] = connection
    return config


def _revision(connection: Connection) -> str | None:
    return MigrationContext.configure(connection).get_current_revision()


def upgrade_database(engine: Engine) -> None:
    with engine.begin() as connection:
        config = _config(connection)
        tables = set(inspect(connection).get_table_names())
        if "alembic_version" not in tables and "runs" in tables:
            command.stamp(config, PRE_ALEMBIC_REVISION)
        before = _revision(connection)
        command.upgrade(config, "head")
        after = _revision(connection)
    if before != after:
        log.info("Database schema upgraded: %s -> %s", before or "empty", after)
