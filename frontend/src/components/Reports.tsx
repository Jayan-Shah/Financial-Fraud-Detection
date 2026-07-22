import { useMemo } from "react";
import { useSelector } from "react-redux";
import {
  Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import type { RootState } from "../app/store";

const RISK_BUCKETS = ["0-20%", "20-40%", "40-60%", "60-80%", "80-100%"];

export function Reports() {
  const items = useSelector((s: RootState) => s.transactions.items);

  const stats = useMemo(() => {
    const total = items.length;
    const flagged = items.filter((t) => t.status === "flagged").length;
    const challenged = items.filter((t) => t.status === "challenged").length;
    const avgRisk = total ? items.reduce((sum, t) => sum + t.risk_score, 0) / total : 0;
    const avgMl = total ? items.reduce((sum, t) => sum + t.ml_score, 0) / total : 0;

    const confirmedFraud = items.filter((t) => t.reviewed_status === "confirmed_fraud").length;
    const falsePositive = items.filter((t) => t.reviewed_status === "false_positive").length;
    const pendingReview = items.filter(
      (t) => t.status !== "clear" && t.reviewed_status === "unreviewed"
    ).length;

    const byCountry = new Map<string, { country: string; clear: number; challenged: number; flagged: number }>();
    for (const t of items) {
      const row = byCountry.get(t.country) ?? { country: t.country, clear: 0, challenged: 0, flagged: 0 };
      row[t.status as "clear" | "challenged" | "flagged"] =
        (row[t.status as "clear" | "challenged" | "flagged"] ?? 0) + 1;
      byCountry.set(t.country, row);
    }
    const countryData = [...byCountry.values()]
      .sort((a, b) => b.clear + b.challenged + b.flagged - (a.clear + a.challenged + a.flagged))
      .slice(0, 8);

    const riskBuckets = RISK_BUCKETS.map((label) => ({ label, rules: 0, ml: 0 }));
    for (const t of items) {
      const rulesIdx = Math.min(Math.floor(t.risk_score * 5), 4);
      riskBuckets[rulesIdx].rules += 1;
      const mlIdx = Math.min(Math.floor(t.ml_score * 5), 4);
      riskBuckets[mlIdx].ml += 1;
    }

    return { total, flagged, challenged, avgRisk, avgMl, confirmedFraud, falsePositive, pendingReview, countryData, riskBuckets };
  }, [items]);

  return (
    <div className="reports">
      <div className="stat-cards">
        <div className="stat-card">
          <span className="stat-label">Transactions (buffered)</span>
          <span className="stat-value">{stats.total}</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">Challenged</span>
          <span className="stat-value challenged-text">{stats.challenged}</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">Flagged</span>
          <span className="stat-value flagged-text">{stats.flagged}</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">Avg Rules / ML Score</span>
          <span className="stat-value">{(stats.avgRisk * 100).toFixed(0)}% / {(stats.avgMl * 100).toFixed(0)}%</span>
        </div>
      </div>

      <div className="stat-cards">
        <div className="stat-card">
          <span className="stat-label">Pending Review</span>
          <span className="stat-value">{stats.pendingReview}</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">Confirmed Fraud</span>
          <span className="stat-value flagged-text">{stats.confirmedFraud}</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">False Positives</span>
          <span className="stat-value">{stats.falsePositive}</span>
        </div>
      </div>

      <div className="chart-row">
        <div className="chart-card">
          <h4>Transactions by Country</h4>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={stats.countryData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#232838" />
              <XAxis dataKey="country" stroke="#8892a6" fontSize={12} />
              <YAxis stroke="#8892a6" fontSize={12} allowDecimals={false} />
              <Tooltip contentStyle={{ background: "#131722", border: "1px solid #232838" }} />
              <Legend />
              <Bar dataKey="clear" stackId="a" fill="#3ecf8e" name="Clear" />
              <Bar dataKey="challenged" stackId="a" fill="#ffc857" name="Challenged" />
              <Bar dataKey="flagged" stackId="a" fill="#e5484d" name="Flagged" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="chart-card">
          <h4>Score Distribution: Rules vs. ML</h4>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={stats.riskBuckets}>
              <CartesianGrid strokeDasharray="3 3" stroke="#232838" />
              <XAxis dataKey="label" stroke="#8892a6" fontSize={12} />
              <YAxis stroke="#8892a6" fontSize={12} allowDecimals={false} />
              <Tooltip contentStyle={{ background: "#131722", border: "1px solid #232838" }} />
              <Legend />
              <Bar dataKey="rules" fill="#3e6ecf" name="Rules Score" />
              <Bar dataKey="ml" fill="#a855f7" name="ML Score" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <p className="muted reports-note">
        Based on the {stats.total} transactions currently buffered in this session (most recent
        5,000) - not the full historical table.
      </p>
    </div>
  );
}
