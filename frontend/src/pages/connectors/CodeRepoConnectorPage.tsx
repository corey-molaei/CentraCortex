import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { connectorStatus, getConnectorConfig, putConnectorConfig, syncConnector, testConnector } from "../../api/connectors";
import { ConnectorRuns } from "../../components/connectors/ConnectorRuns";
import type { ConnectorStatus, SyncRun } from "../../types/connectors";

export function CodeRepoConnectorPage() {
  const [provider, setProvider] = useState<"github" | "gitlab">("github");
  const [baseUrl, setBaseUrl] = useState("https://api.github.com");
  const [token, setToken] = useState("");
  const [repositories, setRepositories] = useState("owner/repo");
  const [enabled, setEnabled] = useState(true);
  const [status, setStatus] = useState<ConnectorStatus | null>(null);
  const [runs, setRuns] = useState<SyncRun[]>([]);
  const [message, setMessage] = useState<string | null>(null);

  async function load() {
    const config = await getConnectorConfig<{ provider: "github" | "gitlab"; base_url: string; repositories: string[]; status: ConnectorStatus }>("code-repo");
    if (config) {
      setProvider(config.provider);
      setBaseUrl(config.base_url);
      setRepositories(config.repositories.join(","));
      setStatus(config.status);
    }
    setRuns(await connectorStatus("code-repo"));
  }

  useEffect(() => {
    load().catch((err) => setMessage(err instanceof Error ? err.message : "Failed loading code repo connector"));
  }, []);

  async function onSave(e: FormEvent) {
    e.preventDefault();
    await putConnectorConfig("code-repo", {
      provider,
      base_url: baseUrl,
      token,
      repositories: repositories.split(",").map((x) => x.trim()).filter(Boolean),
      include_readme: true,
      include_issues: true,
      include_prs: true,
      include_wiki: true,
      enabled
    });
    setToken("");
    setMessage("Code repo config saved.");
    await load();
  }

  return (
    <main className="mx-auto max-w-6xl p-6">
      <header className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">GitHub/GitLab Connector Wizard</h1>
        <Link className="text-sm text-accent underline" to="/connectors">Back to connectors</Link>
      </header>
      {message && <div className="mb-4 rounded bg-slate-800 p-3 text-slate-100">{message}</div>}
      <div className="grid gap-4 md:grid-cols-2">
        <section className="rounded-lg bg-panel p-4">
          <form className="space-y-2" onSubmit={onSave}>
            <h2 className="text-lg font-semibold">Step 1: Credentials</h2>
            <select className="w-full rounded border border-slate-700 bg-slate-900 p-2" value={provider} onChange={(e) => setProvider(e.target.value as "github" | "gitlab")}>
              <option value="github">GitHub</option>
              <option value="gitlab">GitLab</option>
            </select>
            <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="Base API URL" />
            <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" value={token} onChange={(e) => setToken(e.target.value)} placeholder="PAT / Access Token" />
            <h3 className="text-sm font-semibold">Step 2: Repository Selection</h3>
            <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" value={repositories} onChange={(e) => setRepositories(e.target.value)} placeholder="owner/repo,owner/repo2" />
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> Enabled</label>
            <div className="flex gap-2">
              <button className="rounded bg-accent px-4 py-2 font-semibold text-slate-950">Save</button>
              <button className="rounded border border-slate-700 px-4 py-2" type="button" onClick={async () => setMessage((await testConnector("code-repo")).message)}>Test Connection</button>
              <button className="rounded border border-slate-700 px-4 py-2" type="button" onClick={async () => setMessage((await syncConnector("code-repo")).message)}>Run Sync Now</button>
            </div>
          </form>
        </section>
        <ConnectorRuns status={status} runs={runs} />
      </div>
    </main>
  );
}
