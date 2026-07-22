import { FormEvent, useState } from "react";
import { useDispatch, useSelector } from "react-redux";
import type { AppDispatch, RootState } from "../app/store";
import { login } from "../features/auth/authSlice";

const DEMO_EMAIL = "demo@frauddetect.dev";
const DEMO_PASSWORD = "demo-view-only";

export function Login() {
  const dispatch = useDispatch<AppDispatch>();
  const error = useSelector((s: RootState) => s.auth.error);
  const [email, setEmail] = useState("admin@frauddetect.dev");
  const [password, setPassword] = useState("");

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    dispatch(login({ email, password }));
  };

  const onDemoLogin = () => {
    dispatch(login({ email: DEMO_EMAIL, password: DEMO_PASSWORD }));
  };

  return (
    <div className="login-wrapper">
      <form className="login-card" onSubmit={onSubmit}>
        <h2>Compliance Sign In</h2>
        <label>
          Email
          <input value={email} onChange={(e) => setEmail(e.target.value)} type="email" required />
        </label>
        <label>
          Password
          <input value={password} onChange={(e) => setPassword(e.target.value)} type="password" required />
        </label>
        {error && <p className="error">{error}</p>}
        <button type="submit">Sign In</button>

        <div className="login-divider">
          <span>or</span>
        </div>

        <button type="button" className="demo-login-btn" onClick={onDemoLogin}>
          View Demo (read-only)
        </button>
        <p className="muted demo-hint">
          No credentials needed - explores the live feed and reports as a read-only analyst.
        </p>
      </form>
    </div>
  );
}
