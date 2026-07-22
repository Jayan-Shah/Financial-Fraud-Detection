import pytest

from app.schemas import ReviewIn


def test_review_status_accepts_valid_values():
    for value in ("confirmed_fraud", "false_positive", "unreviewed"):
        assert ReviewIn(status=value).status == value


def test_review_status_rejects_invalid_value():
    with pytest.raises(Exception):
        ReviewIn(status="not_a_real_status")


@pytest.mark.asyncio
async def test_ingest_requires_org_api_key(client):
    # No X-Org-Api-Key header at all - FastAPI rejects before the handler runs.
    resp = await client.post(
        "/api/transactions/",
        json={"user_ref": "u1", "amount": 10, "country": "US"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_ingest_rejects_invalid_org_api_key(client):
    resp = await client.post(
        "/api/transactions/",
        json={"user_ref": "u1", "amount": 10, "country": "US"},
        headers={"X-Org-Api-Key": "sk_live_this_key_does_not_exist"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_simulate_burst_requires_auth(client):
    resp = await client.post("/api/transactions/simulate-burst")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_allowlist_requires_auth(client):
    resp = await client.post("/api/transactions/allowlist", json={"user_ref": "u1", "hours": 24})
    assert resp.status_code == 401
