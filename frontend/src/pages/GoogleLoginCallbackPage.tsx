import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { googleLoginCallback } from "../api/client";
import { sessionStore } from "../api/session";

export function GoogleLoginCallbackPage() {
  const [message, setMessage] = useState("Completing Google login...");
  const navigate = useNavigate();

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const state = params.get("state");

    if (!code || !state) {
      setMessage("Google login callback is missing code/state.");
      return;
    }

    googleLoginCallback(code, state)
      .then((data) => {
        sessionStore.save(data);
        navigate("/", { replace: true });
      })
      .catch((err) => {
        setMessage(err instanceof Error ? err.message : "Google login failed.");
      });
  }, [navigate]);

  return (
    <main className="mx-auto flex min-h-screen max-w-xl items-center px-6">
      <div className="w-full rounded-xl border border-slate-700 bg-panel p-6 text-sm text-slate-100">{message}</div>
    </main>
  );
}
