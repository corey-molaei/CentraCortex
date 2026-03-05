import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { googleLoginStart, login } from "../api/client";
import { sessionStore } from "../api/session";

export function LoginPage() {
  const [email, setEmail] = useState("admin@example.com");
  const [password, setPassword] = useState("password123");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [googleLoading, setGoogleLoading] = useState(false);
  const navigate = useNavigate();

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);

    if (!email.includes("@")) {
      setError("Enter a valid email address.");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }

    setLoading(true);
    try {
      const data = await login(email, password);
      sessionStore.save(data);
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  }

  async function onGoogleLogin() {
    setError(null);
    setGoogleLoading(true);
    try {
      const redirectUri = `${window.location.origin}/login/google/callback`;
      const response = await googleLoginStart(redirectUri);
      window.location.href = response.auth_url;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Google login start failed");
      setGoogleLoading(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-md items-center px-6">
      <form className="w-full rounded-xl border border-slate-700 bg-panel p-6" onSubmit={onSubmit}>
        <h1 className="mb-1 text-2xl font-semibold">CentraCortex Login</h1>
        <p className="mb-6 text-sm text-slate-300">Sign in and select your tenant context.</p>

        <label className="mb-2 block text-sm">Email</label>
        <input
          className="mb-4 w-full rounded border border-slate-700 bg-slate-900 p-2"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />

        <label className="mb-2 block text-sm">Password</label>
        <input
          className="mb-4 w-full rounded border border-slate-700 bg-slate-900 p-2"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />

        {error && <div className="mb-4 rounded bg-red-500/15 p-2 text-sm text-red-200">{error}</div>}

        <button
          type="submit"
          className="w-full rounded bg-accent px-4 py-2 font-semibold text-slate-950 transition hover:brightness-110 disabled:opacity-70"
          disabled={loading}
        >
          {loading ? "Signing in..." : "Sign In"}
        </button>

        <button
          className="mt-3 w-full rounded border border-slate-600 px-4 py-2 font-semibold text-slate-100 transition hover:bg-white/10 disabled:opacity-70"
          disabled={googleLoading}
          onClick={onGoogleLogin}
          type="button"
        >
          {googleLoading ? "Redirecting to Google..." : "Sign in with Google"}
        </button>
      </form>
    </main>
  );
}
