import type { Middleware } from "@reduxjs/toolkit";
import {
  setConnected,
  transactionReceived,
} from "../features/transactions/transactionsSlice";
import { logout } from "../features/auth/authSlice";
import { getToken } from "../api";
import type { Transaction } from "../types";

export const WS_CONNECT = "socket/connect";
export const WS_DISCONNECT = "socket/disconnect";

const UNAUTHORIZED_CLOSE_CODE = 4401;

/**
 * Owns the single WebSocket connection to /ws/transactions. On every message
 * it parses the scored transaction and dispatches it straight into the
 * transactions slice - no React component ever touches the raw socket.
 * Reconnects with backoff if the connection drops.
 *
 * The JWT is passed as a query param (not a header) because browsers can't
 * attach custom headers to a WebSocket upgrade request - the backend uses
 * it to determine which organization's pub/sub channel to subscribe this
 * connection to, so one tenant never sees another tenant's live feed.
 */
export const websocketMiddleware: Middleware = (store) => {
  let socket: WebSocket | null = null;
  let retryDelay = 1000;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;

  const connect = () => {
    const token = getToken();
    if (!token) return; // not logged in yet - nothing to authenticate the socket with

    // In local dev, same-origin (via Vite's proxy) works fine for both
    // API calls and the WebSocket. In production on Vercel, the API is
    // reachable through vercel.json's rewrite, but Vercel does not
    // reliably tunnel WebSocket upgrades - so the WS connection needs to
    // go straight to the backend instead. VITE_WS_HOST (set in Vercel's
    // project environment variables) controls this; if it's unset, we
    // fall back to same-origin, which is correct for local dev.
    const wsHost = import.meta.env.VITE_WS_HOST || window.location.host;
    const protocol =
      wsHost === window.location.host && window.location.protocol !== "https:"
        ? "ws"
        : "wss";
    socket = new WebSocket(
      `${protocol}://${wsHost}/ws/transactions?token=${encodeURIComponent(
        token
      )}`
    );

    socket.onopen = () => {
      retryDelay = 1000;
      store.dispatch(setConnected(true));
    };

    socket.onmessage = (event) => {
      try {
        const tx: Transaction = JSON.parse(event.data);
        store.dispatch(transactionReceived(tx));
      } catch {
        // ignore malformed frames
      }
    };

    socket.onclose = (event) => {
      store.dispatch(setConnected(false));
      if (event.code === UNAUTHORIZED_CLOSE_CODE) {
        // The backend rejected this token outright (missing/expired/invalid)
        // - retrying with the same bad token would just loop forever, so
        // send the user back to login instead.
        socket = null;
        store.dispatch(logout());
        return;
      }
      retryTimer = setTimeout(connect, retryDelay);
      retryDelay = Math.min(retryDelay * 2, 15000);
    };

    socket.onerror = () => {
      socket?.close();
    };
  };

  return (next) => (action: any) => {
    if (action.type === WS_CONNECT && !socket) {
      connect();
    }
    if (action.type === WS_DISCONNECT) {
      if (retryTimer) clearTimeout(retryTimer);
      socket?.close();
      socket = null;
    }
    return next(action);
  };
};
