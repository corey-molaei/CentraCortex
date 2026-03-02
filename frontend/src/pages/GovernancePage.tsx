import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  approveQueueItem,
  exportAuditLogsCsv,
  listApprovalQueue,
  listAuditLogs,
  rejectQueueItem
} from "../api/governance";
import type { ApprovalQueueItem, AuditLogItem } from "../types/governance";

export function GovernancePage() {
  const [auditLogs, setAuditLogs] = useState<AuditLogItem[]>([]);
  const [approvalQueue, setApprovalQueue] = useState<ApprovalQueueItem[]>([]);

  const [userIdFilter, setUserIdFilter] = useState("");
  const [eventTypeFilter, setEventTypeFilter] = useState("");
  const [toolFilter, setToolFilter] = useState("");
  const [startAtFilter, setStartAtFilter] = useState("");
  const [endAtFilter, setEndAtFilter] = useState("");

  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const [logs, queue] = await Promise.all([
        listAuditLogs({
          user_id: userIdFilter || undefined,
          event_type: eventTypeFilter || undefined,
          tool: toolFilter || undefined,
          start_at: startAtFilter ? new Date(startAtFilter).toISOString() : undefined,
          end_at: endAtFilter ? new Date(endAtFilter).toISOString() : undefined,
          limit: 100,
          offset: 0
        }),
        listApprovalQueue("pending")
      ]);
      setAuditLogs(logs);
      setApprovalQueue(queue);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load governance data");
    }
  }, [userIdFilter, eventTypeFilter, toolFilter, startAtFilter, endAtFilter]);

  useEffect(() => {
    load().catch((err) => setError(err instanceof Error ? err.message : "Failed to load governance data"));
  }, [load]);

  async function onFilterSubmit(e: FormEvent) {
    e.preventDefault();
    await load();
  }

  async function onExportCsv() {
    try {
      const csv = await exportAuditLogsCsv({
        user_id: userIdFilter || undefined,
        event_type: eventTypeFilter || undefined,
        tool: toolFilter || undefined,
        start_at: startAtFilter ? new Date(startAtFilter).toISOString() : undefined,
        end_at: endAtFilter ? new Date(endAtFilter).toISOString() : undefined,
        limit: 2000
      });

      const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "audit_logs.csv";
      anchor.click();
      URL.revokeObjectURL(url);
      setMessage("Audit log CSV exported.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "CSV export failed");
    }
  }

  async function onApprove(approvalId: string) {
    const note = window.prompt("Approval note (optional)") ?? undefined;
    try {
      await approveQueueItem(approvalId, note);
      setMessage("Approval accepted.");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to approve request");
    }
  }

  async function onReject(approvalId: string) {
    const note = window.prompt("Rejection note (optional)") ?? undefined;
    try {
      await rejectQueueItem(approvalId, note);
      setMessage("Approval rejected.");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reject request");
    }
  }

  return (
    <main className="mx-auto max-w-7xl p-6">
      <header className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Governance & Audit</h1>
          <p className="text-sm text-slate-300">Monitor audit events, process approvals, and export compliance logs.</p>
        </div>
        <div className="flex gap-3 text-sm">
          <Link className="rounded border border-slate-700 px-3 py-2 hover:bg-slate-800" to="/">
            Back
          </Link>
        </div>
      </header>

      {error && <div className="mb-3 rounded bg-red-500/15 p-3 text-red-200">{error}</div>}
      {message && <div className="mb-3 rounded bg-emerald-500/15 p-3 text-emerald-200">{message}</div>}

      <section className="mb-5 rounded-lg bg-panel p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Audit Log Filters</h2>
          <button className="rounded border border-slate-700 px-3 py-2 text-sm hover:bg-slate-800" onClick={onExportCsv}>
            Export CSV
          </button>
        </div>

        <form className="grid gap-3 md:grid-cols-5" onSubmit={onFilterSubmit}>
          <input
            className="rounded border border-slate-700 bg-slate-900 p-2 text-sm"
            placeholder="User ID"
            value={userIdFilter}
            onChange={(e) => setUserIdFilter(e.target.value)}
          />
          <input
            className="rounded border border-slate-700 bg-slate-900 p-2 text-sm"
            placeholder="Event type"
            value={eventTypeFilter}
            onChange={(e) => setEventTypeFilter(e.target.value)}
          />
          <input
            className="rounded border border-slate-700 bg-slate-900 p-2 text-sm"
            placeholder="Tool name"
            value={toolFilter}
            onChange={(e) => setToolFilter(e.target.value)}
          />
          <input
            className="rounded border border-slate-700 bg-slate-900 p-2 text-sm"
            type="datetime-local"
            value={startAtFilter}
            onChange={(e) => setStartAtFilter(e.target.value)}
          />
          <input
            className="rounded border border-slate-700 bg-slate-900 p-2 text-sm"
            type="datetime-local"
            value={endAtFilter}
            onChange={(e) => setEndAtFilter(e.target.value)}
          />
          <div className="md:col-span-5">
            <button className="rounded border border-slate-700 px-4 py-2 hover:bg-slate-800">Apply Filters</button>
          </div>
        </form>
      </section>

      <section className="mb-5 rounded-lg bg-panel p-4">
        <h2 className="mb-3 text-lg font-semibold">Approval Queue</h2>
        <div className="space-y-2">
          {approvalQueue.map((item) => (
            <article className="rounded border border-slate-700 p-3" key={item.id}>
              <div className="mb-1 flex items-center justify-between">
                <strong>{item.tool_name}</strong>
                <span className="text-xs uppercase text-slate-300">{item.status}</span>
              </div>
              <p className="text-xs text-slate-400">Run: {item.run_id}</p>
              <pre className="mt-2 overflow-x-auto rounded bg-slate-950 p-2 text-xs text-slate-300">{JSON.stringify(item.request_payload_json, null, 2)}</pre>
              <div className="mt-2 flex gap-2">
                <button className="rounded border border-emerald-700 px-2 py-1 text-xs hover:bg-emerald-900/30" onClick={() => onApprove(item.id)}>
                  Approve
                </button>
                <button className="rounded border border-red-700 px-2 py-1 text-xs hover:bg-red-900/30" onClick={() => onReject(item.id)}>
                  Reject
                </button>
              </div>
            </article>
          ))}
          {approvalQueue.length === 0 && <p className="text-sm text-slate-400">No pending approvals.</p>}
        </div>
      </section>

      <section className="rounded-lg bg-panel p-4">
        <h2 className="mb-3 text-lg font-semibold">Audit Events</h2>
        <div className="overflow-x-auto">
          <table className="min-w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-slate-700 text-left text-slate-300">
                <th className="py-2 pr-3">Time</th>
                <th className="py-2 pr-3">Event</th>
                <th className="py-2 pr-3">Action</th>
                <th className="py-2 pr-3">User</th>
                <th className="py-2 pr-3">Resource</th>
                <th className="py-2 pr-3">Request ID</th>
              </tr>
            </thead>
            <tbody>
              {auditLogs.map((log) => (
                <tr className="border-b border-slate-800" key={log.id}>
                  <td className="py-2 pr-3 text-slate-400">{new Date(log.created_at).toLocaleString()}</td>
                  <td className="py-2 pr-3">{log.event_type}</td>
                  <td className="py-2 pr-3 text-slate-300">{log.action}</td>
                  <td className="py-2 pr-3 text-slate-400">{log.user_id ?? "-"}</td>
                  <td className="py-2 pr-3 text-slate-400">
                    {log.resource_type}:{log.resource_id ?? "-"}
                  </td>
                  <td className="py-2 pr-3 font-mono text-xs text-slate-500">{log.request_id ?? "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {auditLogs.length === 0 && <p className="pt-3 text-sm text-slate-400">No audit entries for current filter.</p>}
        </div>
      </section>
    </main>
  );
}
