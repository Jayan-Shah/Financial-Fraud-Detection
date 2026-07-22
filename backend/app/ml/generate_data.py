"""
Generates a synthetic transaction dataset with REAL fraud patterns injected
(velocity bursts, geo-takeover sequences, amount spikes relative to each
user's own baseline) - not a naive "amount > threshold" label, which would
just make the model redundant with the existing rules engine.

Critically, features are computed via a single chronological replay that
mirrors the EXACT fetch-before-update order used in the live Celery worker
(app/tasks.py): for each transaction, we read the user's current rolling
state, compute features from it, THEN update the state. This guarantees
zero train/serve skew by construction - we are not approximating the live
system's behavior with pandas .rolling() windows (which are inclusive of
the current row and would require fragile off-by-one corrections); we are
literally replaying the same algorithm offline.
"""
import math
import random
from collections import deque

import numpy as np
import pandas as pd

WINDOW_SECONDS = 120
DEFAULT_LAST_TX_GAP = 86400 * 30  # matches the "no prior tx" fallback in tasks.py

HOME_COUNTRIES = ["US", "GB", "DE", "IN", "BR", "AU", "CA", "FR", "SG", "MX"]
ALL_COUNTRIES = HOME_COUNTRIES + ["NG", "JP", "ZA", "RU", "AE", "VN", "PH"]


def _new_user_profile(rng: random.Random, user_id: str) -> dict:
    home = rng.choice(HOME_COUNTRIES)
    # A minority of users occasionally transact from one consistent second
    # country (frequent travelers / expats) - this is legitimate behavior,
    # not fraud, and exists specifically so the model has to learn that
    # "a second country" alone isn't suspicious; only DISTINCT unexpected
    # countries or a distinct-country BURST is.
    travel_country = rng.choice([c for c in HOME_COUNTRIES if c != home]) if rng.random() < 0.25 else None
    personal_mean = float(np.random.lognormal(mean=3.4, sigma=0.6))  # ~$30-$150 typical baseline, varies per user
    return {
        "user_id": user_id,
        "home_country": home,
        "travel_country": travel_country,
        "personal_mean": personal_mean,
    }


def _generate_normal_timeline(rng: random.Random, profile: dict, start_ts: float, days: int) -> list[dict]:
    events = []
    t = start_ts + rng.uniform(0, 3600 * 6)
    end_ts = start_ts + days * 86400
    while t < end_ts:
        country = profile["home_country"]
        if profile["travel_country"] and rng.random() < 0.05:
            country = profile["travel_country"]
        amount = float(np.random.lognormal(mean=math.log(max(profile["personal_mean"], 1.0)), sigma=0.5))
        events.append({
            "user_ref": profile["user_id"],
            "timestamp": t,
            "amount": round(max(amount, 1.0), 2),
            "country": country,
            "is_fraud": 0,
            "fraud_type": None,
        })
        # Mostly hours-to-a-day between transactions, but a meaningfully
        # larger and WIDER share of quick-succession gaps than a first pass
        # here - real people do sometimes buy several things in quick
        # succession (multi-item checkouts split into separate charges, a
        # fast browsing session). This range is deliberately made to
        # OVERLAP with injected fraud gap ranges below - if legitimate
        # traffic never has short gaps, "gap is short" becomes a perfect
        # single-feature shortcut and the model never has to learn from
        # velocity/geo/amount signals at all, which defeats the point of
        # a multi-feature model.
        if rng.random() < 0.12:
            gap = rng.uniform(4, 300)
        else:
            gap = rng.expovariate(1 / (3600 * 14))
        t += gap
    return events


def _inject_velocity_burst(rng: random.Random, profile: dict, at_ts: float) -> list[dict]:
    n = rng.randint(12, 20)
    events = []
    t = at_ts
    for _ in range(n):
        events.append({
            "user_ref": profile["user_id"],
            "timestamp": t,
            "amount": round(rng.uniform(1, 20), 2),  # card-testing: small amounts to probe a stolen card
            "country": profile["home_country"],
            "is_fraud": 1,
            "fraud_type": "velocity_burst",
        })
        # Real jitter, not perfectly even spacing - evenly-spaced gaps are
        # themselves an unrealistic giveaway a model could latch onto
        # instead of learning the actual velocity/count signal.
        t += rng.uniform(2, 18)
    return events


def _inject_geo_takeover(rng: random.Random, profile: dict, at_ts: float) -> list[dict]:
    n = rng.randint(6, 10)
    foreign_pool = [c for c in ALL_COUNTRIES if c not in (profile["home_country"], profile["travel_country"])]
    events = []
    t = at_ts
    for _ in range(n):
        events.append({
            "user_ref": profile["user_id"],
            "timestamp": t,
            "amount": round(rng.uniform(20, 200), 2),
            "country": rng.choice(foreign_pool),
            "is_fraud": 1,
            "fraud_type": "geo_takeover",
        })
        t += rng.uniform(8, 25)
    return events


def _inject_amount_spike(rng: random.Random, profile: dict, at_ts: float) -> list[dict]:
    # Deliberately relative to THIS user's own baseline, not an absolute
    # dollar threshold - a high-spending user's normal $2,000 purchase must
    # NOT trigger this; only a purchase far outside their OWN history should.
    n = rng.randint(1, 2)
    events = []
    t = at_ts
    for _ in range(n):
        amount = profile["personal_mean"] * rng.uniform(15, 40)
        events.append({
            "user_ref": profile["user_id"],
            "timestamp": t,
            "amount": round(amount, 2),
            "country": profile["home_country"],
            "is_fraud": 1,
            "fraud_type": "amount_spike",
        })
        t += rng.uniform(60, 300)
    return events


