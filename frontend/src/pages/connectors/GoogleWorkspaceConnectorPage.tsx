import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  completeWorkspaceGoogleOAuth,
  getWorkspaceGoogleConfig,
  startWorkspaceGoogleOAuth,
  syncWorkspaceGoogle,
  testWorkspaceGoogle,
  updateWorkspaceGoogleConfig,
  workspaceGoogleStatus
} from "../../api/workspace";
import type { WorkspaceGoogleIntegration } from "../../types/workspace";

export function GoogleWorkspaceConnectorPage() {
  const [config, setConfig] = useState<WorkspaceGoogleIntegration | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  const redirectUri = useMemo(() => `${window.location.origin}/connectors/google-workspace`, []);

  async function load() {
    const [cfg, status] = await Promise.all([getWorkspaceGoogleConfig(), workspaceGoogleStatus()]);
    setConfig(cfg);
    setStatusMessage(
      `Enabled=${status.enabled} | last sync=${status.last_sync_at ?? "-"} | items=${status.last_items_synced} | error=${status.last_error ?? "none"}`
    );
  }

  useEffect(() => {
    load().catch((err) => setError(err instanceof Error ? err.message : "Failed to load workspace Google integration"));
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const state = params.get("state");
    if (!code || !state) {
      return;
    }

    completeWorkspaceGoogleOAuth(code, state)
      .then((res) => {
        setMessage(res.message);
        window.history.replaceState({}, document.title, window.location.pathname);
        return load();
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Google OAuth callback failed"));
  }, []);

  async function saveConfig(event: FormEvent) {
    event.preventDefault();
    if (!config) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const updated = await updateWorkspaceGoogleConfig({
        enabled: config.enabled,
        gmail_enabled: config.gmail_enabled,
        gmail_labels: config.gmail_labels,
        calendar_enabled: config.calendar_enabled,
        calendar_ids: config.calendar_ids,
        drive_enabled: config.drive_enabled,
        drive_folder_ids: config.drive_folder_ids,
        sheets_enabled: config.sheets_enabled,
        sheets_targets: config.sheets_targets,
        crm_sheet_spreadsheet_id: config.crm_sheet_spreadsheet_id,
        crm_sheet_tab_name: config.crm_sheet_tab_name
      });
      setConfig(updated);
      setMessage("Workspace Google integration saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save workspace Google integration");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto max-w-5xl p-6">
      <header className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Google Workspace Integration</h1>
        <Link className="text-sm text-accent underline" to="/connectors">
          Back to connectors
        </Link>
      </header>

      {error && <div className="mb-3 rounded bg-red-500/15 p-3 text-red-200">{error}</div>}
      {message && <div className="mb-3 rounded bg-emerald-500/15 p-3 text-emerald-200">{message}</div>}
      {statusMessage && <div className="mb-3 rounded bg-white/10 p-3 text-sm text-slate-200">{statusMessage}</div>}

      {!config && <p className="text-sm text-slate-300">Loading configuration...</p>}

      {config && (
        <form className="space-y-4 rounded-lg bg-panel p-4" onSubmit={saveConfig}>
          <div className="flex flex-wrap items-center gap-4 text-sm">
            <label className="flex items-center gap-2">
              <input
                checked={config.enabled}
                onChange={(event) => setConfig((prev) => (prev ? { ...prev, enabled: event.target.checked } : prev))}
                type="checkbox"
              />
              Integration enabled
            </label>
            <label className="flex items-center gap-2">
              <input
                checked={config.gmail_enabled}
                onChange={(event) => setConfig((prev) => (prev ? { ...prev, gmail_enabled: event.target.checked } : prev))}
                type="checkbox"
              />
              Gmail
            </label>
            <label className="flex items-center gap-2">
              <input
                checked={config.calendar_enabled}
                onChange={(event) => setConfig((prev) => (prev ? { ...prev, calendar_enabled: event.target.checked } : prev))}
                type="checkbox"
              />
              Calendar
            </label>
            <label className="flex items-center gap-2">
              <input
                checked={config.drive_enabled}
                onChange={(event) => setConfig((prev) => (prev ? { ...prev, drive_enabled: event.target.checked } : prev))}
                type="checkbox"
              />
              Drive
            </label>
            <label className="flex items-center gap-2">
              <input
                checked={config.sheets_enabled}
                onChange={(event) => setConfig((prev) => (prev ? { ...prev, sheets_enabled: event.target.checked } : prev))}
                type="checkbox"
              />
              Sheets
            </label>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <label className="text-sm">
              <span className="mb-1 block text-slate-200">Gmail labels (comma separated)</span>
              <input
                className="w-full rounded border border-slate-700 bg-slate-900 p-2"
                onChange={(event) =>
                  setConfig((prev) =>
                    prev
                      ? {
                          ...prev,
                          gmail_labels: event.target.value
                            .split(",")
                            .map((value) => value.trim())
                            .filter(Boolean)
                        }
                      : prev
                  )
                }
                value={config.gmail_labels.join(",")}
              />
            </label>
            <label className="text-sm">
              <span className="mb-1 block text-slate-200">Calendar IDs (comma separated)</span>
              <input
                className="w-full rounded border border-slate-700 bg-slate-900 p-2"
                onChange={(event) =>
                  setConfig((prev) =>
                    prev
                      ? {
                          ...prev,
                          calendar_ids: event.target.value
                            .split(",")
                            .map((value) => value.trim())
                            .filter(Boolean)
                        }
                      : prev
                  )
                }
                value={config.calendar_ids.join(",")}
              />
            </label>
            <label className="text-sm">
              <span className="mb-1 block text-slate-200">Drive folder IDs (comma separated)</span>
              <input
                className="w-full rounded border border-slate-700 bg-slate-900 p-2"
                onChange={(event) =>
                  setConfig((prev) =>
                    prev
                      ? {
                          ...prev,
                          drive_folder_ids: event.target.value
                            .split(",")
                            .map((value) => value.trim())
                            .filter(Boolean)
                        }
                      : prev
                  )
                }
                value={config.drive_folder_ids.join(",")}
              />
            </label>
            <label className="text-sm">
              <span className="mb-1 block text-slate-200">CRM spreadsheet ID</span>
              <input
                className="w-full rounded border border-slate-700 bg-slate-900 p-2"
                onChange={(event) =>
                  setConfig((prev) => (prev ? { ...prev, crm_sheet_spreadsheet_id: event.target.value || null } : prev))
                }
                value={config.crm_sheet_spreadsheet_id ?? ""}
              />
            </label>
            <label className="text-sm">
              <span className="mb-1 block text-slate-200">CRM sheet tab</span>
              <input
                className="w-full rounded border border-slate-700 bg-slate-900 p-2"
                onChange={(event) =>
                  setConfig((prev) => (prev ? { ...prev, crm_sheet_tab_name: event.target.value || null } : prev))
                }
                value={config.crm_sheet_tab_name ?? ""}
              />
            </label>
            <label className="text-sm md:col-span-2">
              <span className="mb-1 block text-slate-200">Sheets targets JSON</span>
              <textarea
                className="min-h-24 w-full rounded border border-slate-700 bg-slate-900 p-2 font-mono text-xs"
                onChange={(event) => {
                  try {
                    const value = JSON.parse(event.target.value) as Array<Record<string, unknown>>;
                    setConfig((prev) => (prev ? { ...prev, sheets_targets: Array.isArray(value) ? value : [] } : prev));
                    setError(null);
                  } catch {
                    setError("Sheets targets must be valid JSON array");
                  }
                }}
                value={JSON.stringify(config.sheets_targets, null, 2)}
              />
            </label>
          </div>

          <div className="flex flex-wrap gap-2">
            <button className="rounded bg-accent px-4 py-2 font-semibold text-slate-950" disabled={busy} type="submit">
              {busy ? "Saving..." : "Save"}
            </button>
            <button
              className="rounded border border-slate-700 px-4 py-2"
              onClick={() => {
                setError(null);
                startWorkspaceGoogleOAuth(redirectUri)
                  .then((res) => {
                    window.location.href = res.auth_url;
                  })
                  .catch((err) => setError(err instanceof Error ? err.message : "Failed to start OAuth"));
              }}
              type="button"
            >
              {config.is_oauth_connected ? "Reconnect" : "Connect"}
            </button>
            <button
              className="rounded border border-slate-700 px-4 py-2"
              onClick={() => {
                setError(null);
                testWorkspaceGoogle()
                  .then((res) => setMessage(res.message))
                  .catch((err) => setError(err instanceof Error ? err.message : "Google test failed"));
              }}
              type="button"
            >
              Test
            </button>
            <button
              className="rounded border border-slate-700 px-4 py-2"
              onClick={() => {
                setError(null);
                syncWorkspaceGoogle()
                  .then((res) => setMessage(res.message))
                  .catch((err) => setError(err instanceof Error ? err.message : "Google sync failed"));
              }}
              type="button"
            >
              Sync now
            </button>
          </div>

          <p className="text-xs text-slate-400">
            Connected account: {config.google_account_email ?? "not connected"} | OAuth connected: {config.is_oauth_connected ? "yes" : "no"}
          </p>
        </form>
      )}
    </main>
  );
}
