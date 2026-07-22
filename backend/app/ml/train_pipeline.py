"""
Trains the fraud risk-scoring model on the corrected synthetic dataset
(see generate_data.py for why the label is behavioral, not amount>threshold).

Key methodology decisions, and why:
- Temporal split (not random/shuffled): fraud patterns evolve over time in
  any real system; training on a random split leaks future information into
  training and silently inflates every metric. We sort by timestamp and cut
  chronologically instead.
- Class weighting via scale_pos_weight (not SMOTE): SMOTE distorts the
  posterior distribution in a way that makes calibration harder to trust,
  and doesn't handle the mixed continuous/count features here as cleanly
  as class weighting does.
- Isotonic calibration on a held-out validation set: a GBDT trained with
  scale_pos_weight pushes raw scores toward the extremes, so "0.8" out of
  the raw model does NOT mean "80% likely fraud" until it's calibrated.
- Thresholds are DERIVED FROM THE ACTUAL VALIDATION SCORE DISTRIBUTION,
  not assumed from an abstract cost formula in isolation. We compute the
  target precision from the assumed cost ratio, then walk the validation
  set's real precision-recall curve to find the score that actually
  achieves it - this is what "0.048" or any other number is required to be
  validated against before being trusted.
"""
import json
from datetime import datetime, timezone

import joblib
import lightgbm as lgb
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import average_precision_score, precision_recall_curve

from generate_data import FEATURE_COLUMNS, generate_dataset

# Cost assumption, stated explicitly rather than left implicit (see
# docs/ML_DESIGN.md for the reasoning): a missed fraud costs ~$500 on
# average; a false positive (challenging or blocking a legitimate
# customer) costs ~$25 in support/churn. This ratio drives where we set
# the CHALLENGE threshold - NOT an arbitrary guess.
COST_FALSE_NEGATIVE = 500.0
COST_FALSE_POSITIVE = 25.0
TARGET_PRECISION_CHALLENGE = COST_FALSE_POSITIVE / (COST_FALSE_POSITIVE + COST_FALSE_NEGATIVE)

# BLOCK is deliberately a stricter, higher-confidence bar than CHALLENGE -
# an outright decline should require far more certainty than a step-up
# auth prompt does. "At least even odds" is the plain-language framing.
TARGET_PRECISION_BLOCK = 0.50

# A floor below which CHALLENGE must never trigger, regardless of what the
# raw target-precision math says. When the base fraud rate is very low (as
# it should be in a healthy system), the cost-derived target precision can
# be so close to the base rate that the validation curve clears it at a
# near-zero probability - which would mean "challenge literally any
# transaction with a non-zero score," including obviously clean ones. This
# floor is a practical safety net on top of the theoretically-derived value.
MIN_CHALLENGE_PROBABILITY = 0.01

# Same reasoning as above, applied to BLOCK: a derived threshold that's too
# close to CHALLENGE means real (non-fraud) traffic with a mildly elevated
# score gets outright blocked far more often than intended, instead of
# landing in the CHALLENGE tier where it belongs. This floor keeps a real
# gap between "step-up auth" and "hard block" regardless of what the raw
# precision-curve math derives.
MIN_BLOCK_PROBABILITY = 0.05

ARTIFACT_PATH = "fraud_model_artifact.joblib"


def find_threshold_for_precision(y_true, y_scores, target_precision: float, fallback: float) -> float:
    """Walks the real precision-recall curve on validation data to find the
    lowest-scoring threshold that achieves at least target_precision. Falls
    back to a sane default if the curve never reaches it (can happen with a
    small/noisy validation fold) - and says so, rather than silently
    returning something misleading."""
    precisions, _, thresholds = precision_recall_curve(y_true, y_scores)
    # precision_recall_curve returns len(thresholds) == len(precisions) - 1
    for precision, threshold in zip(precisions[:-1], thresholds):
        if precision >= target_precision:
            return float(threshold)
    print(
        f"  WARNING: validation curve never reached precision {target_precision:.4f} - "
        f"falling back to default threshold {fallback}. Retrain with more fraud examples "
        f"or revisit the cost assumption before trusting this in production."
    )
    return fallback


