"""Alembic environment. Migrations run in-process at start-up (see core/migrate.py)."""

from alembic import context

from brandguard.core import models  # noqa: F401  (registers tables on Base.metadata)
from brandguard.core.db import Base

connection = context.config.attributes["connection"]
# render_as_batch: SQLite can't ALTER most things in place, so Alembic copies the table.
context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)

with context.begin_transaction():
    context.run_migrations()
