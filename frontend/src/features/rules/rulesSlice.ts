import { createAsyncThunk, createSlice, PayloadAction } from "@reduxjs/toolkit";
import { api } from "../../api";
import type { FraudRule } from "../../types";

interface RulesState {
  items: FraudRule[];
  status: "idle" | "loading" | "error";
}

const initialState: RulesState = { items: [], status: "idle" };

export const fetchRules = createAsyncThunk("rules/fetch", () => api.listRules());

export const saveRule = createAsyncThunk(
  "rules/save",
  async (rule: FraudRule) => (await api.updateRule(rule.id, rule)) as FraudRule
);

const rulesSlice = createSlice({
  name: "rules",
  initialState,
  reducers: {
    ruleUpdatedLocally(state, action: PayloadAction<FraudRule>) {
      const idx = state.items.findIndex((r) => r.id === action.payload.id);
      if (idx >= 0) state.items[idx] = action.payload;
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(fetchRules.pending, (state) => {
        state.status = "loading";
      })
      .addCase(fetchRules.fulfilled, (state, action) => {
        state.items = action.payload;
        state.status = "idle";
      })
      .addCase(fetchRules.rejected, (state) => {
        state.status = "error";
      })
      .addCase(saveRule.fulfilled, (state, action) => {
        const idx = state.items.findIndex((r) => r.id === action.payload.id);
        if (idx >= 0) state.items[idx] = action.payload;
      });
  },
});

export const { ruleUpdatedLocally } = rulesSlice.actions;
export default rulesSlice.reducer;