def _get_fitted_booster(calibrated):
    """CalibratedClassifierCV's internal attribute holding the fitted base
    estimator was renamed from `base_estimator` to `estimator` in a recent
    scikit-learn version. Handle both so this doesn't silently break on a
    slightly different installed version."""
    inner = getattr(calibrated, "estimator", None) or getattr(calibrated, "base_estimator", None)
    if inner is None:
        raise AttributeError(
            "Could not find the fitted base estimator on this CalibratedClassifierCV "
            "fold - check your scikit-learn version's internal attribute name."
        )
    return inner.booster_


def get_averaged_feature_importance(calibrated_clf: CalibratedClassifierCV, feature_names: list[str]) -> dict:
    """CalibratedClassifierCV fits one model per CV fold internally; we
    average their native LightGBM feature importances for a stable overall
    ranking, used for the explainability surface in the UI."""
    importances = np.zeros(len(feature_names))
    for calibrated in calibrated_clf.calibrated_classifiers_:
        booster = _get_fitted_booster(calibrated)
        importances += booster.feature_importance(importance_type="gain")
    importances /= len(calibrated_clf.calibrated_classifiers_)
    ranked = sorted(zip(feature_names, importances), key=lambda x: -x[1])
    total = sum(v for _, v in ranked) or 1.0
    return {name: round(float(value) / total, 4) for name, value in ranked}


