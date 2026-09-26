"""Brands and sites with pre-flight check results (Phase 0 step 2); runs.site_id.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

from brandguard.core.db import UTCDateTime

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "brands",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )
    op.create_table(
        "sites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("brand_id", sa.Integer(), sa.ForeignKey("brands.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("start_urls", sa.JSON(), nullable=False),
        sa.Column("allowed_domains", sa.JSON(), nullable=False),
        sa.Column("use_sitemap", sa.Boolean(), nullable=False),
        sa.Column("include_patterns", sa.JSON(), nullable=False),
        sa.Column("exclude_patterns", sa.JSON(), nullable=False),
        sa.Column("max_pages", sa.Integer(), nullable=False),
        sa.Column("render_js", sa.String(10), nullable=False),
        sa.Column("expand_interactive", sa.Boolean(), nullable=False),
        sa.Column("independent", sa.Boolean(), nullable=False),
        sa.Column("request_interval_s", sa.Float(), nullable=False),
        sa.Column("respect_robots", sa.Boolean(), nullable=False),
        sa.Column("stop_on_blocks", sa.Boolean(), nullable=False),
        sa.Column("preflight_result", sa.JSON()),
        sa.Column("preflight_at", UTCDateTime()),
        sa.Column("preflight_fingerprint", sa.String(64)),
        sa.Column("preflight_acknowledged_at", UTCDateTime()),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
    )
    with op.batch_alter_table("runs") as batch:
        batch.add_column(sa.Column("site_id", sa.Integer()))
        batch.create_foreign_key("fk_runs_site_id_sites", "sites", ["site_id"], ["id"])
        batch.create_index("ix_runs_site_id", ["site_id"])


def downgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.drop_index("ix_runs_site_id")
        batch.drop_constraint("fk_runs_site_id_sites", type_="foreignkey")
        batch.drop_column("site_id")
    op.drop_table("sites")
    op.drop_table("brands")
