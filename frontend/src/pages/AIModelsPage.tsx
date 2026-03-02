import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  codexOAuthCallback,
  codexOAuthStart,
  createProvider,
  deleteProvider,
  disconnectCodexOAuth,
  getCodexOAuthStatus,
  listProviders,
  testProvider,
  updateProvider
} from "../api/llm";
import type { LLMProvider } from "../types/llm";

export function AIModelsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [providers, setProviders] = useState<LLMProvider[]>([]);
  const [name, setName] = useState("OpenAI Primary");
  const [providerType, setProviderType] = useState<"openai" | "vllm" | "ollama" | "other" | "codex">("openai");
  const [baseUrl, setBaseUrl] = useState("https://api.openai.com");
  const [apiKey, setApiKey] = useState("");
  const [modelName, setModelName] = useState("gpt-4.1-mini");
  const [isDefault, setIsDefault] = useState(true);
  const [isFallback, setIsFallback] = useState(false);
  const [rateLimit, setRateLimit] = useState(60);
  const [codexConnected, setCodexConnected] = useState(false);
  const [codexConnectedEmail, setCodexConnectedEmail] = useState<string | null>(null);
  const [codexAdminBlocked, setCodexAdminBlocked] = useState(false);
  const [editingProviderId, setEditingProviderId] = useState<string | null>(null);
  const [settingDefaultProviderId, setSettingDefaultProviderId] = useState<string | null>(null);
  const [deletingProviderId, setDeletingProviderId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const providerList = await listProviders();
    setProviders(providerList);
    try {
      const oauthStatus = await getCodexOAuthStatus();
      setCodexConnected(oauthStatus.connected);
      setCodexConnectedEmail(oauthStatus.connected_email);
      setCodexAdminBlocked(false);
    } catch {
      setCodexAdminBlocked(true);
      setCodexConnected(false);
      setCodexConnectedEmail(null);
    }
  }, []);

  useEffect(() => {
    load().catch((err) => {
      setError(err instanceof Error ? err.message : "Failed to load providers");
    });
  }, [load]);

  const callbackCode = searchParams.get("code");
  const callbackState = searchParams.get("state");
  const callbackError = searchParams.get("oauth_error");
  const callbackErrorDescription = searchParams.get("oauth_error_description");

  useEffect(() => {
    if (!callbackError) {
      return;
    }
    const decodedDetail = callbackErrorDescription ?? "";
    setError(decodedDetail ? `Codex OAuth failed: ${callbackError} (${decodedDetail})` : `Codex OAuth failed: ${callbackError}`);
    const next = new URLSearchParams(searchParams);
    next.delete("oauth_error");
    next.delete("oauth_error_description");
    setSearchParams(next, { replace: true });
  }, [callbackError, callbackErrorDescription, searchParams, setSearchParams]);

  useEffect(() => {
    if (!callbackCode || !callbackState) {
      return;
    }

    let active = true;
    codexOAuthCallback(callbackCode, callbackState)
      .then((result) => {
        if (!active) {
          return;
        }
        setError(null);
        setMessage(result.message);
      })
      .catch((err) => {
        if (!active) {
          return;
        }
        setError(err instanceof Error ? err.message : "Codex OAuth callback failed");
      })
      .finally(() => {
        if (!active) {
          return;
        }
        const next = new URLSearchParams(searchParams);
        next.delete("code");
        next.delete("state");
        setSearchParams(next, { replace: true });
        load().catch((err) => {
          setError(err instanceof Error ? err.message : "Failed to refresh providers");
        });
      });

    return () => {
      active = false;
    };
  }, [callbackCode, callbackState, load, searchParams, setSearchParams]);

  function resetForm() {
    setEditingProviderId(null);
    setName("OpenAI Primary");
    setProviderType("openai");
    setBaseUrl("https://api.openai.com");
    setApiKey("");
    setModelName("gpt-4.1-mini");
    setIsDefault(true);
    setIsFallback(false);
    setRateLimit(60);
  }

  function onEdit(provider: LLMProvider) {
    setEditingProviderId(provider.id);
    setName(provider.name);
    setProviderType(provider.provider_type);
    setBaseUrl(provider.base_url);
    setApiKey("");
    setModelName(provider.model_name);
    setIsDefault(provider.is_default);
    setIsFallback(provider.is_fallback);
    setRateLimit(provider.rate_limit_rpm);
    setMessage(null);
    setError(null);
  }

  async function onSaveProvider(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setMessage(null);
    try {
      if (editingProviderId) {
        await updateProvider(editingProviderId, {
          name,
          base_url: baseUrl,
          api_key: providerType === "codex" ? undefined : (apiKey || undefined),
          model_name: modelName,
          is_default: isDefault,
          is_fallback: isFallback,
          rate_limit_rpm: rateLimit
        });
        setMessage("Provider updated.");
      } else {
        await createProvider({
          name,
          provider_type: providerType,
          base_url: baseUrl,
          api_key: providerType === "codex" ? undefined : (apiKey || undefined),
          model_name: modelName,
          is_default: isDefault,
          is_fallback: isFallback,
          rate_limit_rpm: rateLimit
        });
        setMessage("Provider saved.");
      }
      resetForm();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save provider");
    }
  }

  async function onSetDefault(provider: LLMProvider) {
    if (provider.is_default) {
      return;
    }

    setError(null);
    setMessage(null);
    setSettingDefaultProviderId(provider.id);
    try {
      await updateProvider(provider.id, { is_default: true });
      setMessage(`${provider.name} is now the default provider.`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to set default provider");
    } finally {
      setSettingDefaultProviderId(null);
    }
  }

  async function onTest(providerId: string) {
    setError(null);
    setMessage(null);
    try {
      const result = await testProvider(providerId);
      setMessage(result.message);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to test provider");
    }
  }

  async function onDelete(provider: LLMProvider) {
    if (provider.is_default) {
      return;
    }
    if (!window.confirm("Delete this AI provider? This action cannot be undone.")) {
      return;
    }

    setError(null);
    setMessage(null);
    setDeletingProviderId(provider.id);
    try {
      const result = await deleteProvider(provider.id);
      setMessage(result.message);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete provider");
    } finally {
      setDeletingProviderId(null);
    }
  }

  async function onConnectCodex() {
    setError(null);
    setMessage(null);
    try {
      const redirectUri =
        import.meta.env.VITE_CODEX_OAUTH_REDIRECT_URI ??
        `${window.location.origin}/auth/callback`;
      const oauth = await codexOAuthStart(redirectUri);
      window.location.href = oauth.auth_url;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start Codex OAuth");
    }
  }

  async function onDisconnectCodex() {
    setError(null);
    setMessage(null);
    try {
      const result = await disconnectCodexOAuth();
      setMessage(result.message);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to disconnect Codex OAuth");
    }
  }

  return (
    <main className="mx-auto max-w-6xl p-6">
      <header className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Tenant Settings / AI Models</h1>
        <Link className="text-sm text-accent underline" to="/">
          Back to dashboard
        </Link>
      </header>

      {error && <div className="mb-4 rounded bg-red-500/15 p-3 text-red-200">{error}</div>}
      {message && <div className="mb-4 rounded bg-emerald-500/15 p-3 text-emerald-200">{message}</div>}

      <section className="mb-4 rounded-lg bg-panel p-4">
        <h2 className="mb-3 text-lg font-semibold">Codex Login</h2>
        {codexAdminBlocked ? (
          <p className="text-sm text-slate-300">Only tenant admins can connect or disconnect Codex OAuth.</p>
        ) : (
          <>
            <p className="text-sm text-slate-300">
              Codex OAuth app credentials are managed at platform level. Use connect to authorize this tenant.
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <span className="rounded border border-slate-700 px-2 py-1 text-xs">
                {codexConnected ? `Connected${codexConnectedEmail ? ` as ${codexConnectedEmail}` : ""}` : "Disconnected"}
              </span>
              <button
                className="rounded border border-slate-700 px-3 py-2"
                onClick={onConnectCodex}
                type="button"
              >
                {codexConnected ? "Reconnect Codex" : "Connect Codex"}
              </button>
              <button
                className="rounded border border-red-500 px-3 py-2 text-red-300 disabled:opacity-50"
                disabled={!codexConnected}
                onClick={onDisconnectCodex}
                type="button"
              >
                Disconnect Codex
              </button>
            </div>
          </>
        )}
      </section>

      <section className="mb-4 rounded-lg bg-panel p-4">
        <h2 className="mb-3 text-lg font-semibold">{editingProviderId ? "Edit Provider" : "Add Provider"}</h2>
        <form className="grid gap-2 md:grid-cols-2" onSubmit={onSaveProvider}>
          <input
            className="rounded border border-slate-700 bg-slate-900 p-2"
            onChange={(e) => setName(e.target.value)}
            placeholder="Provider name"
            required
            value={name}
          />
          <select
            className="rounded border border-slate-700 bg-slate-900 p-2"
            disabled={Boolean(editingProviderId)}
            onChange={(e) => {
              const nextType = e.target.value as "openai" | "vllm" | "ollama" | "other" | "codex";
              setProviderType(nextType);
              if (nextType === "codex") {
                setApiKey("");
              }
            }}
            value={providerType}
          >
            <option value="openai">OpenAI</option>
            <option value="codex">Codex (Login)</option>
            <option value="vllm">Local vLLM (OpenAI-compatible)</option>
            <option value="ollama">Ollama</option>
            <option value="other">Other (OpenAI-compatible)</option>
          </select>

          <input
            className="rounded border border-slate-700 bg-slate-900 p-2"
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="Base URL"
            required
            value={baseUrl}
          />
          <input
            className="rounded border border-slate-700 bg-slate-900 p-2"
            onChange={(e) => setModelName(e.target.value)}
            placeholder="Model name"
            required
            value={modelName}
          />

          {providerType !== "codex" ? (
            <input
              className="rounded border border-slate-700 bg-slate-900 p-2"
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="API key (optional for local providers)"
              value={apiKey}
            />
          ) : (
            <div className="rounded border border-slate-700 bg-slate-900 p-2 text-sm text-slate-300">
              Codex providers use tenant OAuth login. Connect Codex above instead of API key.
            </div>
          )}
          <input
            className="rounded border border-slate-700 bg-slate-900 p-2"
            max={10000}
            min={1}
            onChange={(e) => setRateLimit(Number(e.target.value))}
            type="number"
            value={rateLimit}
          />

          <label className="flex items-center gap-2">
            <input checked={isDefault} onChange={(e) => setIsDefault(e.target.checked)} type="checkbox" />
            Default provider
          </label>
          <label className="flex items-center gap-2">
            <input checked={isFallback} onChange={(e) => setIsFallback(e.target.checked)} type="checkbox" />
            Fallback provider
          </label>

          <div className="flex items-center gap-2">
            <button className="rounded bg-accent px-4 py-2 font-semibold text-slate-950" type="submit">
              {editingProviderId ? "Update Provider" : "Save Provider"}
            </button>
            {editingProviderId && (
              <button
                className="rounded border border-slate-700 px-4 py-2"
                onClick={resetForm}
                type="button"
              >
                Cancel Edit
              </button>
            )}
          </div>
        </form>
      </section>

      <section className="rounded-lg bg-panel p-4">
        <h2 className="mb-3 text-lg font-semibold">Configured Providers</h2>
        <div className="space-y-2">
          {providers.map((provider) => (
            <div
              key={provider.id}
              className="rounded border border-slate-800 p-3"
              data-testid={`provider-row-${provider.id}`}
            >
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="font-medium">{provider.name}</p>
                  <p className="text-sm text-slate-300">
                    {provider.provider_type} / {provider.model_name} / {provider.base_url}
                  </p>
                  <p className="text-xs text-slate-400">
                    {provider.is_default ? "default" : ""}
                    {provider.is_fallback ? " fallback" : ""}
                  </p>
                  {provider.provider_type === "codex" && !provider.oauth_connected && (
                    <p className="mt-1 text-xs text-amber-300">Codex login is not connected for this tenant.</p>
                  )}
                  {provider.is_default && (
                    <p className="mt-1 text-xs text-amber-300">
                      Default provider: make another provider default before deleting.
                    </p>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <button
                    className="rounded border border-slate-700 px-3 py-2"
                    data-testid={`provider-set-default-${provider.id}`}
                    disabled={provider.is_default || settingDefaultProviderId === provider.id}
                    onClick={() => onSetDefault(provider)}
                    type="button"
                  >
                    {settingDefaultProviderId === provider.id ? "Setting..." : "Set Default"}
                  </button>
                  <button
                    className="rounded border border-slate-700 px-3 py-2"
                    data-testid={`provider-edit-${provider.id}`}
                    onClick={() => onEdit(provider)}
                    type="button"
                  >
                    Edit
                  </button>
                  <button
                    className="rounded border border-slate-700 px-3 py-2"
                    data-testid={`provider-test-${provider.id}`}
                    onClick={() => onTest(provider.id)}
                    type="button"
                  >
                    Test
                  </button>
                  <button
                    className="rounded border border-red-500 px-3 py-2 text-red-300 disabled:opacity-50"
                    data-testid={`provider-delete-${provider.id}`}
                    disabled={provider.is_default || deletingProviderId === provider.id}
                    onClick={() => onDelete(provider)}
                    type="button"
                  >
                    {deletingProviderId === provider.id ? "Deleting..." : "Delete"}
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}
