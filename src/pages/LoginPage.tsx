import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { signInWithEmailAndPassword } from "firebase/auth";
import { auth } from "../firebase/firebase";
import { ensureUserProfile } from "../features/auth/ensureUserProfile";

export default function LoginPage() {
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await signInWithEmailAndPassword(auth, email.trim(), password);
      await ensureUserProfile(auth.currentUser!);
      nav("/app", { replace: true });
    } catch (err: any) {
      setError(err?.message ?? "Login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ maxWidth: 420, margin: "48px auto", padding: 24 }}>
      <h1>Login</h1>

      <form onSubmit={onSubmit} style={{ display: "grid", gap: 12 }}>
        <label>
          Email
          <input
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            type="email"
            autoComplete="email"
            required
            style={{ width: "100%", padding: 10, marginTop: 6 }}
          />
        </label>

        <label>
          Password
          <input
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            type="password"
            autoComplete="current-password"
            required
            style={{ width: "100%", padding: 10, marginTop: 6 }}
          />
        </label>

        {error && (
          <div style={{ background: "#ffe5e5", padding: 10, borderRadius: 6 }}>
            {error}
          </div>
        )}

        <button disabled={busy} style={{ padding: 10 }}>
          {busy ? "Logging in..." : "Login"}
        </button>
      </form>

      <p style={{ marginTop: 12 }}>
        No account? <Link to="/register">Create one</Link>
      </p>
    </div>
  );
}
