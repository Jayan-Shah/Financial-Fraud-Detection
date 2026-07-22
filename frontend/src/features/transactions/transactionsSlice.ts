import { createSlice, PayloadAction } from "@reduxjs/toolkit";
import type { Transaction } from "../../types";

interface TransactionsState {
  items: Transaction[];
  connected: boolean;
  flaggedCount: number;
}

const MAX_BUFFERED = 5000; // cap so the grid never grows unbounded in a long-running session

const initialState: TransactionsState = {
  items: [],
  connected: false,
  flaggedCount: 0,
};

const recomputeFlaggedCount = (items: Transaction[]) => items.filter((t) => t.status === "flagged").length;

const transactionsSlice = createSlice({
  name: "transactions",
  initialState,
  reducers: {
    hydrate(state, action: PayloadAction<Transaction[]>) {
      // Dedupe defensively even on initial load, in case the backend ever
      // returns overlapping rows.
      const seen = new Set<string>();
      const deduped: Transaction[] = [];
      for (const tx of action.payload) {
        if (seen.has(tx.id)) continue;
        seen.add(tx.id);
        deduped.push(tx);
      }
      state.items = deduped;
      state.flaggedCount = recomputeFlaggedCount(deduped);
    },
    transactionReceived(state, action: PayloadAction<Transaction>) {
      // Defensive dedupe: if this transaction id is already present (e.g. a
      // redelivered Celery task after a worker restart, or any other
      // at-least-once delivery edge case), update it in place instead of
      // adding a second row - a live feed should never show the same
      // transaction twice.
      const existingIdx = state.items.findIndex((t) => t.id === action.payload.id);
      if (existingIdx >= 0) {
        state.items[existingIdx] = action.payload;
      } else {
        state.items.unshift(action.payload);
        if (state.items.length > MAX_BUFFERED) state.items.pop();
      }
      state.flaggedCount = recomputeFlaggedCount(state.items);
    },
    transactionReviewed(state, action: PayloadAction<Transaction>) {
      const idx = state.items.findIndex((t) => t.id === action.payload.id);
      if (idx >= 0) state.items[idx] = action.payload;
    },
    setConnected(state, action: PayloadAction<boolean>) {
      state.connected = action.payload;
    },
  },
});

export const { hydrate, transactionReceived, setConnected, transactionReviewed } = transactionsSlice.actions;
export default transactionsSlice.reducer;
