"""add review tracking and idempotency key

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-19

"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "transactions",
        sa.Column("reviewed_status", sa.String, nullable=False, server_default="unreviewed"),
    )
    op.add_column("transactions", sa.Column("reviewed_by", sa.String, nullable=True))
    op.add_column("transactions", sa.Column("reviewed_at", sa.DateTime, nullable=True))
    op.add_column("transactions", sa.Column("idempotency_key", sa.String, nullable=True))
    op.create_index(
        "ix_transactions_idempotency_key", "transactions", ["idempotency_key"], unique=True
    )


def downgrade():
    op.drop_index("ix_transactions_idempotency_key", table_name="transactions")
    op.drop_column("transactions", "idempotency_key")
    op.drop_column("transactions", "reviewed_at")
    op.drop_column("transactions", "reviewed_by")
    op.drop_column("transactions", "reviewed_status")
