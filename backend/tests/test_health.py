import pytest


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_ingest_requires_valid_payload(client):
    resp = await client.post("/api/transactions/", json={"user_ref": "u1", "amount": -5, "country": "US"})
    assert resp.status_code == 422  # amount must be > 0


@pytest.mark.asyncio
async def test_transactions_list_requires_auth(client):
    resp = await client.get("/api/transactions/")
    assert resp.status_code == 401
