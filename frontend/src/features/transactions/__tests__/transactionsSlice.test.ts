import { describe, it, expect } from "vitest";
import reducer, { transactionReceived, hydrate, transactionReviewed } from "../transactionsSlice";
import type { Transaction } from "../../../types";

const sample = (overrides: Partial<Transaction> = {}): Transaction => ({
  id: "1",
  user_ref: "u1",
  amount: 100,
  currency: "USD",
  country: "US",
  merchant: null,
  status: "clear",
  risk_score: 0.1,
  risk_reasons: {},
  created_at: new Date().toISOString(),
  scored_at: new Date().toISOString(),
  ml_score: 0.05,
  ml_tier: "clean",
  ml_model_version: "v1.0.0_test",
  reviewed_status: "unreviewed",
  reviewed_by: null,
  reviewed_at: null,
  ...overrides,
});

describe("transactionsSlice", () => {
  it("prepends new transactions", () => {
    const state = reducer(undefined, hydrate([sample({ id: "a" })]));
    const next = reducer(state, transactionReceived(sample({ id: "b" })));
    expect(next.items[0].id).toBe("b");
    expect(next.items).toHaveLength(2);
  });

  it("tracks flagged count", () => {
    const state = reducer(undefined, { type: "init" } as any);
    const next = reducer(state, transactionReceived(sample({ id: "f", status: "flagged" })));
    expect(next.flaggedCount).toBe(1);
  });

  it("updates a transaction's review status in place", () => {
    const state = reducer(undefined, hydrate([sample({ id: "a", status: "flagged" })]));
    const next = reducer(
      state,
      transactionReviewed(sample({ id: "a", status: "flagged", reviewed_status: "confirmed_fraud" }))
    );
    expect(next.items[0].reviewed_status).toBe("confirmed_fraud");
    expect(next.items).toHaveLength(1);
  });
});
