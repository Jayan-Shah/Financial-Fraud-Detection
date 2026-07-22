import { useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useSelector } from "react-redux";
import { Zap } from "lucide-react";
import type { RootState } from "../app/store";
import type { Transaction } from "../types";
import { TransactionDetail } from "./TransactionDetail";
import { api } from "../api";

type Filter = "all" | "flagged" | "challenged" | "reviewed";

/**
 * Renders however many thousands of transactions are buffered in Redux
 * state, but only ever mounts the ~20 rows actually visible in the
 * viewport. This is what keeps the UI smooth at 50-100 events/sec instead
 * of freezing once a few hundred rows pile up.
 *
 * "Flagged" and "Challenged" only ever show UNREVIEWED items - once an
 * analyst confirms or dismisses one, it moves to "Reviewed" instead of
 * continuing to clutter the actionable queue. "All" still shows
 * everything, unfiltered, as the full audit trail.
 */
export function TransactionGrid() {
  const items = useSelector((s: RootState) => s.transactions.items);
  const parentRef = useRef<HTMLDivElement>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [selected, setSelected] = useState<Transaction | null>(null);
  const [simulating, setSimulating] = useState(false);
  const [simulateMsg, setSimulateMsg] = useState<string | null>(null);

  const filteredItems = useMemo(() => {
    switch (filter) {
      case "flagged":
        return items.filter((t) => t.status === "flagged" && t.reviewed_status === "unreviewed");
      case "challenged":
        return items.filter((t) => t.status === "challenged" && t.reviewed_status === "unreviewed");
      case "reviewed":
        return items.filter((t) => t.reviewed_status !== "unreviewed");
      default:
        return items;
    }
  }, [items, filter]);

  const rowVirtualizer = useVirtualizer({
    count: filteredItems.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 46,
    overscan: 12,
  });

  const runSimulation = async () => {
    setSimulating(true);
    setSimulateMsg(null);
    try {
      const result = await api.simulateBurst();
      setSimulateMsg(`Fired ${result.count} transactions for ${result.simulated_user} - watch for a flag below.`);
    } catch {
      setSimulateMsg("Simulation failed to start - check the backend is reachable.");
    } finally {
      setSimulating(false);
      setTimeout(() => setSimulateMsg(null), 6000);
    }
  };

  return (
    <div className="grid-wrapper">
      <div className="grid-toolbar">
        <div className="filter-group">
          <button className={filter === "all" ? "active" : ""} onClick={() => setFilter("all")}>
            All
          </button>
          <button className={filter === "challenged" ? "active" : ""} onClick={() => setFilter("challenged")}>
            Challenged
          </button>
          <button className={filter === "flagged" ? "active" : ""} onClick={() => setFilter("flagged")}>
            Flagged
          </button>
          <button className={filter === "reviewed" ? "active" : ""} onClick={() => setFilter("reviewed")}>
            Reviewed
          </button>
        </div>
        <button className="simulate-btn" disabled={simulating} onClick={runSimulation}>
          <Zap size={14} />
          {simulating ? "Simulating..." : "Simulate Fraud Burst"}
        </button>
        {simulateMsg && <span className="grid-toolbar-hint simulate-msg">{simulateMsg}</span>}
        {!simulateMsg && <span className="grid-toolbar-hint">Click a row for details</span>}
      </div>

      <div className="grid-header">
        <span>Time</span>
        <span>User</span>
        <span>Amount</span>
        <span>Country</span>
        <span>Status</span>
        <span>Rules</span>
        <span>ML</span>
      </div>
      <div ref={parentRef} className="grid-scroll">
        {filteredItems.length === 0 ? (
          <p className="muted empty-state">
            {filter === "reviewed" ? "No reviewed transactions yet." : "Nothing here yet."}
          </p>
        ) : (
          <div style={{ height: rowVirtualizer.getTotalSize(), position: "relative" }}>
            {rowVirtualizer.getVirtualItems().map((virtualRow) => {
              const tx = filteredItems[virtualRow.index];
              return (
                <div
                  key={virtualRow.key}
                  className={`grid-row clickable ${tx.status}`}
                  onClick={() => setSelected(tx)}
                  style={{
                    position: "absolute",
                    top: 0,
                    left: 0,
                    width: "100%",
                    height: virtualRow.size,
                    transform: `translateY(${virtualRow.start}px)`,
                  }}
                >
                  <span>{new Date(tx.created_at).toLocaleTimeString()}</span>
                  <span>{tx.user_ref}</span>
                  <span>
                    {tx.amount.toFixed(2)} {tx.currency}
                  </span>
                  <span>{tx.country}</span>
                  <span className={`badge ${tx.status}`}>{tx.status}</span>
                  <span>{(tx.risk_score * 100).toFixed(0)}%</span>
                  <span>{(tx.ml_score * 100).toFixed(0)}%</span>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {selected && (
        <TransactionDetail
          tx={selected}
          onClose={() => setSelected(null)}
          onUpdated={(updated) => setSelected(updated)}
        />
      )}
    </div>
  );
}
