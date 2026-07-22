"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-07-16

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String, nullable=False, unique=True),
        sa.Column("hashed_password", sa.String, nullable=False),
        sa.Column("role", sa.String, nullable=False, server_default="analyst"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "fraud_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String, nullable=False, unique=True),
        sa.Column("description", sa.String, nullable=True),
        sa.Column("rule_type", sa.String, nullable=False),
        sa.Column("threshold", sa.Float, nullable=False),
        sa.Column("window_seconds", sa.Integer, nullable=False, server_default="120"),
        sa.Column("weight", sa.Float, nullable=False, server_default="1.0"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.Column("updated_by", sa.String, nullable=True),
    )

    op.create_table(
        "transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_ref", sa.String, nullable=False),
        sa.Column("amount", sa.Float, nullable=False),
        sa.Column("currency", sa.String, nullable=False, server_default="USD"),
        sa.Column("country", sa.String, nullable=False),
        sa.Column("merchant", sa.String, nullable=True),
        sa.Column("status", sa.String, nullable=False, server_default="pending"),
        sa.Column("risk_score", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("risk_reasons", postgresql.JSON, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("scored_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_transactions_user_ref", "transactions", ["user_ref"])
    op.create_index("ix_transactions_created_at", "transactions", ["created_at"])


def downgrade():
    op.drop_table("transactions")
    op.drop_table("fraud_rules")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
