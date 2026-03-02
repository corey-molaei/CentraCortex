import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getUserProfile, updateUserProfile } from "../api/client";
import type { UserProfile } from "../types/auth";

export function ProfilePage() {
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [fullName, setFullName] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getUserProfile()
      .then((data) => {
        setProfile(data);
        setFullName(data.full_name ?? "");
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load profile"));
  }, []);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setMessage(null);
    setError(null);
    try {
      const updated = await updateUserProfile(fullName);
      setProfile(updated);
      setMessage("Profile updated.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update profile");
    }
  }

  return (
    <main className="mx-auto max-w-2xl p-6">
      <div className="mb-4">
        <Link className="text-sm text-accent underline" to="/">
          Back to dashboard
        </Link>
      </div>

      <section className="rounded-xl border border-slate-700 bg-panel p-6">
        <h1 className="mb-4 text-2xl font-semibold">User Profile</h1>

        {error && <div className="mb-3 rounded bg-red-500/15 p-3 text-red-200">{error}</div>}
        {message && <div className="mb-3 rounded bg-emerald-500/15 p-3 text-emerald-200">{message}</div>}

        {profile && (
          <form onSubmit={onSubmit}>
            <div className="mb-4">
              <label className="mb-2 block text-sm">Email</label>
              <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" value={profile.email} disabled />
            </div>

            <div className="mb-4">
              <label className="mb-2 block text-sm">Full Name</label>
              <input
                className="w-full rounded border border-slate-700 bg-slate-900 p-2"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
              />
            </div>

            <button type="submit" className="rounded bg-accent px-4 py-2 font-semibold text-slate-950">
              Save
            </button>
          </form>
        )}
      </section>
    </main>
  );
}
