import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { connectorStatus, getConnectorConfig, putConnectorConfig, syncConnector, testConnector } from "../../api/connectors";
import { ConnectorRuns } from "../../components/connectors/ConnectorRuns";
import type { ConnectorStatus, SyncRun } from "../../types/connectors";

export function SharePointConnectorPage() {
  const [azureTenantId, setAzureTenantId] = useState("");
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [siteIds, setSiteIds] = useState("");
  const [driveIds, setDriveIds] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [status, setStatus] = useState<ConnectorStatus | null>(null);
  const [runs, setRuns] = useState<SyncRun[]>([]);
  const [message, setMessage] = useState<string | null>(null);

  async function load() {
    const config = await getConnectorConfig<{ azure_tenant_id: string; client_id: string; site_ids: string[]; drive_ids: string[]; status: ConnectorStatus }>("sharepoint");
    if (config) {
      setAzureTenantId(config.azure_tenant_id);
      setClientId(config.client_id);
      setSiteIds(config.site_ids.join(","));
      setDriveIds(config.drive_ids.join(","));
      setStatus(config.status);
    }
    setRuns(await connectorStatus("sharepoint"));
  }

  useEffect(() => {
    load().catch((err) => setMessage(err instanceof Error ? err.message : "Failed loading sharepoint connector"));
  }, []);

  async function onSave(e: FormEvent) {
    e.preventDefault();
    await putConnectorConfig("sharepoint", {
      azure_tenant_id: azureTenantId,
      client_id: clientId,
      client_secret: clientSecret,
      site_ids: siteIds.split(",").map((x) => x.trim()).filter(Boolean),
      drive_ids: driveIds.split(",").map((x) => x.trim()).filter(Boolean),
      enabled
    });
    setClientSecret("");
    setMessage("SharePoint config saved.");
    await load();
  }

  return (
    <main className="mx-auto max-w-6xl p-6">
      <header className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">SharePoint/Graph Connector Wizard</h1>
        <Link className="text-sm text-accent underline" to="/connectors">Back to connectors</Link>
      </header>
      {message && <div className="mb-4 rounded bg-slate-800 p-3 text-slate-100">{message}</div>}
      <div className="grid gap-4 md:grid-cols-2">
        <section className="rounded-lg bg-panel p-4">
          <form className="space-y-2" onSubmit={onSave}>
            <h2 className="text-lg font-semibold">Step 1: OAuth App Credentials</h2>
            <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" value={azureTenantId} onChange={(e) => setAzureTenantId(e.target.value)} placeholder="Azure Tenant ID" />
            <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" value={clientId} onChange={(e) => setClientId(e.target.value)} placeholder="Client ID" />
            <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" value={clientSecret} onChange={(e) => setClientSecret(e.target.value)} placeholder="Client Secret" />
            <h3 className="text-sm font-semibold">Step 2: Site and Drive Selection</h3>
            <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" value={siteIds} onChange={(e) => setSiteIds(e.target.value)} placeholder="Site IDs comma-separated" />
            <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" value={driveIds} onChange={(e) => setDriveIds(e.target.value)} placeholder="Drive IDs comma-separated" />
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> Enabled</label>
            <div className="flex gap-2">
              <button className="rounded bg-accent px-4 py-2 font-semibold text-slate-950">Save</button>
              <button className="rounded border border-slate-700 px-4 py-2" type="button" onClick={async () => setMessage((await testConnector("sharepoint")).message)}>Test Connection</button>
              <button className="rounded border border-slate-700 px-4 py-2" type="button" onClick={async () => setMessage((await syncConnector("sharepoint")).message)}>Run Sync Now</button>
            </div>
          </form>
        </section>
        <ConnectorRuns status={status} runs={runs} />
      </div>
    </main>
  );
}
