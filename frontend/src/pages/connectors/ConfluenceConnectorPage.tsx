import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { connectorStatus, getConnectorConfig, putConnectorConfig, syncConnector, testConnector } from "../../api/connectors";
import { ConnectorRuns } from "../../components/connectors/ConnectorRuns";
import type { ConnectorStatus, SyncRun } from "../../types/connectors";

export function ConfluenceConnectorPage() {
  const [baseUrl, setBaseUrl] = useState("");
  const [email, setEmail] = useState("");
  const [apiToken, setApiToken] = useState("");
  const [spaceKeys, setSpaceKeys] = useState("ENG,OPS");
  const [enabled, setEnabled] = useState(true);
  const [status, setStatus] = useState<ConnectorStatus | null>(null);
  const [runs, setRuns] = useState<SyncRun[]>([]);
  const [message, setMessage] = useState<string | null>(null);

  async function load() {
    const config = await getConnectorConfig<{ base_url: string; email: string; space_keys: string[]; status: ConnectorStatus }>("confluence");
    if (config) {
      setBaseUrl(config.base_url);
      setEmail(config.email);
      setSpaceKeys(config.space_keys.join(","));
      setStatus(config.status);
    }
    setRuns(await connectorStatus("confluence"));
  }

  useEffect(() => {
    load().catch((err) => setMessage(err instanceof Error ? err.message : "Failed loading confluence connector"));
  }, []);

  async function onSave(e: FormEvent) {
    e.preventDefault();
    await putConnectorConfig("confluence", {
      base_url: baseUrl,
      email,
      api_token: apiToken,
      space_keys: spaceKeys.split(",").map((x) => x.trim()).filter(Boolean),
      enabled
    });
    setApiToken("");
    setMessage("Confluence configuration saved.");
    await load();
  }

  return (
    <main className="mx-auto max-w-6xl p-6">
      <header className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Confluence Connector Wizard</h1>
        <Link className="text-sm text-accent underline" to="/connectors">Back to connectors</Link>
      </header>
      {message && <div className="mb-4 rounded bg-slate-800 p-3 text-slate-100">{message}</div>}
      <div className="grid gap-4 md:grid-cols-2">
        <section className="rounded-lg bg-panel p-4">
          <form className="space-y-2" onSubmit={onSave}>
            <h2 className="text-lg font-semibold">Step 1: Credentials</h2>
            <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="Confluence base URL" />
            <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="User email" />
            <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" value={apiToken} onChange={(e) => setApiToken(e.target.value)} placeholder="API token" />
            <h3 className="text-sm font-semibold">Step 2: Space Selection</h3>
            <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" value={spaceKeys} onChange={(e) => setSpaceKeys(e.target.value)} placeholder="ENG,OPS" />
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> Enabled</label>
            <div className="flex gap-2">
              <button className="rounded bg-accent px-4 py-2 font-semibold text-slate-950">Save</button>
              <button className="rounded border border-slate-700 px-4 py-2" type="button" onClick={async () => setMessage((await testConnector("confluence")).message)}>Test Connection</button>
              <button className="rounded border border-slate-700 px-4 py-2" type="button" onClick={async () => setMessage((await syncConnector("confluence")).message)}>Run Sync Now</button>
            </div>
          </form>
        </section>
        <ConnectorRuns status={status} runs={runs} />
      </div>
    </main>
  );
}
