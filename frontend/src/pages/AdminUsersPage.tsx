import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { inviteUser, listUsers } from "../api/rbac";
import type { InviteResponse, UserListItem } from "../types/rbac";

export function AdminUsersPage() {
  const [query, setQuery] = useState("");
  const [users, setUsers] = useState<UserListItem[]>([]);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("User");
  const [inviteResult, setInviteResult] = useState<InviteResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load(search?: string) {
    try {
      setError(null);
      const data = await listUsers(search);
      setUsers(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load users");
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function onSearchSubmit(e: FormEvent) {
    e.preventDefault();
    await load(query);
  }

  async function onInvite(e: FormEvent) {
    e.preventDefault();
    try {
      const response = await inviteUser(inviteEmail, inviteRole);
      setInviteResult(response);
      setInviteEmail("");
      await load(query);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Invite failed");
    }
  }

  return (
    <main className="mx-auto max-w-6xl p-6">
      <header className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Users</h1>
        <Link className="text-sm text-accent underline" to="/">
          Back to dashboard
        </Link>
      </header>

      {error && <div className="mb-4 rounded bg-red-500/15 p-3 text-red-200">{error}</div>}

      <section className="mb-4 rounded-lg bg-panel p-4">
        <form className="flex gap-2" onSubmit={onSearchSubmit}>
          <input
            className="w-full rounded border border-slate-700 bg-slate-900 p-2"
            placeholder="Search by email or name"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button className="rounded border border-slate-700 px-3 py-2">Search</button>
        </form>
      </section>

      <section className="mb-4 rounded-lg bg-panel p-4">
        <h2 className="mb-3 text-lg font-semibold">Invite User</h2>
        <form className="grid gap-2 md:grid-cols-3" onSubmit={onInvite}>
          <input
            className="rounded border border-slate-700 bg-slate-900 p-2"
            placeholder="user@company.com"
            type="email"
            value={inviteEmail}
            onChange={(e) => setInviteEmail(e.target.value)}
            required
          />
          <select
            className="rounded border border-slate-700 bg-slate-900 p-2"
            value={inviteRole}
            onChange={(e) => setInviteRole(e.target.value)}
          >
            <option>Owner</option>
            <option>Admin</option>
            <option>Manager</option>
            <option>User</option>
          </select>
          <button className="rounded bg-accent px-4 py-2 font-semibold text-slate-950">Send Invite</button>
        </form>
        {inviteResult && (
          <div className="mt-3 rounded bg-emerald-500/15 p-3 text-emerald-200">
            Invite token: <code>{inviteResult.invite_token}</code>
          </div>
        )}
      </section>

      <section className="rounded-lg bg-panel p-4">
        <h2 className="mb-3 text-lg font-semibold">Tenant Users</h2>
        <div className="overflow-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="text-slate-300">
                <th className="pb-2">Email</th>
                <th className="pb-2">Name</th>
                <th className="pb-2">Role</th>
                <th className="pb-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-t border-slate-800">
                  <td className="py-2">{u.email}</td>
                  <td className="py-2">{u.full_name ?? "-"}</td>
                  <td className="py-2">{u.role}</td>
                  <td className="py-2">
                    <Link className="text-accent underline" to={`/admin/users/${u.id}`}>
                      Detail
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}
