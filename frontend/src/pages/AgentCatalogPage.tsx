import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { createAgent, deleteAgent, listAgents } from "../api/agents";
import type { AgentDefinition } from "../types/agents";

const TOOL_PRESETS = [
  "search_knowledge",
  "send_email",
  "post_slack_message",
  "create_ticket",
  "run_script",
  "query_sql"
];

export function AgentCatalogPage() {
  const [agents, setAgents] = useState<AgentDefinition[]>([]);
  const [name, setName] = useState("Knowledge Assistant");
  const [description, setDescription] = useState("Tenant knowledge and safe enterprise actions");
  const [systemPrompt, setSystemPrompt] = useState(
    "You are a secure enterprise assistant. Follow tenant boundaries, use approved tools only, and provide concise outcomes."
  );
  const [defaultAgentType, setDefaultAgentType] = useState<"knowledge" | "comms" | "ops" | "sql" | "guard">("knowledge");
  const [allowedTools, setAllowedTools] = useState<string[]>(["search_knowledge"]);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const allowedToolCsv = useMemo(() => allowedTools.join(", "), [allowedTools]);

  async function load() {
    try {
      setError(null);
      const data = await listAgents();
      setAgents(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load agent catalog");
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    try {
      await createAgent({
        name,
        description,
        system_prompt: systemPrompt,
        default_agent_type: defaultAgentType,
        allowed_tools: allowedTools,
        enabled: true,
        config_json: { require_approval_for_risky_tools: true }
      });
      setMessage("Agent created.");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create agent");
    }
  }

  async function onDelete(agentId: string) {
    if (!window.confirm("Delete this agent definition?")) {
      return;
    }
    try {
      await deleteAgent(agentId);
      setMessage("Agent deleted.");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete agent");
    }
  }

  return (
    <main className="mx-auto max-w-6xl p-6">
      <header className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Agent Catalog</h1>
          <p className="text-sm text-slate-300">Define and govern multi-agent runtime behavior per tenant.</p>
        </div>
        <div className="flex gap-3 text-sm">
          <Link className="rounded border border-slate-700 px-3 py-2 hover:bg-slate-800" to="/agents/run">
            Run Agent
          </Link>
          <Link className="rounded border border-slate-700 px-3 py-2 hover:bg-slate-800" to="/">
            Back
          </Link>
        </div>
      </header>

      {error && <div className="mb-3 rounded bg-red-500/15 p-3 text-red-200">{error}</div>}
      {message && <div className="mb-3 rounded bg-emerald-500/15 p-3 text-emerald-200">{message}</div>}

      <section className="mb-5 rounded-lg bg-panel p-4">
        <h2 className="mb-3 text-lg font-semibold">Create Agent</h2>
        <form className="grid gap-3 md:grid-cols-2" onSubmit={onCreate}>
          <label className="text-sm">
            Name
            <input className="mt-1 w-full rounded border border-slate-700 bg-slate-900 p-2" value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="text-sm">
            Default Agent Type
            <select
              className="mt-1 w-full rounded border border-slate-700 bg-slate-900 p-2"
              value={defaultAgentType}
              onChange={(e) => setDefaultAgentType(e.target.value as "knowledge" | "comms" | "ops" | "sql" | "guard")}
            >
              <option value="knowledge">Knowledge</option>
              <option value="comms">Comms</option>
              <option value="ops">Ops</option>
              <option value="sql">SQL</option>
              <option value="guard">Guard</option>
            </select>
          </label>

          <label className="text-sm md:col-span-2">
            Description
            <input
              className="mt-1 w-full rounded border border-slate-700 bg-slate-900 p-2"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </label>

          <label className="text-sm md:col-span-2">
            System Prompt
            <textarea
              className="mt-1 min-h-28 w-full rounded border border-slate-700 bg-slate-900 p-2"
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
            />
          </label>

          <label className="text-sm md:col-span-2">
            Allowed Tools
            <div className="mt-1 flex flex-wrap gap-2 rounded border border-slate-700 bg-slate-900 p-2">
              {TOOL_PRESETS.map((tool) => {
                const checked = allowedTools.includes(tool);
                return (
                  <label className="inline-flex items-center gap-2 text-sm" key={tool}>
                    <input
                      checked={checked}
                      type="checkbox"
                      onChange={(e) => {
                        if (e.target.checked) {
                          setAllowedTools((prev) => [...prev, tool]);
                        } else {
                          setAllowedTools((prev) => prev.filter((item) => item !== tool));
                        }
                      }}
                    />
                    {tool}
                  </label>
                );
              })}
            </div>
            <p className="mt-2 text-xs text-slate-400">Selected: {allowedToolCsv || "none"}</p>
          </label>

          <div className="md:col-span-2">
            <button className="rounded border border-slate-700 px-4 py-2 hover:bg-slate-800">Create Agent</button>
          </div>
        </form>
      </section>

      <section className="rounded-lg bg-panel p-4">
        <h2 className="mb-3 text-lg font-semibold">Catalog Entries</h2>
        <div className="space-y-3">
          {agents.map((agent) => (
            <article className="rounded border border-slate-700 p-3" key={agent.id}>
              <div className="mb-1 flex items-center justify-between">
                <strong>{agent.name}</strong>
                <button className="text-xs text-red-300 hover:text-red-200" onClick={() => onDelete(agent.id)}>
                  Delete
                </button>
              </div>
              <p className="text-sm text-slate-300">{agent.description ?? "No description"}</p>
              <p className="mt-1 text-xs text-slate-400">
                Type: {agent.default_agent_type} | Tools: {(agent.allowed_tools || []).join(", ") || "none"} | Enabled: {String(agent.enabled)}
              </p>
            </article>
          ))}
          {agents.length === 0 && <p className="text-sm text-slate-400">No agents found for this tenant.</p>}
        </div>
      </section>
    </main>
  );
}
