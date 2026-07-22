"""
Sanity + latency checks for the trained model. Run this after every
retrain, before trusting the artifact - it would have caught the earlier
"label = amount > 300" bug immediately (see the "expensive but legitimate"
case below, which a correctly-trained model must score LOW).
"""
import math
import time
from datetime import datetime, timezone

from inference import MLScorer

N_LATENCY_RUNS = 200


def make_features(**overrides) -> dict:
    now = datetime.now(timezone.utc)
    base = {
        "amount_log": math.log1p(50.0),
        "amount_z_score": 0.0,
        "velocity_120s": 1,
        "geo_countries_120s": 1,
        "geo_country_rarity": 0.02,
        "time_hour_sin": math.sin(2 * math.pi * now.hour / 24),
        "time_hour_cos": math.cos(2 * math.pi * now.hour / 24),
        "time_dow": now.weekday(),
        "time_since_last_tx": 3600.0,
    }
    base.update(overrides)
    return base


def run():
    print("Loading model...")
    scorer = MLScorer("fraud_model_artifact.joblib")
    if not scorer.is_ready:
        print(f"FAILED TO LOAD MODEL: {scorer._load_error}")
        return
    print(f"Model version: {scorer._version}\n")

    print("=== Sanity checks ===")

    # A normal, expensive-but-legitimate purchase. A model trained on a
    # naive "amount > 300" label would score this HIGH and fail this check -
    # this is exactly the regression test that would have caught that bug.
    expensive_but_normal = make_features(
        amount_log=math.log1p(450.0), amount_z_score=1.1, velocity_120s=1, geo_countries_120s=1,
    )
    result = scorer.score(expensive_but_normal)
    status = "PASS" if result.tier == "clean" else "FAIL"
    print(f"[{status}] Expensive but legitimate single purchase -> {result.tier} (p={result.probability})")

    # A clear card-testing burst: high velocity, low per-tx amount.
    burst = make_features(
        amount_log=math.log1p(8.0), amount_z_score=-0.2, velocity_120s=16, geo_countries_120s=1,
        time_since_last_tx=4.0,
    )
    result = scorer.score(burst)
    status = "PASS" if result.tier in ("challenge", "block") else "FAIL"
    print(f"[{status}] Velocity burst pattern -> {result.tier} (p={result.probability})")

    # A geo-takeover pattern: multiple distinct countries, high rarity.
    geo = make_features(
        amount_log=math.log1p(60.0), amount_z_score=0.3, velocity_120s=6, geo_countries_120s=5,
        geo_country_rarity=0.95, time_since_last_tx=15.0,
    )
    result = scorer.score(geo)
    status = "PASS" if result.tier in ("challenge", "block") else "FAIL"
    print(f"[{status}] Geo-takeover pattern -> {result.tier} (p={result.probability})")

    # An amount spike relative to the user's OWN baseline (huge z-score),
    # even though the raw amount alone says nothing.
    spike = make_features(amount_log=math.log1p(3000.0), amount_z_score=22.0, velocity_120s=1, geo_countries_120s=1)
    result = scorer.score(spike)
    status = "PASS" if result.tier in ("challenge", "block") else "FAIL"
    print(f"[{status}] Amount spike vs. personal baseline -> {result.tier} (p={result.probability})")

    print("\n=== Latency benchmark ===")
    sample = make_features()
    # First call after warm-up is already representative since MLScorer
    # warms the model up at construction time - but we still average many
    # calls rather than trusting a single measurement.
    durations = []
    for _ in range(N_LATENCY_RUNS):
        t0 = time.perf_counter()
        scorer.score(sample)
        durations.append((time.perf_counter() - t0) * 1000)

    durations.sort()
    p50 = durations[len(durations) // 2]
    p95 = durations[int(len(durations) * 0.95)]
    avg = sum(durations) / len(durations)
    print(f"  avg={avg:.3f}ms  p50={p50:.3f}ms  p95={p95:.3f}ms  (n={N_LATENCY_RUNS})")
    budget_status = "WITHIN BUDGET" if p95 < 20.0 else "EXCEEDS 20ms BUDGET"
    print(f"  {budget_status} (target: p95 < 20ms)")

    print("\n=== Explainability (on-demand call, not hot path) ===")
    top_features = scorer.explain(burst)
    print(f"  Top contributing features for the velocity burst case: {top_features}")


if __name__ == "__main__":
    run()
