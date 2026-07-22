from app.tasks import _rules_score as _score

RULES = [
    {"rule_type": "velocity", "threshold": 10, "weight": 0.4, "enabled": True, "window_seconds": 120},
    {"rule_type": "geo_spread", "threshold": 3, "weight": 0.4, "enabled": True, "window_seconds": 120},
    {"rule_type": "amount_threshold", "threshold": 5000, "weight": 0.2, "enabled": True, "window_seconds": 120},
]


def test_clean_transaction_scores_zero():
    score, reasons = _score(RULES, amount=50, tx_count=1, country_spread=1)
    assert score == 0.0
    assert reasons == {}


def test_high_velocity_and_geo_spread_flags():
    score, reasons = _score(RULES, amount=10, tx_count=50, country_spread=3)
    assert score >= 0.5
    assert "velocity" in reasons
    assert "geo_spread" in reasons


def test_disabled_rule_is_ignored():
    disabled = [{**RULES[0], "enabled": False}]
    score, reasons = _score(disabled, amount=10, tx_count=999, country_spread=1)
    assert score == 0.0
    assert reasons == {}
