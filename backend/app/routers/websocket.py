import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from jose import jwt, JWTError

from app.config import settings
from app.logging_config import log
from app.redis_client import async_redis

router = APIRouter()


@router.websocket("/ws/transactions")
async def transactions_ws(websocket: WebSocket, token: str | None = None):
    """
    Each connected client gets its own Redis pub/sub subscription, scoped
    to their organization's channel - so one tenant's dashboard never sees
    another tenant's live transaction stream. The JWT is passed as a query
    param (`?token=...`) since browsers can't attach custom headers to a
    WebSocket upgrade request the way a normal fetch() can.
    """
    if not token:
        await websocket.close(code=4401)
        return
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        org_id = payload.get("org_id")
        if not org_id:
            raise JWTError("missing org_id claim")
    except JWTError:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    channel = f"{settings.redis_pubsub_channel}:{org_id}"
    pubsub = async_redis.pubsub()
    await pubsub.subscribe(channel)
    log.info("ws.connected", org_id=org_id)

    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message and message["type"] == "message":
                await websocket.send_text(message["data"])
            await asyncio.sleep(0.01)
    except WebSocketDisconnect:
        log.info("ws.disconnected", org_id=org_id)
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()
