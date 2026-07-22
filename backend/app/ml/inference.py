"""
Inference wrapper for the trained fraud model. Import MLScorer once at
Celery worker module load time (mirrors the module-level load pattern
already used for the artifact in the original tasks.py draft) - never
re-instantiate per transaction.

Two separate methods, deliberately:
- score(): the hot path, called on every transaction. Just the calibrated
  probability + decision tier. Kept as fast as possible.
- explain(): NOT called on every transaction - only when an analyst opens
  a flagged transaction's detail view. Computes LightGBM's native
  pred_contrib (a TreeSHAP-equivalent per-feature breakdown), which costs
  a few extra milliseconds - fine on-demand, not fine at 50-100 tx/sec.
"""
from dataclasses import dataclass
from pathlib import Path

import joblib
import pandas as pd

DEFAULT_ARTIFACT_PATH = Path(__file__).parent / "fraud_model_artifact.joblib"


@dataclass
class ScoreResult:
    probability: float
    tier: str  # "clean" | "challenge" | "block"
    model_version: str


class MLScorer:
    def __init__(self, artifact_path: str | Path = DEFAULT_ARTIFACT_PATH):
        self._loaded = False
        try:
            artifact = joblib.load(artifact_path)
            self._model = artifact["model"]
            self._features = artifact["features"]
            self._thresholds = artifact["thresholds"]
            self._version = artifact["version"]

            # Warm-up: absorb LightGBM/sklearn's first-call lazy-init cost
            # here, at startup, instead of on the first real transaction.
            dummy = pd.DataFrame([[0.0] * len(self._features)], columns=self._features)
            self._model.predict_proba(dummy)

            self._loaded = True
        except Exception as exc:  # noqa: BLE001 - intentionally broad, see fallback below
            self._load_error = str(exc)

    @property
    def is_ready(self) -> bool:
        return self._loaded

    def score(self, feature_dict: dict) -> ScoreResult:
        """
        Hot path. Never raises - if the model isn't loaded or inference
        fails for any reason, returns a "clean" result with probability 0.0
        so a broken ML layer degrades to rules-only scoring rather than
        blocking transaction processing entirely.
        """
        if not self._loaded:
            return ScoreResult(probability=0.0, tier="clean", model_version="unavailable")

        try:
            row = pd.DataFrame([feature_dict], columns=self._features)
            probability = float(self._model.predict_proba(row)[0][1])
        except Exception:
            return ScoreResult(probability=0.0, tier="clean", model_version=self._version)

        if probability >= self._thresholds["block"]:
            tier = "block"
        elif probability >= self._thresholds["challenge"]:
            tier = "challenge"
        else:
            tier = "clean"

        return ScoreResult(probability=round(probability, 4), tier=tier, model_version=self._version)

    def explain(self, feature_dict: dict, top_n: int = 3) -> dict:
        """
        On-demand only (analyst detail view) - NOT part of the per-
        transaction hot path. Averages LightGBM's native pred_contrib
        across the calibrator's internal CV folds for a stable ranking of
        which features pushed this specific transaction's score up.
        """
        if not self._loaded:
            return {}

        row = pd.DataFrame([feature_dict], columns=self._features)
        contributions = None
        for calibrated in self._model.calibrated_classifiers_:
            inner = getattr(calibrated, "estimator", None) or getattr(calibrated, "base_estimator", None)
            booster = inner.booster_
            contrib = booster.predict(row, pred_contrib=True)[0][:-1]  # last column is the base value
            contributions = contrib if contributions is None else contributions + contrib
        contributions = contributions / len(self._model.calibrated_classifiers_)

        ranked = sorted(zip(self._features, contributions), key=lambda x: -abs(x[1]))
        return {name: round(float(value), 4) for name, value in ranked[:top_n]}
