# ML Design & Decision Engine

This document explains how the ML layer works and why it's wired into the
system the way it is. See `backend/app/ml/` for the actual training and
inference code.

## Two independent scoring engines, not one blended score

An earlier version of this system blended the rules score and ML score
linearly (e.g. `0.6 * rules + 0.4 * ml`). That design has a real flaw: if
the ML model produces a low-but-meaningful probability (say, a genuinely
suspicious 8%, in a system where average fraud prevalence is under 2%),
diluting it into a blend makes it too weak to ever cross a combined flag
threshold on its own — the ML signal effectively never mattered.

Instead, the two engines run independently and either can trigger a
decision on its own (an "OR-gate"):

```
1. Manual allowlist override  -> ALLOW (bypasses everything)
2. Rules score >= 0.5         -> BLOCK  (existing velocity/geo/amount rules)
3. ML tier == "block"         -> BLOCK  (high-confidence anomaly, no rule matched)
4. ML tier == "challenge"     -> CHALLENGE (step-up auth / analyst review)
5. Otherwise                  -> CLEAR
```

This means the ML model can genuinely catch a fraud pattern that no
hand-written rule covers — that's the entire point of adding it.

## Where the ML thresholds come from

`challenge` and `block` are **not** guessed numbers. They're derived during
training (`train_pipeline.py`) from the validation set's actual
precision-recall curve, targeting a precision implied by an assumed cost
ratio (a missed fraud costs ~$500 on average; a false positive costs ~$25
in support/churn — see `app/ml/train_pipeline.py` for the exact math). A
practical floor (`0.01`) is also enforced, since a target precision very
close to the base fraud rate can otherwise derive a near-zero threshold
that triggers on essentially any non-zero score.

Re-run `train_pipeline.py` and the printed thresholds will differ slightly
run to run (synthetic data, randomness) — trust what it prints over any
number written down here.

## Feature computation - zero train/serve skew, by construction

The features the model consumes (`amount_z_score`, `velocity_120s`,
`geo_countries_120s`, `geo_country_rarity`, `time_since_last_tx`, cyclical
time encodings) are computed identically in two places:

- **Training** (`generate_data.py::compute_features_streaming`): a
  chronological replay of synthetic transactions, reading each user's
  state, computing features, THEN updating the state.
- **Serving** (`app/tasks.py::score_transaction` /
  `_fetch_and_update_lifetime_state`): the live Celery worker does the
  exact same fetch-before-update sequence against Redis.

These aren't approximations of each other — they're the same algorithm,
one running offline against simulated data, one running online against
real Redis state. That's what eliminates train/serve skew, rather than
trying to correct for it after the fact.

## Why the label is behavioral, not amount-based

Early iterations labeled synthetic fraud as `amount > 300`, which made the
model redundant with the existing amount-threshold rule and would have
false-positived on ordinary expensive purchases. The corrected label
(`generate_data.py`) injects three genuine behavioral patterns instead:
velocity bursts (card testing), geo-takeover sequences (account
compromise), and amount spikes measured relative to *each user's own*
baseline (not a global dollar figure). See `backend/app/ml/README.md` for
the full iteration history, including the two failure modes hit along the
way (a single feature becoming a trivial shortcut; too few examples per
fraud type to survive a temporal split) and how each was diagnosed and fixed.

## Explainability: fast path vs. slow path

`MLScorer.score()` — called on every transaction — only returns a
probability and a tier. It's the hot path and stays fast (single-digit
milliseconds).

`MLScorer.explain()` — LightGBM's native `pred_contrib`, a
TreeSHAP-equivalent per-feature breakdown — is **never** called during
scoring. It's exposed only via `GET /api/transactions/{id}/ml-explain`,
triggered when an analyst opens a flagged/challenged transaction's detail
view. The exact feature vector used at scoring time is stored on the
transaction row (`ml_features`) specifically so this on-demand explanation
reconstructs the real inputs, not a drifted approximation from current
state.

## What's intentionally out of scope

Model versioning via MLflow, automated drift detection (PSI), a
scheduled retraining DAG, and shadow deployment are all real
production-fraud-team practices worth knowing and being able to discuss
(see `backend/app/ml/README.md`'s "production lifecycle" notes) — but none
of that infrastructure is actually built here. Retraining today is a
manual re-run of `train_pipeline.py`.
