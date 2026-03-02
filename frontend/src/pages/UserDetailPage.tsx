import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { assignUserGroup, assignUserRole, getUserDetail, listGroups, listRoles } from "../api/rbac";
import type { Group, Role, UserDetail } from "../types/rbac";

export function UserDetailPage() {
  const { userId } = useParams();
  const [detail, setDetail] = useState<UserDetail | null>(null);
  const [groups, setGroups] = useState<Group[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [selectedGroupId, setSelectedGroupId] = useState("");
  const [selectedRoleId, setSelectedRoleId] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!userId) {
      return;
    }
    try {
      setError(null);
      const [userDetail, allGroups, allRoles] = await Promise.all([
        getUserDetail(userId),
        listGroups(),
        listRoles()
      ]);
      setDetail(userDetail);
      setGroups(allGroups);
      setRoles(allRoles);
      setSelectedGroupId(allGroups[0]?.id ?? "");
      setSelectedRoleId(allRoles[0]?.id ?? "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load user detail");
    }
  }, [userId]);

  useEffect(() => {
    load();
  }, [load]);

  async function onAssignGroup(e: FormEvent) {
    e.preventDefault();
    if (!userId || !selectedGroupId) {
      return;
    }
    await assignUserGroup(userId, selectedGroupId);
    setMessage("Group assigned.");
    await load();
  }

  async function onAssignRole(e: FormEvent) {
    e.preventDefault();
    if (!userId || !selectedRoleId) {
      return;
    }
    await assignUserRole(userId, selectedRoleId);
    setMessage("Role assigned.");
    await load();
  }

  return (
    <main className="mx-auto max-w-4xl p-6">
      <header className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">User Detail</h1>
        <Link className="text-sm text-accent underline" to="/admin/users">
          Back to users
        </Link>
      </header>

      {error && <div className="mb-4 rounded bg-red-500/15 p-3 text-red-200">{error}</div>}
      {message && <div className="mb-4 rounded bg-emerald-500/15 p-3 text-emerald-200">{message}</div>}

      {detail && (
        <div className="grid gap-4 md:grid-cols-2">
          <section className="rounded-lg bg-panel p-4">
            <h2 className="mb-2 text-lg font-semibold">Identity</h2>
            <p>{detail.email}</p>
            <p className="text-slate-300">{detail.full_name ?? "No name"}</p>
            <p className="text-slate-300">Primary role: {detail.role}</p>
          </section>

          <section className="rounded-lg bg-panel p-4">
            <h2 className="mb-2 text-lg font-semibold">Assign Group</h2>
            <form className="flex gap-2" onSubmit={onAssignGroup}>
              <select
                className="w-full rounded border border-slate-700 bg-slate-900 p-2"
                value={selectedGroupId}
                onChange={(e) => setSelectedGroupId(e.target.value)}
              >
                {groups.map((g) => (
                  <option key={g.id} value={g.id}>
                    {g.name}
                  </option>
                ))}
              </select>
              <button className="rounded border border-slate-700 px-3 py-2">Assign</button>
            </form>
          </section>

          <section className="rounded-lg bg-panel p-4">
            <h2 className="mb-2 text-lg font-semibold">Assign Custom Role</h2>
            <form className="flex gap-2" onSubmit={onAssignRole}>
              <select
                className="w-full rounded border border-slate-700 bg-slate-900 p-2"
                value={selectedRoleId}
                onChange={(e) => setSelectedRoleId(e.target.value)}
              >
                {roles.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name}
                  </option>
                ))}
              </select>
              <button className="rounded border border-slate-700 px-3 py-2">Assign</button>
            </form>
          </section>

          <section className="rounded-lg bg-panel p-4">
            <h2 className="mb-2 text-lg font-semibold">Current Groups</h2>
            <ul className="space-y-1 text-slate-300">
              {detail.groups.map((g) => (
                <li key={g.id}>{g.name}</li>
              ))}
            </ul>
            <h2 className="mb-2 mt-4 text-lg font-semibold">Current Custom Roles</h2>
            <ul className="space-y-1 text-slate-300">
              {detail.custom_roles.map((r) => (
                <li key={r.id}>{r.name}</li>
              ))}
            </ul>
          </section>
        </div>
      )}
    </main>
  );
}
