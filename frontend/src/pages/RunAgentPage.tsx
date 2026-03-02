import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listAgentRuns, listAgents, runAgent } from "../api/agents";
import type { AgentDefinition, AgentRun } from "../types/agents";

export function RunAgentPage() {
  const [agents, setAgents] = useState<AgentDefinition[]>([]);
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [agentId, setAgentId] = useState("");
  const [inputText, setInputText] = useState("Find the latest ops runbook steps for database failover.");
  const [toolInputsJson, setToolInputsJson] = useState('{"search_knowledge": {"query": "database failover runbook", "limit": 5}}');
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const [agentList, runList] = await Promise.all([listAgents(), listAgentRuns(50)]);
      setAgents(agentList);
      setRuns(runList);
      if (!agentId && agentList[0]?.id) {
        setAgentId(agentList[0].id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load run console");
    }
  }, [agentId]);

  useEffect(() => {
    load();
  }, [load]);

  async function onRun(e: FormEvent) {
    e.preventDefault();
    if (!agentId) {
      setError("Select an agent first.");
      return;
    }

    let parsedToolInputs: Record<string, Record<string, unknown>> = {};
    try {
      parsedToolInputs = toolInputsJson.trim() ? (JSON.parse(toolInputsJson) as Record<string, Record<string, unknown>>) : {};
    } catch {
      setError("Tool inputs must be valid JSON.");
      return;
    }

    try {
      setIsRunning(true);
      setError(null);
      const run = await runAgent({
        agent_id: agentId,
        input_text: inputText,
        tool_inputs: parsedToolInputs,
        metadata_json: { ui_source: "run-agent-page" }
      });
      setMessage(`Run ${run.id} created with status: ${run.status}`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Agent run failed");
    } finally {
      setIsRunning(false);
    }
  }

  return (
    <main className="mx-auto max-w-6xl p-6">
      <header className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Run Agent</h1>
          <p className="text-sm text-slate-300">Execute RouterAgent flow and inspect tool/approval outcomes.</p>
        </div>
        <div className="flex gap-3 text-sm">
          <Link className="rounded border border-slate-700 px-3 py-2 hover:bg-slate-800" to="/agents">
            Agent Catalog
          </Link>
          <Link className="rounded border border-slate-700 px-3 py-2 hover:bg-slate-800" to="/">
            Back
          </Link>
        </div>
      </header>

      {error && <div className="mb-3 rounded bg-red-500/15 p-3 text-red-200">{error}</div>}
      {message && <div className="mb-3 rounded bg-emerald-500/15 p-3 text-emerald-200">{message}</div>}

      <section className="mb-5 rounded-lg bg-panel p-4">
        <h2 className="mb-3 text-lg font-semibold">New Run</h2>
        <form className="space-y-3" onSubmit={onRun}>
          <label className="block text-sm">
            Agent
            <select
              className="mt-1 w-full rounded border border-slate-700 bg-slate-900 p-2"
              value={agentId}
              onChange={(e) => setAgentId(e.target.value)}
            >
              {agents.map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.name} ({agent.default_agent_type})
                </option>
              ))}
            </select>
          </label>

          <label className="block text-sm">
            Input
            <textarea
              className="mt-1 min-h-24 w-full rounded border border-slate-700 bg-slate-900 p-2"
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
            />
          </label>

          <label className="block text-sm">
            Tool Inputs (JSON)
            <textarea
              className="mt-1 min-h-24 w-full rounded border border-slate-700 bg-slate-900 p-2 font-mono text-xs"
              value={toolInputsJson}
              onChange={(e) => setToolInputsJson(e.target.value)}
            />
          </label>

          <button className="rounded border border-slate-700 px-4 py-2 hover:bg-slate-800" disabled={isRunning}>
            {isRunning ? "Running..." : "Run Agent"}
          </button>
        </form>
      </section>

      <section className="rounded-lg bg-panel p-4">
        <h2 className="mb-3 text-lg font-semibold">Recent Runs</h2>
        <div className="space-y-2">
          {runs.map((run) => (
            <article className="rounded border border-slate-700 p-3" key={run.id}>
              <div className="mb-1 flex items-center justify-between">
                <strong className="font-mono text-sm">{run.id}</strong>
                <span className="text-xs uppercase text-slate-300">{run.status}</span>
              </div>
              <p className="text-sm text-slate-300">{run.input_text.slice(0, 180)}</p>
              <p className="mt-1 text-xs text-slate-400">Routed: {run.routed_agent ?? "n/a"}</p>
              <Link className="mt-2 inline-block text-sm text-accent underline" to={`/agents/runs/${run.id}`}>
                View Trace
              </Link>
            </article>
          ))}
          {runs.length === 0 && <p className="text-sm text-slate-400">No runs yet.</p>}
        </div>
      </section>
    </main>
  );
}