def main():
    print("Generating synthetic dataset with injected behavioral fraud patterns...")
    df = generate_dataset(n_users=3000, fraud_episode_rate=0.12, seed=42)
    fraud_rate = df["is_fraud"].mean()
    print(f"  {len(df)} transactions, {df['is_fraud'].sum()} fraud ({fraud_rate*100:.2f}%)")
    if df["is_fraud"].sum() < 50:
        print("  WARNING: very few fraud examples - consider increasing n_users or fraud_episode_rate.")

    # Already sorted by timestamp from generate_dataset(); split chronologically.
    n = len(df)
    train_end = int(n * 0.70)
    val_end = int(n * 0.85)

    # Critical diagnostic: with a temporal split and a naturally rare event,
    # it's entirely possible for one fraud TYPE to be nearly absent from
    # training even though the overall fraud count looks fine in aggregate.
    # Silently training on that would produce exactly the failure mode we
    # hit before (a model that can't detect geo-takeover or amount-spike
    # patterns because it barely saw any) - so check this explicitly rather
    # than discovering it later via failing sanity checks.
    print("\nFraud type counts per chronological split (catches type-imbalance a split can hide):")
    split_labels = (["train"] * train_end) + (["val"] * (val_end - train_end)) + (["test"] * (n - val_end))
    df["_split"] = split_labels
    counts = df[df["is_fraud"] == 1].groupby(["_split", "fraud_type"]).size().unstack(fill_value=0)
    print(counts.reindex(["train", "val", "test"]))
    min_per_type_train = counts.loc["train"].min() if "train" in counts.index else 0
    if min_per_type_train < 30:
        print(
            f"  WARNING: training set has as few as {min_per_type_train} examples of some fraud "
            f"type - that's too few to learn a stable pattern from. Increase fraud_episode_rate "
            f"or n_users before trusting this run."
        )
    df = df.drop(columns=["_split"])

    X = df[FEATURE_COLUMNS]
    y = df["is_fraud"]

    X_train, y_train = X.iloc[:train_end], y.iloc[:train_end]
    X_val, y_val = X.iloc[train_end:val_end], y.iloc[train_end:val_end]
    X_test, y_test = X.iloc[val_end:], y.iloc[val_end:]

    print(f"Split: train={len(X_train)} val={len(X_val)} test={len(X_test)} (chronological, no shuffling)")

    n_pos = y_train.sum()
    scale_pos_weight = (len(y_train) - n_pos) / n_pos if n_pos > 0 else 1.0
    print(f"scale_pos_weight = {scale_pos_weight:.2f} (train fraud rate: {y_train.mean()*100:.3f}%)")

    lgb_clf = lgb.LGBMClassifier(
        n_estimators=150,
        learning_rate=0.05,
        num_leaves=31,
        scale_pos_weight=scale_pos_weight,
        random_state=42,
        verbose=-1,
    )

    print("Training + isotonic calibration (cv=3)...")
    calibrated_clf = CalibratedClassifierCV(estimator=lgb_clf, method="isotonic", cv=3)
    calibrated_clf.fit(X_train, y_train)

    val_scores = calibrated_clf.predict_proba(X_val)[:, 1]
    test_scores = calibrated_clf.predict_proba(X_test)[:, 1]

    val_pr_auc = average_precision_score(y_val, val_scores)
    test_pr_auc = average_precision_score(y_test, test_scores)
    print(f"Validation PR-AUC: {val_pr_auc:.4f}")
    print(f"Test PR-AUC (strictly out-of-time): {test_pr_auc:.4f}")

    print(f"\nDeriving thresholds from the validation set's actual precision-recall curve...")
    print(f"  Target precision for CHALLENGE (cost ratio {COST_FALSE_NEGATIVE:.0f}:{COST_FALSE_POSITIVE:.0f}): {TARGET_PRECISION_CHALLENGE:.4f}")
    challenge_threshold = find_threshold_for_precision(y_val, val_scores, TARGET_PRECISION_CHALLENGE, fallback=0.05)
    if challenge_threshold < MIN_CHALLENGE_PROBABILITY:
        print(
            f"  Derived threshold ({challenge_threshold:.5f}) is below the practical floor "
            f"({MIN_CHALLENGE_PROBABILITY}) - the target precision is too close to the base "
            f"fraud rate to translate into a meaningful probability cutoff on its own. Using "
            f"the floor instead."
        )
        challenge_threshold = MIN_CHALLENGE_PROBABILITY
    print(f"  -> CHALLENGE threshold: {challenge_threshold:.4f}")

    print(f"  Target precision for BLOCK: {TARGET_PRECISION_BLOCK:.4f}")
    block_threshold = find_threshold_for_precision(y_val, val_scores, TARGET_PRECISION_BLOCK, fallback=0.30)
    if block_threshold < MIN_BLOCK_PROBABILITY:
        print(
            f"  Derived threshold ({block_threshold:.5f}) is below the practical floor "
            f"({MIN_BLOCK_PROBABILITY}) - using the floor instead, to avoid outright "
            f"blocking real traffic that's only mildly elevated."
        )
        block_threshold = MIN_BLOCK_PROBABILITY
    print(f"  -> BLOCK threshold: {block_threshold:.4f}")

    if block_threshold <= challenge_threshold:
        block_threshold = min(challenge_threshold * 3, 0.9)
        print(f"  NOTE: derived BLOCK threshold wasn't meaningfully stricter than CHALLENGE - "
              f"adjusted to {block_threshold:.4f}. Revisit with more fraud examples.")

    importances = get_averaged_feature_importance(calibrated_clf, FEATURE_COLUMNS)
    print("\nFeature importance (gain, normalized, averaged across CV folds):")
    for name, value in importances.items():
        print(f"  {name:<22} {value:.4f}")

    version = f"v1.0.0_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    artifact = {
        "model": calibrated_clf,
        "features": FEATURE_COLUMNS,
        "version": version,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "thresholds": {
            "challenge": round(challenge_threshold, 4),
            "block": round(block_threshold, 4),
        },
        "metrics": {
            "val_pr_auc": round(float(val_pr_auc), 4),
            "test_pr_auc": round(float(test_pr_auc), 4),
            "train_fraud_rate": round(float(y_train.mean()), 5),
            "n_train": len(X_train),
            "n_val": len(X_val),
            "n_test": len(X_test),
        },
        "feature_importance": importances,
        "cost_assumption": {
            "false_negative_cost": COST_FALSE_NEGATIVE,
            "false_positive_cost": COST_FALSE_POSITIVE,
        },
        "label_design_notes": (
            "Fraud label is behavioral (velocity burst / geo-takeover / "
            "amount spike relative to the user's OWN baseline), not an "
            "absolute amount threshold - this is what makes the ML signal "
            "genuinely complementary to the existing rules engine rather "
            "than redundant with it."
        ),
    }
    joblib.dump(artifact, ARTIFACT_PATH)
    print(f"\nSaved artifact: {ARTIFACT_PATH} ({version})")

    with open("training_report.json", "w") as f:
        json.dump({k: v for k, v in artifact.items() if k != "model"}, f, indent=2)
    print("Saved training_report.json (human-readable summary, excludes the model binary)")


if __name__ == "__main__":
    main()
