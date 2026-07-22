import { createAsyncThunk, createSlice } from "@reduxjs/toolkit";
import { api } from "../../api";
import type { CurrentUser } from "../../types";

interface AuthState {
  token: string | null;
  role: string | null;
  error: string | null;
  currentUser: CurrentUser | null;
}

const initialState: AuthState = {
  token: localStorage.getItem("access_token"),
  role: localStorage.getItem("role"),
  error: null,
  currentUser: null,
};

export const login = createAsyncThunk(
  "auth/login",
  async ({ email, password }: { email: string; password: string }) => api.login(email, password)
);

export const fetchCurrentUser = createAsyncThunk("auth/fetchCurrentUser", () => api.me());

const authSlice = createSlice({
  name: "auth",
  initialState,
  reducers: {
    logout(state) {
      state.token = null;
      state.role = null;
      state.currentUser = null;
      localStorage.removeItem("access_token");
      localStorage.removeItem("role");
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(login.fulfilled, (state, action) => {
        state.token = action.payload.access_token;
        state.role = action.payload.role;
        state.error = null;
        localStorage.setItem("access_token", action.payload.access_token);
        localStorage.setItem("role", action.payload.role);
      })
      .addCase(login.rejected, (state) => {
        state.error = "Invalid email or password";
      })
      .addCase(fetchCurrentUser.fulfilled, (state, action) => {
        state.currentUser = action.payload;
      });
  },
});

export const { logout } = authSlice.actions;
export default authSlice.reducer;
