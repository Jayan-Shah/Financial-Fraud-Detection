from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.logging_config import configure_logging, log
from app.routers import auth, rules, transactions, websocket

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("app.startup", environment=settings.environment)
    yield
    log.info("app.shutdown")


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(transactions.router)
app.include_router(rules.router)
app.include_router(websocket.router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "environment": settings.environment}
