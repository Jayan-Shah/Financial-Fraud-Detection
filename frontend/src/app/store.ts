import { configureStore } from "@reduxjs/toolkit";
import transactionsReducer from "../features/transactions/transactionsSlice";
import rulesReducer from "../features/rules/rulesSlice";
import authReducer from "../features/auth/authSlice";
import { websocketMiddleware } from "../middleware/websocketMiddleware";

export const store = configureStore({
  reducer: {
    transactions: transactionsReducer,
    rules: rulesReducer,
    auth: authReducer,
  },
  middleware: (getDefaultMiddleware) => getDefaultMiddleware().concat(websocketMiddleware),
});

export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;
