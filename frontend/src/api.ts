const BASE = "/api";

export function getToken(): string | null {
  return localStorage.getItem("access_token");
}

// Set by the app shell on mount - lets any failed authenticated request
// trigger a logout + redirect to the login screen, instead of leaving a
// stale/broken dashboard visible when a stored token has expired or is
// otherwise no longer valid.
let unauthorizedHandler: (() => void) | null = null;
export function setUnauthorizedHandler(fn: () => void) {
  unauthorizedHandler = fn;
}

function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(options.headers || {}),
    },
  });
  if (res.status === 401) {
    unauthorizedHandler?.();
  }
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export const api = {
  login: (email: string, password: string) =>
    request<{ access_token: string; role: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  me: () => request<import("./types").CurrentUser>("/auth/me"),
  listTransactions: () => request<import("./types").Transaction[]>("/transactions/"),
  listRules: () => request<import("./types").FraudRule[]>("/rules/"),
  createRule: (rule: Partial<import("./types").FraudRule>) =>
    request("/rules/", { method: "POST", body: JSON.stringify(rule) }),
  updateRule: (id: string, rule: Partial<import("./types").FraudRule>) =>
    request(`/rules/${id}`, { method: "PUT", body: JSON.stringify(rule) }),
  deleteRule: (id: string) => request(`/rules/${id}`, { method: "DELETE" }),
  reviewTransaction: (id: string, reviewStatus: "confirmed_fraud" | "false_positive" | "unreviewed") =>
    request<import("./types").Transaction>(`/transactions/${id}/review`, {
      method: "PATCH",
      body: JSON.stringify({ status: reviewStatus }),
    }),
  explainTransaction: (id: string) =>
    request<import("./types").MLExplanation>(`/transactions/${id}/ml-explain`),
  allowlistUser: (userRef: string, hours = 24) =>
    request<{ user_ref: string; expires_at: string }>("/transactions/allowlist", {
      method: "POST",
      body: JSON.stringify({ user_ref: userRef, hours }),
    }),
  simulateBurst: () =>
    request<{ accepted: boolean; simulated_user: string; count: number }>(
      "/transactions/simulate-burst",
      { method: "POST" }
    ),
};
