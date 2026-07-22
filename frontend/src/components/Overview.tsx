import { useMemo } from "react";
import { useSelector } from "react-redux";
import { AlertTriangle, ShieldAlert, TrendingUp, Cpu, CheckCircle2 } from "lucide-react";
import type { RootState } from "../app/store";

export function Overview() {
  const items = useSelector((s: RootState) => s.transactions.items);

  const stats = useMemo(() => {
    const total = items.length;
    const flagged = items.filter((t) => t.status === "flagged").length;
    const challenged = items.filter((t) => t.status === "challenged").length;
    const avgRules = total ? items.reduce((sum, t) => sum + t.risk_score, 0) / total : 0;
    const avgMl = total ? items.reduce((sum, t) => sum + t.ml_score, 0) / total : 0;
    const confirmedFraud = items.filter((t) => t.reviewed_status === "confirmed_fraud").length;
    const latestModelVersion = items.find((t) => t.ml_model_version)?.ml_model_version ?? null;
    const recent = items.filter((t) => t.status === "flagged" || t.status === "challenged").slice(0, 8);
    return { total, flagged, challenged, avgRules, avgMl, confirmedFraud, latestModelVersion, recent };
  }, [items]);

  return (
    <div className="overview">
      <div className="overview-header">
        <h2>Overview</h2>
        <p className="muted">Real-time summary across the current session's transaction stream.</p>
      </div>

      <div className="kpi-grid">
        <div className="kpi-card">
          <div className="kpi-icon neutral">
            <TrendingUp size={18} />
          </div>
          <div>
            <span className="kpi-value">{stats.total}</span>
            <span className="kpi-label">Transactions</span>
          </div>
        </div>

        <div className="kpi-card">
          <div className="kpi-icon warning">
            <ShieldAlert size={18} />
          </div>
          <div>
            <span className="kpi-value">{stats.challenged}</span>
            <span className="kpi-label">Challenged (step-up auth)</span>
          </div>
        </div>

        <div className="kpi-card">
          <div className="kpi-icon danger">
            <AlertTriangle size={18} />
          </div>
          <div>
            <span className="kpi-value">{stats.flagged}</span>
            <span className="kpi-label">Flagged / Blocked</span>
          </div>
        </div>

        <div className="kpi-card">
          <div className="kpi-icon success">
            <CheckCircle2 size={18} />
          </div>
          <div>
            <span className="kpi-value">{stats.confirmedFraud}</span>
            <span className="kpi-label">Analyst-Confirmed Fraud</span>
          </div>
        </div>
      </div>

      <div className="overview-row">
        <div className="panel">
          <h3>Scoring Engines</h3>
          <div className="engine-row">
            <span>Rules Engine (avg score)</span>
            <div className="engine-bar">
              <div className="engine-bar-fill rules" style={{ width: `${Math.min(stats.avgRules * 100, 100)}%` }} />
            </div>
            <span className="engine-value">{(stats.avgRules * 100).toFixed(1)}%</span>
          </div>
          <div className="engine-row">
            <span>ML Anomaly Model (avg score)</span>
            <div className="engine-bar">
              <div className="engine-bar-fill ml" style={{ width: `${Math.min(stats.avgMl * 100, 100)}%` }} />
            </div>
            <span className="engine-value">{(stats.avgMl * 100).toFixed(1)}%</span>
          </div>
          <div className="model-status">
            <Cpu size={14} />
            <span>
              {stats.latestModelVersion
                ? `Model active: ${stats.latestModelVersion}`
                : "No ML-scored transactions observed yet this session"}
            </span>
          </div>
        </div>

        <div className="panel">
          <h3>Recent High-Risk Activity</h3>
          {stats.recent.length === 0 ? (
            <p className="muted">Nothing flagged or challenged yet. Try "Simulate Fraud Burst" on the Live Feed.</p>
          ) : (
            <ul className="recent-list">
              {stats.recent.map((tx) => (
                <li key={tx.id}>
                  <span className={`badge ${tx.status}`}>{tx.status}</span>
                  <span className="recent-user">{tx.user_ref}</span>
                  <span className="recent-country">{tx.country}</span>
                  <span className="recent-amount">
                    {tx.amount.toFixed(2)} {tx.currency}
                  </span>
                  <span className="recent-time">{new Date(tx.created_at).toLocaleTimeString()}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
