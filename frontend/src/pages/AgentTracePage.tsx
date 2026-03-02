import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { approveRunTool, getAgentRun, rejectRunTool } from "../api/agents";
import type { AgentRunDetail } from "../types/agents";

export function AgentTracePage() {
  const { runId } = useParams();
  const [detail, setDetail] = useState<AgentRunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!runId) {
      return;
    }

    try {
      setError(null);
      const data = await getAgentRun(runId);
      setDetail(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load trace");
    }
  }, [runId]);

  useEffect(() => {
    load();
  }, [load]);

  async function onApprove(approvalId: string) {
    const note = window.prompt("Approval note (optional):") ?? undefined;
    try {
      await approveRunTool(approvalId, note);
      setMessage("Approval accepted and run resumed.");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Approval failed");
    }
  }

  async function onReject(approvalId: string) {
    const note = window.prompt("Rejection note (optional):") ?? undefined;
    try {
      await rejectRunTool(approvalId, note);
      setMessage("Approval rejected.");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Rejection failed");
    }
  }

  return (
    <main className="mx-auto max-w-6xl p-6">
      <header className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Execution Trace</h1>
          <p className="text-sm text-slate-300">Inspect router decisions, tool calls, approvals, and outcomes.</p>
        </div>
        <div className="flex gap-3 text-sm">
          <Link className="rounded border border-slate-700 px-3 py-2 hover:bg-slate-800" to="/agents/run">
            Back to Runs
          </Link>
          <Link className="rounded border border-slate-700 px-3 py-2 hover:bg-slate-800" to="/">
            Back
          </Link>
        </div>
      </header>

      {error && <div className="mb-3 rounded bg-red-500/15 p-3 text-red-200">{error}</div>}
      {message && <div className="mb-3 rounded bg-emerald-500/15 p-3 text-emerald-200">{message}</div>}

      {detail && (
        <>
          <section className="mb-5 rounded-lg bg-panel p-4">
            <h2 className="mb-2 text-lg font-semibold">Run Summary</h2>
            <p className="text-sm text-slate-300">Run: {detail.run.id}</p>
            <p className="text-sm text-slate-300">Status: {detail.run.status}</p>
            <p className="text-sm text-slate-300">Routed Agent: {detail.run.routed_agent ?? "n/a"}</p>
            <p className="text-sm text-slate-300">Output: {detail.run.output_text ?? "pending"}</p>
            {detail.run.error_message && <p className="text-sm text-red-300">Error: {detail.run.error_message}</p>}
          </section>

          <section className="mb-5 rounded-lg bg-panel p-4">
            <h2 className="mb-2 text-lg font-semibold">Approvals</h2>
            <div className="space-y-2">
              {detail.approvals.map((approval) => (
                <article className="rounded border border-slate-700 p-3" key={approval.id}>
                  <div className="mb-1 flex items-center justify-between">
                    <strong>{approval.tool_name}</strong>
                    <span className="text-xs uppercase text-slate-300">{approval.status}</span>
                  </div>
                  <pre className="overflow-x-auto rounded bg-slate-950 p-2 text-xs text-slate-300">{JSON.stringify(approval.request_payload_json, null, 2)}</pre>
                  {approval.status === "pending" && (
                    <div className="mt-2 flex gap-2">
                      <button className="rounded border border-emerald-700 px-3 py-1 text-sm hover:bg-emerald-900/30" onClick={() => onApprove(approval.id)}>
                        Approve
                      </button>
                      <button className="rounded border border-red-700 px-3 py-1 text-sm hover:bg-red-900/30" onClick={() => onReject(approval.id)}>
                        Reject
                      </button>
                    </div>
                  )}
                </article>
              ))}
              {detail.approvals.length === 0 && <p className="text-sm text-slate-400">No approvals for this run.</p>}
            </div>
          </section>

          <section className="rounded-lg bg-panel p-4">
            <h2 className="mb-2 text-lg font-semibold">Trace Steps</h2>
            <div className="space-y-2">
              {detail.traces.map((trace) => (
                <article className="rounded border border-slate-700 p-3" key={trace.id}>
                  <div className="mb-1 flex items-center justify-between">
                    <span className="text-sm font-semibold">
                      #{trace.step_order} {trace.agent_name} / {trace.step_type}
                    </span>
                    <span className="text-xs uppercase text-slate-300">{trace.status}</span>
                  </div>
                  {trace.reasoning_redacted && <p className="text-xs text-slate-400">{trace.reasoning_redacted}</p>}
                  {trace.tool_name && <p className="text-xs text-slate-300">Tool: {trace.tool_name}</p>}
                  <details className="mt-2">
                    <summary className="cursor-pointer text-xs text-accent">View input/output JSON</summary>
                    <div className="grid gap-2 pt-2 md:grid-cols-2">
                      <pre className="overflow-x-auto rounded bg-slate-950 p-2 text-xs text-slate-300">{JSON.stringify(trace.input_json, null, 2)}</pre>
                      <pre className="overflow-x-auto rounded bg-slate-950 p-2 text-xs text-slate-300">{JSON.stringify(trace.output_json, null, 2)}</pre>
                    </div>
                  </details>
                </article>
              ))}
              {detail.traces.length === 0 && <p className="text-sm text-slate-400">No traces recorded.</p>}
            </div>
          </section>
        </>
      )}
    </main>
  );
}
