import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";

export function CodexOAuthCallbackPage() {
  const [searchParams] = useSearchParams();

  useEffect(() => {
    const returnUri =
      import.meta.env.VITE_CODEX_OAUTH_RETURN_URI ??
      `${window.location.origin}/settings/ai-models`;
    const target = new URL(returnUri);

    const code = searchParams.get("code");
    const state = searchParams.get("state");
    const error = searchParams.get("error");
    const errorDescription = searchParams.get("error_description");

    if (code) {
      target.searchParams.set("code", code);
    }
    if (state) {
      target.searchParams.set("state", state);
    }
    if (error) {
      target.searchParams.set("oauth_error", error);
    }
    if (errorDescription) {
      target.searchParams.set("oauth_error_description", errorDescription);
    }

    window.location.replace(target.toString());
  }, [searchParams]);

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl items-center justify-center p-6">
      <p className="text-sm text-slate-300">Completing Codex sign-in...</p>
    </main>
  );
}
