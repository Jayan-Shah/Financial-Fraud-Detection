"""
Fires synthetic transactions at the FastAPI ingestion endpoint continuously.
Mostly normal, low-risk traffic, but periodically simulates a fraud burst
(one user firing many transactions across several countries in a short
window) so the scoring pipeline and live dashboard have something real to
react to.
"""
import os
import random
import time
import uuid

import requests

TARGET_URL = os.getenv("TARGET_URL", "http://localhost:8000/api/transactions/")
RATE_PER_SECOND = float(os.getenv("RATE_PER_SECOND", "10"))
ORG_API_KEY = os.getenv("ORG_API_KEY")

if not ORG_API_KEY:
    print(
        "[mock-generator] WARNING: ORG_API_KEY is not set - ingestion will "
        "fail with 401. Run `python -m app.seed` in backend/, copy the "
        "printed API key, and set ORG_API_KEY before running this script."
    )

COUNTRIES = ["US", "GB", "DE", "FR", "NG", "IN", "BR", "SG", "AU", "CA"]
MERCHANTS = ["Amazon", "Uber", "Netflix", "Steam", "Shopify Store", "Local Cafe", "Airline Co", "SaaS Tool"]
NORMAL_USERS = [f"user_{i:04d}" for i in range(1, 300)]


def random_transaction(user_ref: str | None = None, country: str | None = None, amount: float | None = None):
    return {
        "user_ref": user_ref or random.choice(NORMAL_USERS),
        "amount": round(amount if amount is not None else random.uniform(5, 400), 2),
        "currency": "USD",
        "country": country or random.choice(COUNTRIES),
        "merchant": random.choice(MERCHANTS),
    }


def send(tx: dict):
    try:
        requests.post(TARGET_URL, json=tx, headers={"X-Org-Api-Key": ORG_API_KEY or ""}, timeout=2)
    except requests.RequestException as exc:
        print(f"[mock-generator] failed to send transaction: {exc}")


def fraud_burst():
    """Simulates the scenario from the brief: one user, many countries, many
    transactions, in a very short window."""
    fraud_user = f"user_fraud_{uuid.uuid4().hex[:6]}"
    print(f"[mock-generator] firing fraud burst for {fraud_user}")
    for _ in range(50):
        send(random_transaction(user_ref=fraud_user, country=random.choice(COUNTRIES), amount=random.uniform(1, 20)))
        time.sleep(0.02)


def main():
    print(f"[mock-generator] streaming to {TARGET_URL} at ~{RATE_PER_SECOND}/s")
    tick = 0
    while True:
        send(random_transaction())
        tick += 1
        if tick % 400 == 0:  # roughly every ~40s at 10/s, trigger a fraud burst
            fraud_burst()
        time.sleep(1 / RATE_PER_SECOND)


if __name__ == "__main__":
    main()
