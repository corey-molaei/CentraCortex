import { FormEvent, useEffect, useState } from "react";
import { Alert } from "../components/ui/Alert";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/Card";
import { PageContainer } from "../layout/PageContainer";
import { getWorkspaceSettings, updateWorkspaceSettings } from "../api/workspace";
import type { WorkspaceSettings } from "../types/workspace";

export function WorkspaceSettingsPage() {
  const [settings, setSettings] = useState<WorkspaceSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getWorkspaceSettings()
      .then(setSettings)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load workspace settings"))
      .finally(() => setLoading(false));
  }, []);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!settings) {
      return;
    }
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      const updated = await updateWorkspaceSettings({
        business_name: settings.business_name,
        timezone: settings.timezone,
        default_email_signature: settings.default_email_signature,
        fallback_contact: settings.fallback_contact,
        escalation_email: settings.escalation_email,
        allowed_actions: settings.allowed_actions
      });
      setSettings(updated);
      setMessage("Workspace settings saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save workspace settings");
    } finally {
      setSaving(false);
    }
  }

  return (
    <PageContainer>
      <Card>
        <CardHeader>
          <CardTitle>Workspace Settings</CardTitle>
          <CardDescription>Business profile, runtime defaults, escalation, and action guardrails.</CardDescription>
        </CardHeader>
        <CardContent>
          {loading && <p className="text-sm text-slate-300">Loading workspace settings...</p>}
          {error && (
            <Alert title="Workspace Settings Error" variant="danger">
              {error}
            </Alert>
          )}
          {message && (
            <Alert title="Saved" variant="success">
              {message}
            </Alert>
          )}

          {settings && (
            <form className="grid gap-4 md:grid-cols-2" onSubmit={onSubmit}>
              <label className="text-sm">
                <span className="mb-1 block text-slate-200">Business Name</span>
                <input
                  className="w-full rounded border border-slate-700 bg-slate-900 p-2"
                  onChange={(event) => setSettings((prev) => (prev ? { ...prev, business_name: event.target.value } : prev))}
                  value={settings.business_name ?? ""}
                />
              </label>

              <label className="text-sm">
                <span className="mb-1 block text-slate-200">Timezone</span>
                <input
                  className="w-full rounded border border-slate-700 bg-slate-900 p-2"
                  onChange={(event) => setSettings((prev) => (prev ? { ...prev, timezone: event.target.value } : prev))}
                  placeholder="Australia/Sydney"
                  value={settings.timezone}
                />
              </label>

              <label className="text-sm md:col-span-2">
                <span className="mb-1 block text-slate-200">Default Email Signature</span>
                <textarea
                  className="min-h-24 w-full rounded border border-slate-700 bg-slate-900 p-2"
                  onChange={(event) =>
                    setSettings((prev) => (prev ? { ...prev, default_email_signature: event.target.value } : prev))
                  }
                  value={settings.default_email_signature ?? ""}
                />
              </label>

              <label className="text-sm">
                <span className="mb-1 block text-slate-200">Fallback Contact</span>
                <input
                  className="w-full rounded border border-slate-700 bg-slate-900 p-2"
                  onChange={(event) => setSettings((prev) => (prev ? { ...prev, fallback_contact: event.target.value } : prev))}
                  value={settings.fallback_contact ?? ""}
                />
              </label>

              <label className="text-sm">
                <span className="mb-1 block text-slate-200">Escalation Email</span>
                <input
                  className="w-full rounded border border-slate-700 bg-slate-900 p-2"
                  onChange={(event) => setSettings((prev) => (prev ? { ...prev, escalation_email: event.target.value } : prev))}
                  value={settings.escalation_email ?? ""}
                />
              </label>

              <div className="md:col-span-2">
                <p className="mb-2 text-sm font-medium text-slate-100">Allowed Actions</p>
                <div className="grid gap-2 md:grid-cols-2">
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      checked={settings.allowed_actions.email_send}
                      onChange={(event) =>
                        setSettings((prev) =>
                          prev
                            ? {
                                ...prev,
                                allowed_actions: { ...prev.allowed_actions, email_send: event.target.checked }
                              }
                            : prev
                        )
                      }
                      type="checkbox"
                    />
                    Email send
                  </label>
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      checked={settings.allowed_actions.email_reply}
                      onChange={(event) =>
                        setSettings((prev) =>
                          prev
                            ? {
                                ...prev,
                                allowed_actions: { ...prev.allowed_actions, email_reply: event.target.checked }
                              }
                            : prev
                        )
                      }
                      type="checkbox"
                    />
                    Email reply
                  </label>
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      checked={settings.allowed_actions.calendar_create}
                      onChange={(event) =>
                        setSettings((prev) =>
                          prev
                            ? {
                                ...prev,
                                allowed_actions: { ...prev.allowed_actions, calendar_create: event.target.checked }
                              }
                            : prev
                        )
                      }
                      type="checkbox"
                    />
                    Calendar create
                  </label>
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      checked={settings.allowed_actions.calendar_update}
                      onChange={(event) =>
                        setSettings((prev) =>
                          prev
                            ? {
                                ...prev,
                                allowed_actions: { ...prev.allowed_actions, calendar_update: event.target.checked }
                              }
                            : prev
                        )
                      }
                      type="checkbox"
                    />
                    Calendar update
                  </label>
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      checked={settings.allowed_actions.calendar_delete}
                      onChange={(event) =>
                        setSettings((prev) =>
                          prev
                            ? {
                                ...prev,
                                allowed_actions: { ...prev.allowed_actions, calendar_delete: event.target.checked }
                              }
                            : prev
                        )
                      }
                      type="checkbox"
                    />
                    Calendar delete
                  </label>
                </div>
              </div>

              <div className="md:col-span-2">
                <button
                  className="rounded bg-accent px-4 py-2 font-semibold text-slate-950 disabled:opacity-70"
                  disabled={saving}
                  type="submit"
                >
                  {saving ? "Saving..." : "Save Workspace Settings"}
                </button>
              </div>
            </form>
          )}
        </CardContent>
      </Card>
    </PageContainer>
  );
}
