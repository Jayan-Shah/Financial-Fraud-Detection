import { useEffect, useState } from "react";
import { useDispatch, useSelector } from "react-redux";
import type { AppDispatch, RootState } from "./app/store";
import { WS_CONNECT, WS_DISCONNECT } from "./middleware/websocketMiddleware";
import { hydrate } from "./features/transactions/transactionsSlice";
import { logout, fetchCurrentUser } from "./features/auth/authSlice";
import { api, setUnauthorizedHandler } from "./api";
import { Sidebar, type Tab } from "./components/Sidebar";
import { Overview } from "./components/Overview";
import { TransactionGrid } from "./components/TransactionGrid";
import { AdminDashboard } from "./components/AdminDashboard";
import { Reports } from "./components/Reports";
import { Login } from "./components/Login";

const TAB_TITLES: Record<Tab, string> = {
  overview: "Overview",
  live: "Live Feed",
  reports: "Reports",
  admin: "Rules Admin",
};

export default function App() {
  const dispatch = useDispatch<AppDispatch>();
  const token = useSelector((s: RootState) => s.auth.token);
  const role = useSelector((s: RootState) => s.auth.role);
  const currentUser = useSelector((s: RootState) => s.auth.currentUser);
  const connected = useSelector((s: RootState) => s.transactions.connected);
  const [tab, setTab] = useState<Tab>("overview");

  useEffect(() => {
    // A stored token that's expired or otherwise no longer valid should
    // never leave the user staring at a broken dashboard - any 401 from
    // the API (or the WebSocket rejecting the token, see the middleware)
    // sends them straight back to the login screen.
    setUnauthorizedHandler(() => dispatch(logout()));
  }, [dispatch]);

  useEffect(() => {
    if (!token) return;
    dispatch(fetchCurrentUser());
    dispatch({ type: WS_CONNECT });
    api.listTransactions().then((tx) => dispatch(hydrate(tx))).catch(() => {});
    return () => {
      dispatch({ type: WS_DISCONNECT });
    };
  }, [token, dispatch]);

  if (!token) {
    return (
      <div className="app-shell centered">
        <Login />
      </div>
    );
  }

  return (
    <div className="app-shell with-sidebar">
      <Sidebar
        activeTab={tab}
        onNavigate={setTab}
        role={role}
        orgName={currentUser?.organization_name ?? null}
        userEmail={currentUser?.email ?? null}
        connected={connected}
        onSignOut={() => dispatch(logout())}
      />
      <div className="main-column">
        <header className="topbar">
          <h1>{TAB_TITLES[tab]}</h1>
        </header>
        <main>
          {tab === "overview" && <Overview />}
          {tab === "live" && <TransactionGrid />}
          {tab === "reports" && <Reports />}
          {tab === "admin" && <AdminDashboard />}
        </main>
      </div>
    </div>
  );
}
