import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { createPolicy, listPolicies } from "../api/rbac";
import type { Policy } from "../types/rbac";

export function PoliciesPage() {
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [name, setName] = useState("");
  const [policyType, setPolicyType] = useState<"document" | "tool" | "data_source">("document");
  const [resourceId, setResourceId] = useState("*");
  const [allowedRoles, setAllowedRoles] = useState("User");
  const [allowedUsers, setAllowedUsers] = useState("");
  const [allowedGroups, setAllowedGroups] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      setPolicies(await listPolicies());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load policies");
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    await createPolicy({
      name,
      policy_type: policyType,
      resource_id: resourceId,
      allowed_role_names: allowedRoles
        .split(",")
        .map((v) => v.trim())
        .filter(Boolean),
      allowed_user_ids: allowedUsers
        .split(",")
        .map((v) => v.trim())
        .filter(Boolean),
      allowed_group_ids: allowedGroups
        .split(",")
        .map((v) => v.trim())
        .filter(Boolean)
    });

    setName("");
    setAllowedUsers("");
    setAllowedGroups("");
    await load();
  }

  return (
    <main className="mx-auto max-w-6xl p-6">
      <header className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Policies</h1>
        <Link className="text-sm text-accent underline" to="/">
          Back to dashboard
        </Link>
      </header>

      {error && <div className="mb-4 rounded bg-red-500/15 p-3 text-red-200">{error}</div>}

      <section className="mb-4 rounded-lg bg-panel p-4">
        <h2 className="mb-2 text-lg font-semibold">Create ACL Policy</h2>
        <form className="grid gap-2 md:grid-cols-2" onSubmit={onCreate}>
          <input
            className="rounded border border-slate-700 bg-slate-900 p-2"
            placeholder="Policy name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
          <select
            className="rounded border border-slate-700 bg-slate-900 p-2"
            value={policyType}
            onChange={(e) => setPolicyType(e.target.value as "document" | "tool" | "data_source")}
          >
            <option value="document">document</option>
            <option value="tool">tool</option>
            <option value="data_source">data_source</option>
          </select>

          <input
            className="rounded border border-slate-700 bg-slate-900 p-2"
            placeholder="Resource ID (use * for wildcard)"
            value={resourceId}
            onChange={(e) => setResourceId(e.target.value)}
            required
          />
          <input
            className="rounded border border-slate-700 bg-slate-900 p-2"
            placeholder="Allowed roles comma-separated"
            value={allowedRoles}
            onChange={(e) => setAllowedRoles(e.target.value)}
          />
          <input
            className="rounded border border-slate-700 bg-slate-900 p-2"
            placeholder="Allowed user IDs comma-separated"
            value={allowedUsers}
            onChange={(e) => setAllowedUsers(e.target.value)}
          />
          <input
            className="rounded border border-slate-700 bg-slate-900 p-2"
            placeholder="Allowed group IDs comma-separated"
            value={allowedGroups}
            onChange={(e) => setAllowedGroups(e.target.value)}
          />

          <button className="rounded bg-accent px-4 py-2 font-semibold text-slate-950">Create Policy</button>
        </form>
      </section>

      <section className="rounded-lg bg-panel p-4">
        <h2 className="mb-2 text-lg font-semibold">Policy List</h2>
        <ul className="space-y-2">
          {policies.map((p) => (
            <li key={p.id} className="rounded border border-slate-800 p-3">
              <p className="font-medium">{p.name}</p>
              <p className="text-sm text-slate-300">
                Type: {p.policy_type} | Resource: {p.resource_id}
              </p>
              <p className="text-sm text-slate-300">Roles: {p.allowed_role_names.join(", ") || "-"}</p>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
