import { useState } from "react";
import { useDispatch } from "react-redux";
import { Brain, UserCheck, Loader2 } from "lucide-react";
import type { AppDispatch } from "../app/store";
import { transactionReviewed } from "../features/transactions/transactionsSlice";
import { api } from "../api";
import type { MLExplanation, Transaction } from "../types";

const REASON_LABELS: Record<string, string> = {
  velocity: "Velocity",
  geo_spread: "Geo Spread",
  amount_threshold: "High Amount",
  ml_signal: "ML Signal",
  manual_override: "Manual Override",
};

const REVIEW_LABELS: Record<Transaction["reviewed_status"], string> = {
  unreviewed: "Unreviewed",
  confirmed_fraud: "Confirmed Fraud",
  false_positive: "False Positive",
};

const ML_TIER_LABELS: Record<Transaction["ml_tier"], string> = {
  clean: "Clean",
  challenge: "Elevated (step-up auth)",
  block: "High confidence anomaly",
};

export function TransactionDetail({
  tx,
  onClose,
  onUpdated,
}: {
  tx: Transaction;
  onClose: () => void;
  onUpdated: (tx: Transaction) => void;
}) {
  const dispatch = useDispatch<AppDispatch>();
  const [submitting, setSubmitting] = useState(false);
  const [explanation, setExplanation] = useState<MLExplanation | null>(null);
  const [loadingExplain, setLoadingExplain] = useState(false);
  const [allowlisting, setAllowlisting] = useState(false);
  const [allowlistMsg, setAllowlistMsg] = useState<string | null>(null);

  const reasonEntries = Object.entries(tx.risk_reasons ?? {});

  const submitReview = async (reviewStatus: Transaction["reviewed_status"]) => {
    setSubmitting(true);
    try {
      const updated = await api.reviewTransaction(tx.id, reviewStatus);
      dispatch(transactionReviewed(updated));
      onUpdated(updated);
    } catch {
      // best-effort - a failed review shouldn't crash the modal
    } finally {
      setSubmitting(false);
    }
  };

  const loadExplanation = async () => {
    setLoadingExplain(true);
    try {
      const result = await api.explainTransaction(tx.id);
      setExplanation(result);
    } catch {
      setExplanation({ available: false, reason: "Failed to load explanation." });
    } finally {
      setLoadingExplain(false);
    }
  };

  const allowlistUser = async () => {
    setAllowlisting(true);
    try {
      const result = await api.allowlistUser(tx.user_ref, 24);
      setAllowlistMsg(`${tx.user_ref} allowlisted until ${new Date(result.expires_at).toLocaleString()}`);
    } catch {
      setAllowlistMsg("Failed to allowlist user.");
    } finally {
      setAllowlisting(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Transaction Detail</h3>
          <button className="modal-close" onClick={onClose}>
            ×
          </button>
        </div>

        <div className={`modal-status-banner ${tx.status}`}>
          {tx.status === "flagged" && "⚠ Flagged / blocked"}
          {tx.status === "challenged" && "⚠ Challenged - step-up authentication requested"}
          {tx.status === "clear" && "Cleared - no rules or ML signal triggered"}
        </div>

        <dl className="detail-grid">
          <dt>Transaction ID</dt>
          <dd className="mono">{tx.id}</dd>
          <dt>User</dt>
          <dd>{tx.user_ref}</dd>
          <dt>Amount</dt>
          <dd>
            {tx.amount.toFixed(2)} {tx.currency}
          </dd>
          <dt>Country</dt>
          <dd>{tx.country}</dd>
          <dt>Merchant</dt>
          <dd>{tx.merchant ?? "—"}</dd>
          <dt>Rules Score</dt>
          <dd>{(tx.risk_score * 100).toFixed(0)}%</dd>
          <dt>Received</dt>
          <dd>{new Date(tx.created_at).toLocaleString()}</dd>
          <dt>Scored</dt>
          <dd>{tx.scored_at ? new Date(tx.scored_at).toLocaleString() : "—"}</dd>
        </dl>

        <h4>Rule Breakdown</h4>
        {reasonEntries.length === 0 ? (
          <p className="muted">No fraud rules were triggered by this transaction.</p>
        ) : (
          <ul className="reason-list">
            {reasonEntries.map(([key, detail]) => (
              <li key={key}>
                <span className="reason-tag">{REASON_LABELS[key] ?? key}</span>
                <span>{detail}</span>
              </li>
            ))}
          </ul>
        )}

        <div className="ml-section">
          <h4>
            <Brain size={15} /> ML Breakdown
          </h4>
          <div className="ml-summary">
            <div>
              <span className="muted">Anomaly Probability</span>
              <strong>{(tx.ml_score * 100).toFixed(1)}%</strong>
            </div>
            <div>
              <span className="muted">Tier</span>
              <strong>{ML_TIER_LABELS[tx.ml_tier]}</strong>
            </div>
            <div>
              <span className="muted">Model Version</span>
              <strong className="mono-small">{tx.ml_model_version ?? "n/a"}</strong>
            </div>
          </div>

          {!explanation ? (
            <button className="explain-btn" onClick={loadExplanation} disabled={loadingExplain}>
              {loadingExplain ? <Loader2 size={14} className="spin" /> : <Brain size={14} />}
              {loadingExplain ? "Loading explanation..." : "Explain This Score"}
            </button>
          ) : explanation.available ? (
            <div className="ml-contributions">
              <p className="muted" style={{ marginBottom: 8 }}>Top contributing features (higher = pushed the score up):</p>
              {Object.entries(explanation.top_contributing_features ?? {}).map(([feature, value]) => (
                <div className="contribution-row" key={feature}>
                  <span className="contribution-name">{feature}</span>
                  <span className={`contribution-value ${value >= 0 ? "positive" : "negative"}`}>
                    {value >= 0 ? "+" : ""}{value.toFixed(3)}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="muted">{explanation.reason}</p>
          )}
        </div>

        {tx.status !== "clear" && (
          <div className="review-section">
            <h4>Analyst Review</h4>
            <p className="muted review-current">
              Current status: <strong>{REVIEW_LABELS[tx.reviewed_status]}</strong>
              {tx.reviewed_by ? ` (by ${tx.reviewed_by})` : ""}
            </p>
            <div className="review-buttons">
              <button
                className="review-btn confirm"
                disabled={submitting || tx.reviewed_status === "confirmed_fraud"}
                onClick={() => submitReview("confirmed_fraud")}
              >
                Confirm Fraud
              </button>
              <button
                className="review-btn dismiss"
                disabled={submitting || tx.reviewed_status === "false_positive"}
                onClick={() => submitReview("false_positive")}
              >
                Mark False Positive
              </button>
              {tx.reviewed_status !== "unreviewed" && (
                <button className="review-btn reset" disabled={submitting} onClick={() => submitReview("unreviewed")}>
                  Reset
                </button>
              )}
            </div>

            <div className="allowlist-row">
              <button className="allowlist-btn" onClick={allowlistUser} disabled={allowlisting}>
                <UserCheck size={14} />
                {allowlisting ? "Allowlisting..." : "Allowlist User (24h)"}
              </button>
              {allowlistMsg && <span className="muted allowlist-msg">{allowlistMsg}</span>}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
