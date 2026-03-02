import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { connectorStatus, getConnectorConfig, putConnectorConfig, syncConnector, testConnector } from "../../api/connectors";
import { ConnectorRuns } from "../../components/connectors/ConnectorRuns";
import type { ConnectorStatus, SyncRun } from "../../types/connectors";

export function LogsConnectorPage() {
  const [folderPath, setFolderPath] = useState("/var/log");
  const [fileGlob, setFileGlob] = useState("*.log");
  const [parserType, setParserType] = useState("plain");
  const [enabled, setEnabled] = useState(true);
  const [status, setStatus] = useState<ConnectorStatus | null>(null);
  const [runs, setRuns] = useState<SyncRun[]>([]);
  const [message, setMessage] = useState<string | null>(null);

  async function load() {
    const config = await getConnectorConfig<{ folder_path: string; file_glob: string; parser_type: string; status: ConnectorStatus }>("logs");
    if (config) {
      setFolderPath(config.folder_path);
      setFileGlob(config.file_glob);
      setParserType(config.parser_type);
      setStatus(config.status);
    }
    setRuns(await connectorStatus("logs"));
  }

  useEffect(() => {
    load().catch((err) => setMessage(err instanceof Error ? err.message : "Failed loading logs connector"));
  }, []);

  async function onSave(e: FormEvent) {
    e.preventDefault();
    await putConnectorConfig("logs", {
      folder_path: folderPath,
      file_glob: fileGlob,
      parser_type: parserType,
      enabled
    });
    setMessage("Logs connector configuration saved.");
    await load();
  }

  return (
    <main className="mx-auto max-w-6xl p-6">
      <header className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Logs Connector Wizard</h1>
        <Link className="text-sm text-accent underline" to="/connectors">Back to connectors</Link>
      </header>
      {message && <div className="mb-4 rounded bg-slate-800 p-3 text-slate-100">{message}</div>}
      <div className="grid gap-4 md:grid-cols-2">
        <section className="rounded-lg bg-panel p-4">
          <form className="space-y-2" onSubmit={onSave}>
            <h2 className="text-lg font-semibold">Step 1: Source Path</h2>
            <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" value={folderPath} onChange={(e) => setFolderPath(e.target.value)} placeholder="/path/to/logs" />
            <h3 className="text-sm font-semibold">Step 2: Parsing Rules</h3>
            <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" value={fileGlob} onChange={(e) => setFileGlob(e.target.value)} placeholder="*.log" />
            <select className="w-full rounded border border-slate-700 bg-slate-900 p-2" value={parserType} onChange={(e) => setParserType(e.target.value)}>
              <option value="plain">Plain Text</option>
              <option value="jsonl">JSONL</option>
            </select>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> Enabled</label>
            <div className="flex gap-2">
              <button className="rounded bg-accent px-4 py-2 font-semibold text-slate-950">Save</button>
              <button className="rounded border border-slate-700 px-4 py-2" type="button" onClick={async () => setMessage((await testConnector("logs")).message)}>Test Connection</button>
              <button className="rounded border border-slate-700 px-4 py-2" type="button" onClick={async () => setMessage((await syncConnector("logs")).message)}>Run Sync Now</button>
            </div>
          </form>
        </section>
        <ConnectorRuns status={status} runs={runs} />
      </div>
    </main>
  );
}
