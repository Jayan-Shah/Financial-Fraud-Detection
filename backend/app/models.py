import secrets
import uuid
from datetime import datetime

from sqlalchemy import String, Float, Integer, Boolean, DateTime, ForeignKey, JSON, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _generate_api_key() -> str:
    return f"sk_live_{secrets.token_urlsafe(32)}"


class Organization(Base):
    """
    A tenant. Every user, transaction, fraud rule, and allowlist entry
    belongs to exactly one organization - this is the isolation boundary
    for a multi-tenant deployment (e.g. one org per merchant/bank client).
    """
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # Service-to-service credential for the transaction ingestion endpoint -
    # deliberately separate from analyst JWT auth, since the payment
    # gateway sending transactions is a different caller than a human
    # logging into the dashboard.
    api_key: Mapped[str] = mapped_column(String, unique=True, index=True, default=_generate_api_key)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, default="analyst")  # analyst | compliance_admin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    organization: Mapped["Organization"] = relationship()


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), index=True, nullable=False)
    user_ref: Mapped[str] = mapped_column(String, index=True, nullable=False)  # the payer's user id
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String, default="USD")
    country: Mapped[str] = mapped_column(String, nullable=False)
    merchant: Mapped[str] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending | clear | challenged | flagged
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)  # rules-engine score
    risk_reasons: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    scored_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    # ML layer output - independent of the rules score above. See
    # app/ml/inference.py for how this is produced.
    ml_score: Mapped[float] = mapped_column(Float, default=0.0)
    ml_tier: Mapped[str] = mapped_column(String, default="clean")  # clean | challenge | block
    ml_model_version: Mapped[str] = mapped_column(String, nullable=True)
    # The exact feature vector used at scoring time - stored so an on-demand
    # explainability call later reconstructs the SAME inputs that produced
    # ml_score, rather than a drifted approximation from current state.
    ml_features: Mapped[dict] = mapped_column(JSON, nullable=True)

    # Analyst feedback loop - lets a human confirm or dismiss a flagged
    # transaction. This label is what a real system would feed back into
    # retraining/rule-tuning; here it's tracked for audit + reporting.
    reviewed_status: Mapped[str] = mapped_column(String, default="unreviewed")  # unreviewed | confirmed_fraud | false_positive
    reviewed_by: Mapped[str] = mapped_column(String, nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    # Set when the client supplies an Idempotency-Key header on ingestion,
    # so retried requests (e.g. after a network blip) don't get double-scored.
    idempotency_key: Mapped[str] = mapped_column(String, nullable=True, unique=True)


class FraudRule(Base):
    __tablename__ = "fraud_rules"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_fraud_rules_org_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=True)
    rule_type: Mapped[str] = mapped_column(String, nullable=False)  # velocity | geo_spread | amount_threshold
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    window_seconds: Mapped[int] = mapped_column(Integer, default=120)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by: Mapped[str] = mapped_column(String, nullable=True)


class AllowlistEntry(Base):
    """
    A temporary manual override - e.g. customer support clearing a VIP or a
    confirmed false positive for 24h so the decision engine returns ALLOW
    for that user regardless of what the rules/ML would otherwise say.
    Enforced in the Celery worker before rules/ML are even evaluated.
    """
    __tablename__ = "allowlist_entries"
    __table_args__ = (UniqueConstraint("org_id", "user_ref", name="uq_allowlist_org_user"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), index=True, nullable=False)
    user_ref: Mapped[str] = mapped_column(String, nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
