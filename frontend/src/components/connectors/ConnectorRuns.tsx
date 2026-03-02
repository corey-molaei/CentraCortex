import type { ConnectorStatus, SyncRun } from "../../types/connectors";

export function ConnectorRuns({ status, runs }: { status: ConnectorStatus | null; runs: SyncRun[] }) {
  return (
    <section className="rounded-lg bg-panel p-4">
      <h2 className="mb-2 text-lg font-semibold">Sync Status</h2>
      {status ? (
        <div className="mb-3 text-sm text-slate-300">
          <p>Enabled: {status.enabled ? "yes" : "no"}</p>
          <p>Last sync: {status.last_sync_at ?? "never"}</p>
          <p>Last items synced: {status.last_items_synced}</p>
          <p>Last error: {status.last_error ?? "none"}</p>
        </div>
      ) : (
        <p className="mb-3 text-sm text-slate-300">No connector configured yet.</p>
      )}

      <div className="space-y-2">
        {runs.map((run) => (
          <div key={run.id} className="rounded border border-slate-800 p-2 text-sm">
            <p>
              {run.status} | items: {run.items_synced}
            </p>
            <p className="text-slate-300">{new Date(run.started_at).toLocaleString()}</p>
            {run.error_message && <p className="text-red-300">{run.error_message}</p>}
          </div>
        ))}
      </div>
    </section>
  );
}
