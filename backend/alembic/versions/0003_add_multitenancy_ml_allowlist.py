"""add multi-tenancy, ml columns, allowlist

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-20

"""
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

DEFAULT_ORG_ID = str(uuid.uuid4())


def upgrade():
    # --- organizations ---
    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("api_key", sa.String, nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_organizations_api_key", "organizations", ["api_key"])

    # Backfill: create one default org and attach all existing rows to it,
    # so this migration is safe to run against a database that already has
    # data from before multi-tenancy existed (e.g. local dev databases).
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "INSERT INTO organizations (id, name, api_key, created_at) "
            "VALUES (:id, :name, :api_key, now())"
        ),
        {"id": DEFAULT_ORG_ID, "name": "Default Organization", "api_key": f"sk_live_migrated_{uuid.uuid4().hex}"},
    )

    # --- users.org_id ---
    op.add_column("users", sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True))
    conn.execute(sa.text("UPDATE users SET org_id = :org_id"), {"org_id": DEFAULT_ORG_ID})
    op.alter_column("users", "org_id", nullable=False)
    op.create_foreign_key("fk_users_org_id", "users", "organizations", ["org_id"], ["id"])

    # --- transactions: org_id + ML columns ---
    op.add_column("transactions", sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True))
    conn.execute(sa.text("UPDATE transactions SET org_id = :org_id"), {"org_id": DEFAULT_ORG_ID})
    op.alter_column("transactions", "org_id", nullable=False)
    op.create_foreign_key("fk_transactions_org_id", "transactions", "organizations", ["org_id"], ["id"])
    op.create_index("ix_transactions_org_id", "transactions", ["org_id"])

    op.add_column("transactions", sa.Column("ml_score", sa.Float, nullable=False, server_default="0.0"))
    op.add_column("transactions", sa.Column("ml_tier", sa.String, nullable=False, server_default="clean"))
    op.add_column("transactions", sa.Column("ml_model_version", sa.String, nullable=True))
    op.add_column("transactions", sa.Column("ml_features", postgresql.JSON, nullable=True))

    # --- fraud_rules: org_id, and re-scope the uniqueness of `name` to be per-org ---
    op.add_column("fraud_rules", sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True))
    conn.execute(sa.text("UPDATE fraud_rules SET org_id = :org_id"), {"org_id": DEFAULT_ORG_ID})
    op.alter_column("fraud_rules", "org_id", nullable=False)
    op.create_foreign_key("fk_fraud_rules_org_id", "fraud_rules", "organizations", ["org_id"], ["id"])
    op.create_index("ix_fraud_rules_org_id", "fraud_rules", ["org_id"])
    op.drop_constraint("fraud_rules_name_key", "fraud_rules", type_="unique")
    op.create_unique_constraint("uq_fraud_rules_org_name", "fraud_rules", ["org_id", "name"])

    # --- allowlist_entries ---
    op.create_table(
        "allowlist_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("user_ref", sa.String, nullable=False),
        sa.Column("created_by", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("org_id", "user_ref", name="uq_allowlist_org_user"),
    )
    op.create_index("ix_allowlist_entries_org_id", "allowlist_entries", ["org_id"])


def downgrade():
    op.drop_table("allowlist_entries")

    op.drop_constraint("uq_fraud_rules_org_name", "fraud_rules", type_="unique")
    op.create_unique_constraint("fraud_rules_name_key", "fraud_rules", ["name"])
    op.drop_index("ix_fraud_rules_org_id", table_name="fraud_rules")
    op.drop_constraint("fk_fraud_rules_org_id", "fraud_rules", type_="foreignkey")
    op.drop_column("fraud_rules", "org_id")

    op.drop_column("transactions", "ml_features")
    op.drop_column("transactions", "ml_model_version")
    op.drop_column("transactions", "ml_tier")
    op.drop_column("transactions", "ml_score")
    op.drop_index("ix_transactions_org_id", table_name="transactions")
    op.drop_constraint("fk_transactions_org_id", "transactions", type_="foreignkey")
    op.drop_column("transactions", "org_id")

    op.drop_constraint("fk_users_org_id", "users", type_="foreignkey")
    op.drop_column("users", "org_id")

    op.drop_index("ix_organizations_api_key", table_name="organizations")
    op.drop_table("organizations")
