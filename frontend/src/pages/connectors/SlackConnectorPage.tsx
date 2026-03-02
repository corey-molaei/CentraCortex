import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { connectorStatus, getConnectorConfig, putConnectorConfig, slackOAuthCallback, slackOAuthStart, syncConnector, testConnector } from "../../api/connectors";
import { ConnectorRuns } from "../../components/connectors/ConnectorRuns";
import type { ConnectorStatus, SyncRun } from "../../types/connectors";

export function SlackConnectorPage() {
  const [workspaceName, setWorkspaceName] = useState("");
  const [botToken, setBotToken] = useState("");
  const [channelIds, setChannelIds] = useState("C12345678");
  const [enabled, setEnabled] = useState(true);
  const [status, setStatus] = useState<ConnectorStatus | null>(null);
  const [runs, setRuns] = useState<SyncRun[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const redirectUri = useMemo(() => `${window.location.origin}/connectors/slack`, []);

  async function load() {
    const config = await getConnectorConfig<{
      workspace_name: string | null;
      channel_ids: string[];
      status: ConnectorStatus;
    }>("slack");
    if (config) {
      setWorkspaceName(config.workspace_name ?? "");
      setChannelIds(config.channel_ids.join(","));
      setStatus(config.status);
    }
    setRuns(await connectorStatus("slack"));
  }

  useEffect(() => {
    load().catch((err) => setError(err instanceof Error ? err.message : "Failed loading Slack connector"));
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const state = params.get("state");
    if (!code || !state) {
      return;
    }

    slackOAuthCallback(code, state)
      .then((res) => {
        setMessage(res.message);
        window.history.replaceState({}, document.title, window.location.pathname);
        return load();
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Slack OAuth callback failed"));
  }, []);

  async function onSave(e: FormEvent) {
    e.preventDefault();
    try {
      await putConnectorConfig("slack", {
        workspace_name: workspaceName,
        bot_token: botToken || null,
        channel_ids: channelIds.split(",").map((x) => x.trim()).filter(Boolean),
        enabled
      });
      setBotToken("");
      setMessage("Slack configuration saved.");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save Slack config");
    }
  }

  return (
    <main className="mx-auto max-w-6xl p-6">
      <header className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Slack Connector Wizard</h1>
        <Link className="text-sm text-accent underline" to="/connectors">Back to connectors</Link>
      </header>
      {error && <div className="mb-4 rounded bg-red-500/15 p-3 text-red-200">{error}</div>}
      {message && <div className="mb-4 rounded bg-emerald-500/15 p-3 text-emerald-200">{message}</div>}

      <div className="grid gap-4 md:grid-cols-2">
        <section className="rounded-lg bg-panel p-4">
          <h2 className="mb-2 text-lg font-semibold">Step 1: OAuth or Token</h2>
          <form className="space-y-2" onSubmit={onSave}>
            <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" placeholder="Workspace Name" value={workspaceName} onChange={(e) => setWorkspaceName(e.target.value)} />
            <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" placeholder="Bot Token (optional if using OAuth)" value={botToken} onChange={(e) => setBotToken(e.target.value)} />
            <button
              className="rounded border border-slate-700 px-3 py-2"
              type="button"
              onClick={async () => {
                const oauth = await slackOAuthStart(redirectUri);
                window.location.href = oauth.auth_url;
              }}
            >
              Connect with Slack OAuth
            </button>
            <h3 className="pt-2 text-sm font-semibold">Step 2: Channel Selection</h3>
            <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" placeholder="Channel IDs comma-separated" value={channelIds} onChange={(e) => setChannelIds(e.target.value)} />
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> Enabled
            </label>
            <div className="flex gap-2">
              <button className="rounded bg-accent px-4 py-2 font-semibold text-slate-950" type="submit">Save</button>
              <button className="rounded border border-slate-700 px-4 py-2" type="button" onClick={async () => setMessage((await testConnector("slack")).message)}>Test Connection</button>
              <button className="rounded border border-slate-700 px-4 py-2" type="button" onClick={async () => setMessage((await syncConnector("slack")).message)}>Run Sync Now</button>
            </div>
          </form>
        </section>
        <ConnectorRuns status={status} runs={runs} />
      </div>
    </main>
  );
}
