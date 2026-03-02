import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { createGroup, listGroups } from "../api/rbac";
import type { Group } from "../types/rbac";

export function GroupsPage() {
  const [groups, setGroups] = useState<Group[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      setGroups(await listGroups());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load groups");
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    await createGroup(name, description);
    setName("");
    setDescription("");
    await load();
  }

  return (
    <main className="mx-auto max-w-5xl p-6">
      <header className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Groups</h1>
        <Link className="text-sm text-accent underline" to="/">
          Back to dashboard
        </Link>
      </header>

      {error && <div className="mb-4 rounded bg-red-500/15 p-3 text-red-200">{error}</div>}

      <section className="mb-4 rounded-lg bg-panel p-4">
        <h2 className="mb-2 text-lg font-semibold">Create Group</h2>
        <form className="grid gap-2 md:grid-cols-3" onSubmit={onCreate}>
          <input
            className="rounded border border-slate-700 bg-slate-900 p-2"
            placeholder="Group name"
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
        <h2 className="mb-2 text-lg font-semibold">Group List</h2>
        <ul className="space-y-2">
          {groups.map((g) => (
            <li key={g.id} className="flex items-center justify-between rounded border border-slate-800 p-3">
              <div>
                <p className="font-medium">{g.name}</p>
                <p className="text-sm text-slate-300">{g.description}</p>
              </div>
              <Link className="text-accent underline" to={`/admin/groups/${g.id}`}>
                View
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
