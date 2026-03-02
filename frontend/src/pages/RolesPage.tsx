import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { createRole, listRoles } from "../api/rbac";
import type { Role } from "../types/rbac";

export function RolesPage() {
  const [roles, setRoles] = useState<Role[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      setRoles(await listRoles());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load roles");
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    await createRole(name, description);
    setName("");
    setDescription("");
    await load();
  }

  return (
    <main className="mx-auto max-w-5xl p-6">
      <header className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Roles</h1>
        <Link className="text-sm text-accent underline" to="/">
          Back to dashboard
        </Link>
      </header>

      {error && <div className="mb-4 rounded bg-red-500/15 p-3 text-red-200">{error}</div>}

      <section className="mb-4 rounded-lg bg-panel p-4">
        <h2 className="mb-2 text-lg font-semibold">Create Custom Role</h2>
        <form className="grid gap-2 md:grid-cols-3" onSubmit={onCreate}>
          <input
            className="rounded border border-slate-700 bg-slate-900 p-2"
            placeholder="Role name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
          <input
            className="rounded border border-slate-700 bg-slate-900 p-2"
            placeholder="Description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
          <button className="rounded bg-accent px-4 py-2 font-semibold text-slate-950">Create</button>
        </form>
      </section>

      <section className="rounded-lg bg-panel p-4">
        <h2 className="mb-2 text-lg font-semibold">Role Catalog</h2>
        <ul className="space-y-2">
          {roles.map((r) => (
            <li key={r.id} className="rounded border border-slate-800 p-3">
              <p className="font-medium">
                {r.name} {r.is_system ? "(system)" : ""}
              </p>
              <p className="text-sm text-slate-300">{r.description ?? "No description"}</p>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
