import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { connectorStatus, getConnectorConfig, putConnectorConfig, syncConnector, testConnector } from "../../api/connectors";
import { ConnectorRuns } from "../../components/connectors/ConnectorRuns";
import type { ConnectorStatus, SyncRun } from "../../types/connectors";

export function DBConnectorPage() {
  const [connectionUri, setConnectionUri] = useState("");
  const [tableAllowlist, setTableAllowlist] = useState("public.events");
  const [enabled, setEnabled] = useState(true);
  const [status, setStatus] = useState<ConnectorStatus | null>(null);
  const [runs, setRuns] = useState<SyncRun[]>([]);
  const [message, setMessage] = useState<string | null>(null);

  async function load() {
    const config = await getConnectorConfig<{ table_allowlist: string[]; status: ConnectorStatus }>("db");
    if (config) {
      setTableAllowlist(config.table_allowlist.join(","));
      setStatus(config.status);
    }
    setRuns(await connectorStatus("db"));
  }

  useEffect(() => {
    load().catch((err) => setMessage(err instanceof Error ? err.message : "Failed loading DB connector"));
  }, []);

  async function onSave(e: FormEvent) {
    e.preventDefault();
    await putConnectorConfig("db", {
      connection_uri: connectionUri,
      table_allowlist: tableAllowlist.split(",").map((x) => x.trim()).filter(Boolean),
      enabled
    });
    setConnectionUri("");
    setMessage("DB connector configuration saved.");
    await load();
  }

  return (
    <main className="mx-auto max-w-6xl p-6">
      <header className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">DB Read-Only Connector Wizard</h1>
        <Link className="text-sm text-accent underline" to="/connectors">Back to connectors</Link>
      </header>
      {message && <div className="mb-4 rounded bg-slate-800 p-3 text-slate-100">{message}</div>}
      <div className="grid gap-4 md:grid-cols-2">
        <section className="rounded-lg bg-panel p-4">
          <form className="space-y-2" onSubmit={onSave}>
            <h2 className="text-lg font-semibold">Step 1: Credentials</h2>
            <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" value={connectionUri} onChange={(e) => setConnectionUri(e.target.value)} placeholder="postgresql://readonly:***@host:5432/db" />
            <h3 className="text-sm font-semibold">Step 2: Table Allowlist</h3>
            <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" value={tableAllowlist} onChange={(e) => setTableAllowlist(e.target.value)} placeholder="public.events,public.orders" />
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> Enabled</label>
            <div className="flex gap-2">
              <button className="rounded bg-accent px-4 py-2 font-semibold text-slate-950">Save</button>
              <button className="rounded border border-slate-700 px-4 py-2" type="button" onClick={async () => setMessage((await testConnector("db")).message)}>Test Connection</button>
              <button className="rounded border border-slate-700 px-4 py-2" type="button" onClick={async () => setMessage((await syncConnector("db")).message)}>Run Sync Now</button>
            </div>
          </form>
        </section>
        <ConnectorRuns status={status} runs={runs} />
      </div>
    </main>
  );
}