def generate_raw_events(n_users: int = 1200, fraud_episode_rate: float = 0.12, days: int = 45, seed: int = 42) -> pd.DataFrame:
    rng = random.Random(seed)
    np.random.seed(seed)
    start_ts = pd.Timestamp("2026-05-01").timestamp()

    all_events = []
    for i in range(n_users):
        profile = _new_user_profile(rng, f"user_{i:04d}")
        events = _generate_normal_timeline(rng, profile, start_ts, days)

        if events and rng.random() < fraud_episode_rate:
            episode_type = rng.choice(["velocity_burst", "geo_takeover", "amount_spike"])
            inject_at = rng.choice(events)["timestamp"] + rng.uniform(60, 3600)
            if episode_type == "velocity_burst":
                events += _inject_velocity_burst(rng, profile, inject_at)
            elif episode_type == "geo_takeover":
                events += _inject_geo_takeover(rng, profile, inject_at)
            else:
                events += _inject_amount_spike(rng, profile, inject_at)

        all_events.extend(events)

    df = pd.DataFrame(all_events).sort_values("timestamp").reset_index(drop=True)
    return df


class _UserState:
    """Mirrors exactly what's stored in Redis per user in app/tasks.py."""

    __slots__ = ("tx_times", "geo_times", "total_tx", "sum_amt", "sum_sq_amt", "last_tx", "country_counts")

    def __init__(self):
        self.tx_times: deque = deque()
        self.geo_times: deque = deque()  # (timestamp, country)
        self.total_tx = 0
        self.sum_amt = 0.0
        self.sum_sq_amt = 0.0
        self.last_tx = None
        self.country_counts: dict[str, int] = {}


def compute_features_streaming(df: pd.DataFrame) -> pd.DataFrame:
    """
    Single chronological replay computing features with fetch-BEFORE-update
    semantics, identical to the live Celery worker. df must already be
    sorted by timestamp ascending (generate_raw_events does this).
    """
    states: dict[str, _UserState] = {}
    rows = []

    for row in df.itertuples(index=False):
        user = row.user_ref
        now = row.timestamp
        amount = row.amount
        country = row.country

        state = states.setdefault(user, _UserState())

        # --- FETCH (mirrors the Redis pipeline reads in tasks.py) ---
        while state.tx_times and state.tx_times[0] < now - WINDOW_SECONDS:
            state.tx_times.popleft()
        velocity_120s = len(state.tx_times)

        while state.geo_times and state.geo_times[0][0] < now - WINDOW_SECONDS:
            state.geo_times.popleft()
        geo_countries_120s = len({c for _, c in state.geo_times})

        if state.total_tx > 0:
            user_mean = state.sum_amt / state.total_tx
            variance = (state.sum_sq_amt / state.total_tx) - (user_mean ** 2)
            user_std = math.sqrt(variance) if variance > 0 else 1.0
        else:
            user_mean, user_std = 0.0, 1.0
        amount_z_score = (amount - user_mean) / (user_std if user_std > 0 else 1.0)

        country_past_count = state.country_counts.get(country, 0)
        geo_country_rarity = (
            (state.total_tx - country_past_count) / state.total_tx if state.total_tx > 0 else 0.0
        )

        last_tx = state.last_tx if state.last_tx is not None else now - DEFAULT_LAST_TX_GAP
        time_since_last_tx = now - last_tx

        dt = pd.Timestamp(now, unit="s")

        rows.append({
            "user_ref": user,
            "timestamp": now,
            "amount": amount,
            "country": country,
            "is_fraud": row.is_fraud,
            "fraud_type": row.fraud_type,
            "amount_log": math.log1p(amount),
            "amount_z_score": amount_z_score,
            "velocity_120s": velocity_120s,
            "geo_countries_120s": geo_countries_120s,
            "geo_country_rarity": geo_country_rarity,
            "time_hour_sin": math.sin(2 * math.pi * dt.hour / 24),
            "time_hour_cos": math.cos(2 * math.pi * dt.hour / 24),
            "time_dow": dt.dayofweek,
            "time_since_last_tx": time_since_last_tx,
        })

        # --- UPDATE (mirrors the post-scoring Redis writes in tasks.py) ---
        state.tx_times.append(now)
        state.geo_times.append((now, country))
        state.total_tx += 1
        state.sum_amt += amount
        state.sum_sq_amt += amount * amount
        state.last_tx = now
        state.country_counts[country] = state.country_counts.get(country, 0) + 1

    return pd.DataFrame(rows)


FEATURE_COLUMNS = [
    "amount_log", "amount_z_score", "velocity_120s", "geo_countries_120s",
    "geo_country_rarity", "time_hour_sin", "time_hour_cos", "time_dow", "time_since_last_tx",
]


def generate_dataset(n_users: int = 3000, fraud_episode_rate: float = 0.12, seed: int = 42) -> pd.DataFrame:
    raw = generate_raw_events(n_users=n_users, fraud_episode_rate=fraud_episode_rate, seed=seed)
    return compute_features_streaming(raw)


if __name__ == "__main__":
    df = generate_dataset()
    print(f"Generated {len(df)} transactions, {df['is_fraud'].sum()} fraudulent ({df['is_fraud'].mean()*100:.2f}%)")
    print(df["fraud_type"].value_counts(dropna=True))
