import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  createBuilderAgent,
  deploySpecVersion,
  generateSpecVersion,
  getSpecVersion,
  listAgentSpecVersions,
  listBuilderAgents,
  rollbackSpecVersion,
  updateSpecVersion,
  uploadBuilderExamples
} from "../api/agentBuilder";
import type { AgentSpec, SpecVersion, SpecVersionDetail } from "../types/agentBuilder";
import type { AgentDefinition } from "../types/agents";

const TOOL_PRESETS = ["search_knowledge", "send_email", "post_slack_message", "create_ticket", "run_script", "query_sql"];
const DATA_SOURCE_PRESETS = ["jira", "slack", "email", "code_repo", "confluence", "sharepoint", "db", "logs", "file_upload"];

export function AgentBuilderPage() {
  const [agents, setAgents] = useState<AgentDefinition[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [versions, setVersions] = useState<SpecVersion[]>([]);
  const [activeVersionId, setActiveVersionId] = useState<string | null>(null);
  const [versionDetail, setVersionDetail] = useState<SpecVersionDetail | null>(null);

  const [newAgentName, setNewAgentName] = useState("Builder Agent");
  const [newAgentDescription, setNewAgentDescription] = useState("No-code builder managed agent");

  const [prompt, setPrompt] = useState("Create an agent that summarizes connector updates and flags high-risk items.");
  const [riskLevel, setRiskLevel] = useState<"low" | "medium" | "high" | "critical">("medium");
  const [selectedTools, setSelectedTools] = useState<string[]>(["search_knowledge"]);
  const [selectedDataSources, setSelectedDataSources] = useState<string[]>(["jira", "slack"]);
  const [exampleText, setExampleText] = useState("Use concise bullet points. Prioritize urgent findings first.");
  const [exampleFiles, setExampleFiles] = useState<File[]>([]);

  const [editorMode, setEditorMode] = useState<"form" | "json">("form");
  const [formSpec, setFormSpec] = useState<AgentSpec | null>(null);
  const [jsonEditor, setJsonEditor] = useState("");

  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const activeVersion = useMemo(
    () => versions.find((item) => item.id === activeVersionId) ?? null,
    [versions, activeVersionId]
  );

  const loadAgents = useCallback(async () => {
    const data = await listBuilderAgents();
    setAgents(data);
    if (!selectedAgentId && data[0]?.id) {
      setSelectedAgentId(data[0].id);
    }
  }, [selectedAgentId]);

  const loadVersions = useCallback(async () => {
    if (!selectedAgentId) {
      setVersions([]);
      return;
    }
    const data = await listAgentSpecVersions(selectedAgentId);
    setVersions(data);
    if (!activeVersionId && data[0]?.id) {
      setActiveVersionId(data[0].id);
    }
  }, [selectedAgentId, activeVersionId]);

  const loadVersionDetail = useCallback(async () => {
    if (!activeVersionId) {
      setVersionDetail(null);
      setFormSpec(null);
      setJsonEditor("");
      return;
    }
    const detail = await getSpecVersion(activeVersionId);
    setVersionDetail(detail);
    setFormSpec(detail.version.spec_json);
    setJsonEditor(JSON.stringify(detail.version.spec_json, null, 2));
  }, [activeVersionId]);

  useEffect(() => {
    loadAgents().catch((err) => setError(err instanceof Error ? err.message : "Failed to load agents"));
  }, [loadAgents]);

  useEffect(() => {
    loadVersions().catch((err) => setError(err instanceof Error ? err.message : "Failed to load versions"));
  }, [loadVersions]);

  useEffect(() => {
    loadVersionDetail().catch((err) => setError(err instanceof Error ? err.message : "Failed to load version detail"));
  }, [loadVersionDetail]);

  async function onCreateAgent(e: FormEvent) {
    e.preventDefault();
    try {
      setError(null);
      const created = await createBuilderAgent({ name: newAgentName, description: newAgentDescription });
      setMessage(`Builder agent created: ${created.name}`);
      await loadAgents();
      setSelectedAgentId(created.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create builder agent");
    }
  }

  async function onUploadExamples() {
    if (!selectedAgentId || exampleFiles.length === 0) {
      return;
    }
    try {
      setError(null);
      const result = await uploadBuilderExamples(selectedAgentId, exampleFiles);
      setMessage(`${result.uploaded_count} style example file(s) uploaded.`);
      setExampleFiles([]);
      await loadVersionDetail();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to upload examples");
    }
  }

  async function onGenerateVersion(e: FormEvent) {
    e.preventDefault();
    if (!selectedAgentId) {
      setError("Select an agent first.");
      return;
    }

    const inlineExamples = exampleText
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);

    try {
      setError(null);
      const created = await generateSpecVersion(selectedAgentId, {
        prompt,
        selected_tools: selectedTools,
        selected_data_sources: selectedDataSources,
        risk_level: riskLevel,
        example_texts: inlineExamples,
        generate_tests_count: 6
      });
      setMessage(`Generated spec version v${created.version_number}.`);
      await loadVersions();
      setActiveVersionId(created.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate spec version");
    }
  }

  async function onSaveSpec() {
    if (!activeVersionId) {
      return;
    }

    try {
      setError(null);
      const specPayload = editorMode === "form" ? formSpec : JSON.parse(jsonEditor);
      if (!specPayload) {
        setError("No spec payload to save.");
        return;
      }
      const updated = await updateSpecVersion(activeVersionId, specPayload);
      setMessage(`Saved version v${updated.version_number}.`);
      await loadVersions();
      await loadVersionDetail();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save spec");
    }
  }

  async function onDeploy(versionId: string) {
    try {
      setError(null);
      const deployed = await deploySpecVersion(versionId);
      setMessage(`Deployed version v${deployed.version.version_number}.`);
      await loadVersions();
      setActiveVersionId(versionId);
      await loadVersionDetail();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to deploy version");
    }
  }

  async function onRollback(versionId: string) {
    if (!selectedAgentId) {
      return;
    }
    const note = window.prompt("Rollback note (optional)") ?? undefined;
    try {
      setError(null);
      const result = await rollbackSpecVersion(selectedAgentId, versionId, note);
      setMessage(`Rolled back and deployed version v${result.version.version_number}.`);
      await loadVersions();
      setActiveVersionId(result.version.id);
      await loadVersionDetail();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to rollback version");
    }
  }

  return (
    <main className="mx-auto max-w-7xl p-6">
      <header className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Agent Builder Wizard</h1>
          <p className="text-sm text-slate-300">Prompt-to-AgentSpec generation, versioning, deploy, and rollback.</p>
        </div>
        <div className="flex gap-3 text-sm">
          <Link className="rounded border border-slate-700 px-3 py-2 hover:bg-slate-800" to="/agents">
            Agent Runtime
          </Link>
          <Link className="rounded border border-slate-700 px-3 py-2 hover:bg-slate-800" to="/">
            Back
          </Link>
        </div>
      </header>

      {error && <div className="mb-3 rounded bg-red-500/15 p-3 text-red-200">{error}</div>}
      {message && <div className="mb-3 rounded bg-emerald-500/15 p-3 text-emerald-200">{message}</div>}

      <section className="mb-5 rounded-lg bg-panel p-4">
        <h2 className="mb-3 text-lg font-semibold">Step 1: Choose Or Create Agent</h2>
        <div className="grid gap-3 md:grid-cols-2">
          <label className="text-sm">
            Existing Builder Agent
            <select
              className="mt-1 w-full rounded border border-slate-700 bg-slate-900 p-2"
              value={selectedAgentId}
              onChange={(e) => {
                setSelectedAgentId(e.target.value);
                setActiveVersionId(null);
              }}
            >
              <option value="">Select agent</option>
              {agents.map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.name}
                </option>
              ))}
            </select>
          </label>

          <form className="grid gap-2" onSubmit={onCreateAgent}>
            <input
              className="rounded border border-slate-700 bg-slate-900 p-2"
              value={newAgentName}
              onChange={(e) => setNewAgentName(e.target.value)}
              placeholder="New agent name"
            />
            <input
              className="rounded border border-slate-700 bg-slate-900 p-2"
              value={newAgentDescription}
              onChange={(e) => setNewAgentDescription(e.target.value)}
              placeholder="Description"
            />
            <button className="w-fit rounded border border-slate-700 px-4 py-2 hover:bg-slate-800">Create Builder Agent</button>
          </form>
        </div>
      </section>

      <section className="mb-5 rounded-lg bg-panel p-4">
        <h2 className="mb-3 text-lg font-semibold">Step 2: Prompt + Inputs</h2>
        <form className="space-y-3" onSubmit={onGenerateVersion}>
          <label className="block text-sm">
            Prompt
            <textarea className="mt-1 min-h-24 w-full rounded border border-slate-700 bg-slate-900 p-2" value={prompt} onChange={(e) => setPrompt(e.target.value)} />
          </label>

          <div className="grid gap-3 md:grid-cols-3">
            <label className="text-sm">
              Risk Level
              <select className="mt-1 w-full rounded border border-slate-700 bg-slate-900 p-2" value={riskLevel} onChange={(e) => setRiskLevel(e.target.value as "low" | "medium" | "high" | "critical")}>
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
                <option value="critical">Critical</option>
              </select>
            </label>

            <div className="text-sm md:col-span-2">
              Tools
              <div className="mt-1 flex flex-wrap gap-2 rounded border border-slate-700 bg-slate-900 p-2">
                {TOOL_PRESETS.map((tool) => (
                  <label className="inline-flex items-center gap-2" key={tool}>
                    <input
                      checked={selectedTools.includes(tool)}
                      type="checkbox"
                      onChange={(e) => {
                        if (e.target.checked) {
                          setSelectedTools((prev) => [...prev, tool]);
                        } else {
                          setSelectedTools((prev) => prev.filter((item) => item !== tool));
                        }
                      }}
                    />
                    {tool}
                  </label>
                ))}
              </div>
            </div>
          </div>

          <div className="text-sm">
            Data Sources
            <div className="mt-1 flex flex-wrap gap-2 rounded border border-slate-700 bg-slate-900 p-2">
              {DATA_SOURCE_PRESETS.map((source) => (
                <label className="inline-flex items-center gap-2" key={source}>
                  <input
                    checked={selectedDataSources.includes(source)}
                    type="checkbox"
                    onChange={(e) => {
                      if (e.target.checked) {
                        setSelectedDataSources((prev) => [...prev, source]);
                      } else {
                        setSelectedDataSources((prev) => prev.filter((item) => item !== source));
                      }
                    }}
                  />
                  {source}
                </label>
              ))}
            </div>
          </div>

          <label className="block text-sm">
            Inline Style Examples (one per line)
            <textarea
              className="mt-1 min-h-20 w-full rounded border border-slate-700 bg-slate-900 p-2"
              value={exampleText}
              onChange={(e) => setExampleText(e.target.value)}
            />
          </label>

          <div className="flex flex-wrap items-center gap-3">
            <input
              multiple
              type="file"
              accept=".txt,.md,.log,.json"
              onChange={(e) => setExampleFiles(Array.from(e.target.files ?? []))}
            />
            <button
              className="rounded border border-slate-700 px-3 py-2 hover:bg-slate-800"
              onClick={(e) => {
                e.preventDefault();
                onUploadExamples().catch((err) => setError(err instanceof Error ? err.message : "Failed to upload"));
              }}
              type="button"
            >
              Upload Example Files
            </button>
            <button className="rounded border border-slate-700 px-4 py-2 hover:bg-slate-800" type="submit">
              Generate Spec Version
            </button>
          </div>
        </form>
      </section>

      <section className="mb-5 rounded-lg bg-panel p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Step 3: Agent Spec Editor</h2>
          <div className="flex gap-2 text-sm">
            <button className="rounded border border-slate-700 px-2 py-1 hover:bg-slate-800" onClick={() => setEditorMode("form")}>
              Form View
            </button>
            <button className="rounded border border-slate-700 px-2 py-1 hover:bg-slate-800" onClick={() => setEditorMode("json")}>
              JSON View
            </button>
          </div>
        </div>

        {!versionDetail && <p className="text-sm text-slate-400">Generate or select a version to edit.</p>}

        {versionDetail && editorMode === "form" && formSpec && (
          <div className="grid gap-3 md:grid-cols-2">
            <label className="text-sm md:col-span-2">
              Name
              <input
                className="mt-1 w-full rounded border border-slate-700 bg-slate-900 p-2"
                value={formSpec.name}
                onChange={(e) => setFormSpec({ ...formSpec, name: e.target.value })}
              />
            </label>
            <label className="text-sm md:col-span-2">
              Goal
              <textarea
                className="mt-1 min-h-20 w-full rounded border border-slate-700 bg-slate-900 p-2"
                value={formSpec.goal}
                onChange={(e) => setFormSpec({ ...formSpec, goal: e.target.value })}
              />
            </label>
            <label className="text-sm">
              Agent Type
              <select
                className="mt-1 w-full rounded border border-slate-700 bg-slate-900 p-2"
                value={formSpec.agent_type}
                onChange={(e) => setFormSpec({ ...formSpec, agent_type: e.target.value as AgentSpec["agent_type"] })}
              >
                <option value="knowledge">knowledge</option>
                <option value="comms">comms</option>
                <option value="ops">ops</option>
                <option value="sql">sql</option>
                <option value="guard">guard</option>
              </select>
            </label>
            <label className="text-sm">
              Risk Level
              <select
                className="mt-1 w-full rounded border border-slate-700 bg-slate-900 p-2"
                value={formSpec.risk_level}
                onChange={(e) => setFormSpec({ ...formSpec, risk_level: e.target.value as AgentSpec["risk_level"] })}
              >
                <option value="low">low</option>
                <option value="medium">medium</option>
                <option value="high">high</option>
                <option value="critical">critical</option>
              </select>
            </label>
            <label className="text-sm md:col-span-2">
              System Prompt
              <textarea
                className="mt-1 min-h-28 w-full rounded border border-slate-700 bg-slate-900 p-2"
                value={formSpec.system_prompt}
                onChange={(e) => setFormSpec({ ...formSpec, system_prompt: e.target.value })}
              />
            </label>
          </div>
        )}

        {versionDetail && editorMode === "json" && (
          <textarea
            className="min-h-72 w-full rounded border border-slate-700 bg-slate-900 p-2 font-mono text-xs"
            value={jsonEditor}
            onChange={(e) => setJsonEditor(e.target.value)}
          />
        )}

        {versionDetail && (
          <div className="mt-3 flex gap-2">
            <button className="rounded border border-slate-700 px-4 py-2 hover:bg-slate-800" onClick={onSaveSpec}>
              Save Spec
            </button>
            {activeVersionId && (
              <button className="rounded border border-emerald-700 px-4 py-2 hover:bg-emerald-900/30" onClick={() => onDeploy(activeVersionId)}>
                Deploy Version
              </button>
            )}
          </div>
        )}
      </section>

      <section className="rounded-lg bg-panel p-4">
        <h2 className="mb-3 text-lg font-semibold">Step 4: Version History + Rollback</h2>

        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-2">
            {versions.map((version) => (
              <article className="rounded border border-slate-700 p-3" key={version.id}>
                <div className="mb-1 flex items-center justify-between">
                  <strong>v{version.version_number}</strong>
                  <span className="text-xs uppercase text-slate-300">{version.status}</span>
                </div>
                <p className="text-xs text-slate-400">Risk: {version.risk_level}</p>
                <p className="mt-1 text-xs text-slate-400">Prompt: {version.source_prompt.slice(0, 120)}</p>
                <div className="mt-2 flex gap-2">
                  <button
                    className="rounded border border-slate-700 px-2 py-1 text-xs hover:bg-slate-800"
                    onClick={() => setActiveVersionId(version.id)}
                  >
                    Open
                  </button>
                  <button
                    className="rounded border border-emerald-700 px-2 py-1 text-xs hover:bg-emerald-900/30"
                    onClick={() => onDeploy(version.id)}
                  >
                    Deploy
                  </button>
                  <button
                    className="rounded border border-amber-700 px-2 py-1 text-xs hover:bg-amber-900/30"
                    onClick={() => onRollback(version.id)}
                  >
                    Rollback To
                  </button>
                </div>
              </article>
            ))}
            {versions.length === 0 && <p className="text-sm text-slate-400">No versions for this agent.</p>}
          </div>

          <div className="space-y-3">
            {activeVersion && (
              <section className="rounded border border-slate-700 p-3">
                <h3 className="mb-2 text-sm font-semibold">Generated Test Suite (v{activeVersion.version_number})</h3>
                <div className="space-y-2">
                  {activeVersion.generated_tests_json.map((test, idx) => (
                    <article className="rounded bg-slate-950 p-2" key={`${activeVersion.id}-${idx}`}>
                      <p className="text-xs text-slate-300">Prompt: {test.prompt}</p>
                      <p className="text-xs text-slate-400">Expected: {test.expected_behavior}</p>
                      <p className="text-xs text-slate-500">Focus: {test.policy_focus}</p>
                    </article>
                  ))}
                </div>
              </section>
            )}

            {versionDetail && (
              <section className="rounded border border-slate-700 p-3">
                <h3 className="mb-2 text-sm font-semibold">Style Library Samples</h3>
                <div className="space-y-2">
                  {versionDetail.style_examples.map((example) => (
                    <article className="rounded bg-slate-950 p-2" key={example.id}>
                      <p className="text-xs text-slate-300">{example.filename ?? "inline-example"}</p>
                      <p className="text-xs text-slate-400">{example.content.slice(0, 180)}</p>
                    </article>
                  ))}
                  {versionDetail.style_examples.length === 0 && <p className="text-xs text-slate-500">No style samples on this version.</p>}
                </div>
              </section>
            )}
          </div>
        </div>
      </section>
    </main>
  );
}
