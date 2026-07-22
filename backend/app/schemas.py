from typing import Literal
import uuid
from datetime import datetime
from pydantic import BaseModel, Field


class TransactionIn(BaseModel):
    user_ref: str
    amount: float = Field(gt=0)
    currency: str = "USD"
    country: str
    merchant: str | None = None


class MLBreakdown(BaseModel):
    score: float
    tier: Literal["clean", "challenge", "block"]
    model_version: str | None = None


class TransactionOut(BaseModel):
    id: uuid.UUID
    user_ref: str
    amount: float
    currency: str
    country: str
    merchant: str | None
    status: str
    risk_score: float
    risk_reasons: dict
    created_at: datetime
    scored_at: datetime | None
    ml_score: float
    ml_tier: str
    ml_model_version: str | None
    reviewed_status: str
    reviewed_by: str | None
    reviewed_at: datetime | None

    class Config:
        from_attributes = True


class ReviewIn(BaseModel):
    status: Literal["confirmed_fraud", "false_positive", "unreviewed"]


class AllowlistIn(BaseModel):
    user_ref: str
    hours: int = Field(default=24, ge=1, le=168)


class FraudRuleIn(BaseModel):
    name: str
    description: str | None = None
    rule_type: str
    threshold: float
    window_seconds: int = 120
    weight: float = 1.0
    enabled: bool = True


class FraudRuleOut(FraudRuleIn):
    id: uuid.UUID
    updated_at: datetime
    updated_by: str | None

    class Config:
        from_attributes = True


class LoginIn(BaseModel):
    email: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


class MeOut(BaseModel):
    email: str
    role: str
    organization_name: str
    organization_id: uuid.UUID
