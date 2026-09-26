import sqlite3

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text

from brandguard.core.db import Base, get_engine

# The schema that step 1 created with create_all(), before migrations existed.
STEP1_SCHEMA = """
CREATE TABLE settings (
    key VARCHAR(100) NOT NULL PRIMARY KEY, value JSON NOT NULL, updated_at DATETIME NOT NULL
);
CREATE TABLE runs (
    id INTEGER NOT NULL PRIMARY KEY, kind VARCHAR(50) NOT NULL, status VARCHAR(20) NOT NULL,
    step VARCHAR(100), done INTEGER NOT NULL, total INTEGER NOT NULL, message TEXT, error TEXT,
    cancel_requested BOOLEAN NOT NULL, created_at DATETIME NOT NULL, started_at DATETIME,
    finished_at DATETIME
);
CREATE INDEX ix_runs_status ON runs (status);
INSERT INTO runs (kind, status, done, total, message, cancel_requested, created_at)
VALUES ('selftest', 'completed', 30, 30, 'All checks passed', 0, '2026-09-26 16:00:00');
"""


def test_migrated_schema_matches_models():
    with get_engine().connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diff == []


def test_step1_database_is_upgraded_in_place(brandguard_home):
    brandguard_home.mkdir(parents=True)
    with sqlite3.connect(brandguard_home / "brandguard.db") as legacy:
        legacy.executescript(STEP1_SCHEMA)

    with get_engine().connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0003"
        run = connection.execute(text("SELECT kind, message, site_id FROM runs")).one()
        assert tuple(run) == ("selftest", "All checks passed", None)
        assert connection.scalar(text("SELECT name FROM brands")) == "Pfizer"
