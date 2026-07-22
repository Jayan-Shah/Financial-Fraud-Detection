import os
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Fraud Detection Platform"
    environment: str = os.getenv("ENVIRONMENT", "development")

    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@postgres:5432/fraud_db"
    )
    sync_database_url: str = os.getenv(
        "SYNC_DATABASE_URL", "postgresql://postgres:postgres@postgres:5432/fraud_db"
    )

    redis_url: str = os.getenv("REDIS_URL", "redis://redis:6379/0")
    redis_pubsub_channel: str = "transactions.scored"
    celery_broker_url: str = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/1")
    celery_result_backend: str = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/2")

    jwt_secret: str = os.getenv("JWT_SECRET", "change-me-in-production")
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    # Read as a plain string (not list[str]) - pydantic-settings JSON-decodes
    # any list-typed field straight out of the env/dotenv source, before any
    # validator gets a chance to run, so a plain comma-separated value like
    # "http://localhost,http://localhost:5173" would fail to parse as JSON.
    # `cors_origins` below splits this into the list everything else uses.
    cors_origins_raw: str = Field(default="http://localhost:5173", validation_alias="CORS_ORIGINS")

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins_raw.split(",") if origin.strip()]

    class Config:
        env_file = ".env"


settings = Settings()
