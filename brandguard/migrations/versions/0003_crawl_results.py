"""Crawl results (Phase 0 step 3): assets and segments; runs.params and runs.stats.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

from brandguard.core.db import UTCDateTime

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.add_column(sa.Column("params", sa.JSON()))
        batch.add_column(sa.Column("stats", sa.JSON()))
    op.create_table(
        "assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("site_id", sa.Integer(), sa.ForeignKey("sites.id"), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("final_url", sa.Text()),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("status_reason", sa.String(200)),
        sa.Column("found_on_id", sa.Integer(), sa.ForeignKey("assets.id")),
        sa.Column("http_status", sa.Integer()),
        sa.Column("title", sa.Text()),
        sa.Column("language", sa.String(35)),
        sa.Column("content_sha256", sa.String(64)),
        sa.Column("html_path", sa.Text()),
        sa.Column("screenshot_path", sa.Text()),
        sa.Column("info", sa.JSON()),
        sa.Column("fetched_at", UTCDateTime()),
        sa.UniqueConstraint("run_id", "url", name="uq_assets_run_url"),
    )
    op.create_index("ix_assets_run_id", "assets", ["run_id"])
    op.create_index("ix_assets_site_id", "assets", ["site_id"])
    op.create_index("ix_assets_status", "assets", ["status"])
    op.create_table(
        "segments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "asset_id", sa.Integer(), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_source", sa.String(40), nullable=False),
        sa.Column("visibility", sa.String(10), nullable=False),
        sa.Column("render_transform", sa.String(20)),
        sa.Column("locator", sa.JSON()),
        sa.Column("extractor", sa.String(40), nullable=False),
    )
    op.create_index("ix_segments_asset_id", "segments", ["asset_id"])
    op.create_index("ix_segments_visibility", "segments", ["visibility"])


def downgrade() -> None:
    op.drop_table("segments")
    op.drop_table("assets")
    with op.batch_alter_table("runs") as batch:
        batch.drop_column("stats")
        batch.drop_column("params")
