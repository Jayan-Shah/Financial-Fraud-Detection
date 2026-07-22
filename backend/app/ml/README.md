# Fraud Risk-Scoring ML Layer

Lives at `backend/app/ml/` and is imported directly by the Celery worker
(`app/tasks.py`) and the FastAPI app (`app/routers/transactions.py`, for
the on-demand explain endpoint) - this is not a standalone service.

## Files

- `generate_data.py` — synthetic dataset generator + leak-free streaming
  feature computation (see below for why "streaming" specifically)
- `train_pipeline.py` — temporal split, class-weighted LightGBM, isotonic
  calibration, data-derived thresholds, feature importance, artifact export
- `inference.py` — `MLScorer` class: load once, `score()` for the hot
  path, `explain()` for on-demand analyst detail (see `docs/ML_DESIGN.md`)
- `test_inference.py` — sanity checks and a latency benchmark
- `fraud_model_artifact.joblib` — **not committed** (gitignored, like any
  build artifact) — generate it locally, see below

## Training the model

```bash
cd backend/app/ml
pip install -r ../../requirements.txt   # ML deps are part of the main backend requirements
python train_pipeline.py
python test_inference.py
```

This writes `fraud_model_artifact.joblib` into this same directory, which
is where `MLScorer`'s default path expects it (`app/ml/inference.py`'s
`DEFAULT_ARTIFACT_PATH` resolves relative to this file, not the process's
working directory - so it loads correctly regardless of whether the
Celery worker is launched from `backend/` or anywhere else).

**Restart the Celery worker after (re)training** — the artifact is loaded
once at worker process startup, not re-read per transaction.

## The iteration history (worth reading if you're presenting this project)

This model went through four real, diagnosed failure modes before landing
on something trustworthy. Each is worth knowing, not just the final state:

**1. Label was amount-based, not behavioral.** The first version labeled
fraud as `amount > 300` — which made the model redundant with the existing
rules engine and would have false-positived on ordinary expensive
purchases. Fixed by injecting three genuine behavioral patterns instead:
velocity bursts, geo-takeover sequences, and amount spikes measured
relative to *each user's own* baseline.

**2. A single feature became a trivial shortcut.** After fixing the label,
`time_since_last_tx` alone separated classes almost perfectly (89% of
feature importance) because injected fraud used near-perfectly-even
transaction spacing that never occurred in "normal" traffic. Fixed by
adding real timing jitter to injected fraud and broadening legitimate
quick-succession traffic to genuinely overlap fraud's gap range — forcing
the model to actually use velocity/geo/amount signals together.

**3. Too few examples per fraud type to survive a temporal split.**
Broadening the overlap (fix #2) also thinned out the total fraud count.
With only ~300 total fraud rows split three ways by time and further by
internal CV folds, the model overfit to noise (`time_dow` showing 22%
importance — nonsensical). Fixed by increasing both the user count and
the fraud injection rate for more absolute data volume, and adding an
explicit per-fraud-type-per-split diagnostic to `train_pipeline.py` so
this is caught immediately in the training output, not discovered later
via failing sanity checks.

**4. The CHALLENGE threshold could derive to ~0.** With a very low base
fraud rate, the cost-derived target precision for CHALLENGE (~4.76%) is
close enough to the base rate that the validation curve cleared it at an
almost-zero probability — meaning any non-zero score would challenge a
transaction, including clearly legitimate ones. Fixed with an explicit
minimum probability floor (`MIN_CHALLENGE_PROBABILITY`), applied on top of
the theoretically-derived value, not instead of it.

The lesson underneath all four: a model that "looks done" (compiles, runs,
produces a PR-AUC number) can still be fundamentally broken in a way that
only shows up when you actually interrogate the feature importances, run
sanity checks against known-clean and known-fraud patterns, and check data
volume per class per split — not just the headline metric.

## What this layer does NOT do

Model versioning via MLflow, automated drift detection, a scheduled
retraining pipeline, and shadow deployment are real practices worth
discussing (see `docs/ML_DESIGN.md`) but aren't built here — this is a
portfolio/hackathon-scoped system, not enterprise MLOps infrastructure.
Retraining today is a manual re-run of `train_pipeline.py`.
