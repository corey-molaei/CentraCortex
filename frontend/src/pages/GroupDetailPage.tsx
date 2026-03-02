import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getGroup, listGroupMembers } from "../api/rbac";
import type { Group, UserListItem } from "../types/rbac";

export function GroupDetailPage() {
  const { groupId } = useParams();
  const [group, setGroup] = useState<Group | null>(null);
  const [members, setMembers] = useState<UserListItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!groupId) {
      return;
    }
    Promise.all([getGroup(groupId), listGroupMembers(groupId)])
      .then(([g, m]) => {
        setGroup(g);
        setMembers(m);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load group"));
  }, [groupId]);

  return (
    <main className="mx-auto max-w-4xl p-6">
      <header className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Group Detail</h1>
        <Link className="text-sm text-accent underline" to="/admin/groups">
          Back to groups
        </Link>
      </header>

      {error && <div className="mb-4 rounded bg-red-500/15 p-3 text-red-200">{error}</div>}

      {group && (
        <section className="rounded-lg bg-panel p-4">
          <h2 className="text-lg font-semibold">{group.name}</h2>
          <p className="mb-4 text-slate-300">{group.description ?? "No description"}</p>

          <h3 className="mb-2 font-medium">Members</h3>
          <ul className="space-y-2">
            {members.map((m) => (
              <li key={m.id} className="rounded border border-slate-800 p-3">
                <p>{m.email}</p>
                <p className="text-sm text-slate-300">{m.full_name ?? "No name"}</p>
              </li>
            ))}
          </ul>
        </section>
      )}
    </main>
  );
}
