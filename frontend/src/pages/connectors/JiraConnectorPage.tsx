import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { connectorStatus, getConnectorConfig, putConnectorConfig, syncConnector, testConnector } from "../../api/connectors";
import { ConnectorRuns } from "../../components/connectors/ConnectorRuns";
import type { ConnectorStatus, SyncRun } from "../../types/connectors";

export function JiraConnectorPage() {
  const [baseUrl, setBaseUrl] = useState("");
  const [email, setEmail] = useState("");
  const [apiToken, setApiToken] = useState("");
  const [projectKeys, setProjectKeys] = useState("ENG");
  const [issueTypes, setIssueTypes] = useState("Bug,Task");
  const [enabled, setEnabled] = useState(true);
  const [status, setStatus] = useState<ConnectorStatus | null>(null);
  const [runs, setRuns] = useState<SyncRun[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    const config = await getConnectorConfig<{
      base_url: string;
      email: string;
      project_keys: string[];
      issue_types: string[];
      status: ConnectorStatus;
    }>("jira");
    if (config) {
      setBaseUrl(config.base_url);
      setEmail(config.email);
      setProjectKeys(config.project_keys.join(","));
      setIssueTypes(config.issue_types.join(","));
      setStatus(config.status);
    }
    setRuns(await connectorStatus("jira"));
  }

  useEffect(() => {
    load().catch((err) => setError(err instanceof Error ? err.message : "Failed loading Jira connector"));
  }, []);

  async function onSave(e: FormEvent) {
    e.preventDefault();
    try {
      await putConnectorConfig("jira", {
        base_url: baseUrl,
        email,
        api_token: apiToken,
        project_keys: projectKeys.split(",").map((x) => x.trim()).filter(Boolean),
        issue_types: issueTypes.split(",").map((x) => x.trim()).filter(Boolean),
        fields_mapping: {},
        enabled
      });
      setApiToken("");
      setMessage("Jira configuration saved.");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save Jira config");
    }
  }

  return (
    <main className="mx-auto max-w-6xl p-6">
      <header className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Jira Connector Wizard</h1>
        <Link className="text-sm text-accent underline" to="/connectors">Back to connectors</Link>
      </header>
      {error && <div className="mb-4 rounded bg-red-500/15 p-3 text-red-200">{error}</div>}
      {message && <div className="mb-4 rounded bg-emerald-500/15 p-3 text-emerald-200">{message}</div>}

      <div className="grid gap-4 md:grid-cols-2">
        <section className="rounded-lg bg-panel p-4">
          <h2 className="mb-2 text-lg font-semibold">Step 1: Credentials</h2>
          <form className="space-y-2" onSubmit={onSave}>
            <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" placeholder="Base URL" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} required />
            <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" placeholder="Jira Email" value={email} onChange={(e) => setEmail(e.target.value)} required />
            <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" placeholder="API Token" value={apiToken} onChange={(e) => setApiToken(e.target.value)} required />
            <h3 className="pt-2 text-sm font-semibold">Step 2: Project and Type Selection</h3>
            <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" placeholder="Projects (ENG,OPS)" value={projectKeys} onChange={(e) => setProjectKeys(e.target.value)} />
            <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" placeholder="Issue types (Bug,Task)" value={issueTypes} onChange={(e) => setIssueTypes(e.target.value)} />
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> Enabled
            </label>
            <div className="flex gap-2">
              <button className="rounded bg-accent px-4 py-2 font-semibold text-slate-950" type="submit">Save</button>
              <button className="rounded border border-slate-700 px-4 py-2" type="button" onClick={async () => setMessage((await testConnector("jira")).message)}>Test Connection</button>
              <button className="rounded border border-slate-700 px-4 py-2" type="button" onClick={async () => setMessage((await syncConnector("jira")).message)}>Run Sync Now</button>
            </div>
          </form>
        </section>
        <ConnectorRuns status={status} runs={runs} />
      </div>
    </main>
  );
}
