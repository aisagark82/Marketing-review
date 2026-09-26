"""Gemini (Phase 0 step 6): AI review fields on findings, call log, response cache.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

from brandguard.core.db import UTCDateTime

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("findings") as batch:
        batch.add_column(sa.Column("ai_verdict", sa.String(20)))
        batch.add_column(sa.Column("ai_reason", sa.Text()))
        batch.add_column(sa.Column("ai_suggestion", sa.Text()))
        batch.add_column(sa.Column("ai_model", sa.String(80)))
    op.create_table(
        "ai_calls",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stage", sa.String(30), nullable=False),
        sa.Column("model", sa.String(80), nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("runs.id")),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )
    op.create_index("ix_ai_calls_run_id", "ai_calls", ["run_id"])
    op.create_index("ix_ai_calls_created_at", "ai_calls", ["created_at"])
    op.create_table(
        "ai_cache",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("stage", sa.String(30), nullable=False),
        sa.Column("response", sa.JSON(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("ai_cache")
    op.drop_table("ai_calls")
    with op.batch_alter_table("findings") as batch:
        for column in ("ai_model", "ai_suggestion", "ai_reason", "ai_verdict"):
            batch.drop_column(column)
