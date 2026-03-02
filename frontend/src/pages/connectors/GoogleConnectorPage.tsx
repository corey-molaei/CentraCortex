import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  createGoogleAccount,
  createGoogleCalendarEvent,
  deleteGoogleAccount,
  deleteGoogleCalendarEvent,
  googleOAuthCallback,
  googleOAuthStart,
  googleStatus,
  googleSync,
  googleTest,
  googleListCalendars,
  listGoogleAccounts,
  type GoogleAccountRead,
  type GoogleCalendarListItem,
  updateGoogleAccount,
  updateGoogleCalendarEvent
} from "../../api/connectors";
import { ConnectorRuns } from "../../components/connectors/ConnectorRuns";
import type { SyncRun } from "../../types/connectors";

export function GoogleConnectorPage() {
  const [accounts, setAccounts] = useState<GoogleAccountRead[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState<string | null>(null);
  const [runs, setRuns] = useState<SyncRun[]>([]);

  const [newLabel, setNewLabel] = useState("");
  const [newEnabled, setNewEnabled] = useState(true);
  const [newGmailEnabled, setNewGmailEnabled] = useState(true);
  const [newGmailLabels, setNewGmailLabels] = useState("INBOX,SENT");
  const [newCalendarEnabled, setNewCalendarEnabled] = useState(true);
  const [availableCalendarsByAccount, setAvailableCalendarsByAccount] = useState<Record<string, GoogleCalendarListItem[]>>({});
  const [loadingCalendarsForAccount, setLoadingCalendarsForAccount] = useState<string | null>(null);

  const [eventId, setEventId] = useState("");
  const [eventCalendarId, setEventCalendarId] = useState("primary");
  const [eventSummary, setEventSummary] = useState("");
  const [eventDescription, setEventDescription] = useState("");
  const [eventLocation, setEventLocation] = useState("");
  const [eventStart, setEventStart] = useState("");
  const [eventEnd, setEventEnd] = useState("");
  const [eventTimezone, setEventTimezone] = useState("UTC");
  const [eventAttendees, setEventAttendees] = useState("");

  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const redirectUri = useMemo(() => `${window.location.origin}/connectors/google`, []);

  const selectedAccount = accounts.find((account) => account.id === selectedAccountId) ?? null;

  const errorMessage = (err: unknown, fallback: string) => (err instanceof Error ? err.message : fallback);

  function updateLocalAccount(accountId: string, patch: Partial<GoogleAccountRead>) {
    setAccounts((prev) => prev.map((account) => (account.id === accountId ? { ...account, ...patch } : account)));
  }

  async function runAction(action: () => Promise<void>, fallback: string) {
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(errorMessage(err, fallback));
    }
  }

  async function loadAccounts() {
    const list = await listGoogleAccounts();
    setAccounts(list);
    setSelectedAccountId((current) => {
      if (current && list.some((item) => item.id === current)) {
        return current;
      }
      return list[0]?.id ?? null;
    });
  }

  async function loadRuns(accountId: string | null) {
    if (!accountId) {
      setRuns([]);
      return;
    }
    setRuns(await googleStatus(accountId));
  }

  async function loadCalendars(accountId: string) {
    setLoadingCalendarsForAccount(accountId);
    try {
      const calendars = await googleListCalendars(accountId);
      setAvailableCalendarsByAccount((prev) => ({ ...prev, [accountId]: calendars }));
      const validIds = new Set(calendars.map((item) => item.id));
      const primary = calendars.find((item) => item.primary)?.id ?? calendars[0]?.id ?? "primary";
      setAccounts((prev) =>
        prev.map((account) => {
          if (account.id !== accountId) {
            return account;
          }
          const filtered = (account.calendar_ids || []).filter((calendarId) => validIds.has(calendarId));
          return {
            ...account,
            calendar_ids: filtered.length > 0 ? filtered : [primary]
          };
        })
      );
    } finally {
      setLoadingCalendarsForAccount((current) => (current === accountId ? null : current));
    }
  }

  useEffect(() => {
    loadAccounts().catch((err) => setError(errorMessage(err, "Failed loading Google accounts")));
  }, []);

  useEffect(() => {
    loadRuns(selectedAccountId).catch((err) => setError(errorMessage(err, "Failed loading Google account status")));
  }, [selectedAccountId]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const state = params.get("state");
    if (!code || !state) {
      return;
    }

    googleOAuthCallback(code, state)
      .then((res) => {
        setMessage(res.message);
        window.history.replaceState({}, document.title, window.location.pathname);
        return loadAccounts();
      })
      .catch((err) => setError(errorMessage(err, "Google OAuth callback failed")));
  }, []);

  async function onCreateAccount(event: FormEvent) {
    event.preventDefault();
    await runAction(async () => {
      const created = await createGoogleAccount({
        label: newLabel.trim() || null,
        enabled: newEnabled,
        gmail_enabled: newGmailEnabled,
        gmail_labels: newGmailLabels.split(",").map((value) => value.trim()).filter(Boolean),
        calendar_enabled: newCalendarEnabled,
        calendar_ids: ["primary"]
      });
      setMessage("Google account added.");
      await loadAccounts();
      setSelectedAccountId(created.id);
    }, "Failed to add Google account");
  }

  async function onSaveAccount(account: GoogleAccountRead) {
    if (account.calendar_enabled && (!account.calendar_ids || account.calendar_ids.length === 0)) {
      setError("Select at least one calendar before saving.");
      return;
    }
    await runAction(async () => {
      await updateGoogleAccount(account.id, {
        label: account.label,
        enabled: account.status.enabled,
        is_primary: account.is_primary,
        gmail_enabled: account.gmail_enabled,
        gmail_labels: account.gmail_labels,
        calendar_enabled: account.calendar_enabled,
        calendar_ids: account.calendar_ids
      });
      setMessage("Google account configuration saved.");
      await loadAccounts();
    }, "Failed to save Google account");
  }

  useEffect(() => {
    if (!selectedAccountId) {
      return;
    }
    const account = accounts.find((item) => item.id === selectedAccountId);
    if (!account || !account.is_oauth_connected || !account.calendar_enabled) {
      return;
    }
    if (availableCalendarsByAccount[account.id]) {
      return;
    }
    loadCalendars(account.id).catch((err) => setError(errorMessage(err, "Failed loading Google calendars")));
  }, [accounts, selectedAccountId, availableCalendarsByAccount]);

  const calendarPayload = {
    calendar_id: eventCalendarId,
    summary: eventSummary,
    description: eventDescription || null,
    location: eventLocation || null,
    start_datetime: eventStart,
    end_datetime: eventEnd,
    timezone: eventTimezone || null,
    attendees: eventAttendees.split(",").map((value) => value.trim()).filter(Boolean)
  };

  return (
    <main className="mx-auto max-w-6xl p-6">
      <header className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">My Google Accounts</h1>
        <Link className="text-sm text-accent underline" to="/connectors">Back to connectors</Link>
      </header>

      {error && <div className="mb-4 rounded bg-red-500/15 p-3 text-red-200">{error}</div>}
      {message && <div className="mb-4 rounded bg-emerald-500/15 p-3 text-emerald-200">{message}</div>}

      <section className="mb-4 rounded-lg bg-panel p-4">
        <h2 className="mb-2 text-lg font-semibold">Add Google Account</h2>
        <form className="grid gap-2 md:grid-cols-2" onSubmit={onCreateAccount}>
          <input
            className="w-full rounded border border-slate-700 bg-slate-900 p-2"
            onChange={(e) => setNewLabel(e.target.value)}
            placeholder="Label (optional)"
            value={newLabel}
          />
          <input
            className="w-full rounded border border-slate-700 bg-slate-900 p-2"
            onChange={(e) => setNewGmailLabels(e.target.value)}
            placeholder="Gmail labels, e.g. INBOX,SENT"
            value={newGmailLabels}
          />
          <p className="w-full rounded border border-slate-700 bg-slate-900 p-2 text-sm text-slate-300">
            Calendars are discovered after Google connect. You can choose them per account below.
          </p>
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <label className="flex items-center gap-2">
              <input checked={newEnabled} onChange={(e) => setNewEnabled(e.target.checked)} type="checkbox" /> Enabled
            </label>
            <label className="flex items-center gap-2">
              <input checked={newGmailEnabled} onChange={(e) => setNewGmailEnabled(e.target.checked)} type="checkbox" /> Gmail
            </label>
            <label className="flex items-center gap-2">
              <input checked={newCalendarEnabled} onChange={(e) => setNewCalendarEnabled(e.target.checked)} type="checkbox" /> Calendar
            </label>
          </div>
          <div className="md:col-span-2">
            <button className="rounded bg-accent px-4 py-2 font-semibold text-slate-950" type="submit">Add Account</button>
          </div>
        </form>
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="space-y-3">
          {accounts.length === 0 && <p className="rounded-lg bg-panel p-4 text-sm text-slate-300">No Google accounts added yet.</p>}
          {accounts.map((account) => (
            <article
              className={`rounded-lg border p-4 ${selectedAccountId === account.id ? "border-accent bg-panel" : "border-slate-800 bg-panel/70"}`}
              key={account.id}
            >
              <div className="mb-3 flex items-center justify-between gap-2">
                <button
                  className="text-left"
                  onClick={() => setSelectedAccountId(account.id)}
                  type="button"
                >
                  <h3 className="font-semibold">{account.label || account.google_account_email || "Unconnected Google account"}</h3>
                  <p className="text-xs text-slate-400">{account.google_account_email || "Not connected yet"}</p>
                </button>
                <div className="flex items-center gap-2 text-xs text-slate-300">
                  {account.is_primary && (
                    <span className="rounded border border-emerald-500/60 px-2 py-0.5 text-emerald-200">Primary</span>
                  )}
                  <span>{account.is_oauth_connected ? "Connected" : "Disconnected"}</span>
                </div>
              </div>

              <div className="grid gap-2 text-sm md:grid-cols-2">
                <input
                  className="w-full rounded border border-slate-700 bg-slate-900 p-2"
                  onChange={(e) => updateLocalAccount(account.id, { label: e.target.value })}
                  placeholder="Label"
                  value={account.label ?? ""}
                />
                <input
                  className="w-full rounded border border-slate-700 bg-slate-900 p-2"
                  onChange={(e) => updateLocalAccount(account.id, { gmail_labels: e.target.value.split(",").map((value) => value.trim()).filter(Boolean) })}
                  placeholder="Gmail labels"
                  value={(account.gmail_labels || []).join(",")}
                />
                <div className="flex flex-wrap items-center gap-3">
                  <label className="flex items-center gap-2">
                    <input
                      checked={account.status.enabled}
                      onChange={(e) => updateLocalAccount(account.id, { status: { ...account.status, enabled: e.target.checked } })}
                      type="checkbox"
                    />
                    Enabled
                  </label>
                  <label className="flex items-center gap-2">
                    <input
                      checked={account.gmail_enabled}
                      onChange={(e) => updateLocalAccount(account.id, { gmail_enabled: e.target.checked })}
                      type="checkbox"
                    />
                    Gmail
                  </label>
                  <label className="flex items-center gap-2">
                    <input
                      checked={account.calendar_enabled}
                      onChange={(e) => updateLocalAccount(account.id, { calendar_enabled: e.target.checked })}
                      type="checkbox"
                    />
                    Calendar
                  </label>
                </div>
              </div>

              <div className="mt-3 rounded border border-slate-800 bg-slate-900/60 p-3">
                <div className="mb-2 flex items-center justify-between">
                  <p className="text-sm font-medium">Calendar selection</p>
                  <button
                    className="rounded border border-slate-700 px-2 py-1 text-xs"
                    disabled={!account.is_oauth_connected || loadingCalendarsForAccount === account.id}
                    onClick={() => void runAction(async () => {
                      await loadCalendars(account.id);
                    }, "Failed loading Google calendars")}
                    type="button"
                  >
                    {loadingCalendarsForAccount === account.id ? "Loading..." : "Refresh Calendars"}
                  </button>
                </div>
                {!account.is_oauth_connected && (
                  <p className="text-xs text-slate-400">Connect account first to load calendars.</p>
                )}
                {account.is_oauth_connected && (availableCalendarsByAccount[account.id] || []).length === 0 && (
                  <p className="text-xs text-slate-400">No calendars loaded yet. Click Refresh Calendars.</p>
                )}
                <div className="space-y-1">
                  {(availableCalendarsByAccount[account.id] || []).map((calendar) => {
                    const checked = (account.calendar_ids || []).includes(calendar.id);
                    return (
                      <label className="flex items-center gap-2 text-sm" key={`${account.id}:${calendar.id}`}>
                        <input
                          checked={checked}
                          onChange={(e) => {
                            const current = new Set(account.calendar_ids || []);
                            if (e.target.checked) {
                              current.add(calendar.id);
                            } else {
                              current.delete(calendar.id);
                            }
                            updateLocalAccount(account.id, { calendar_ids: Array.from(current) });
                          }}
                          type="checkbox"
                        />
                        <span>{calendar.summary} <span className="text-xs text-slate-400">[{calendar.id}]</span></span>
                      </label>
                    );
                  })}
                </div>
                <p className="mt-2 text-xs text-slate-400">
                  Selected: {(account.calendar_ids || []).join(", ") || "none"}
                </p>
              </div>

              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  className="rounded border border-slate-700 px-3 py-2"
                  onClick={() => void runAction(async () => {
                    const oauth = await googleOAuthStart(account.id, redirectUri);
                    window.location.href = oauth.auth_url;
                  }, "Failed to start Google OAuth")}
                  type="button"
                >
                  {account.is_oauth_connected ? "Reconnect" : "Connect"}
                </button>
                <button className="rounded border border-slate-700 px-3 py-2" onClick={() => void onSaveAccount(account)} type="button">Save</button>
                <button
                  className={`rounded border border-slate-700 px-3 py-2 ${account.is_primary ? "opacity-60" : ""}`}
                  disabled={account.is_primary}
                  onClick={() => void runAction(async () => {
                    await updateGoogleAccount(account.id, { is_primary: true });
                    setMessage("Primary Google account updated.");
                    await loadAccounts();
                  }, "Failed to set primary account")}
                  type="button"
                >
                  Set as Primary
                </button>
                <button
                  className={`rounded border border-slate-700 px-3 py-2 ${
                    account.is_oauth_connected ? "" : "cursor-not-allowed opacity-60"
                  }`}
                  disabled={!account.is_oauth_connected}
                  onClick={() => void runAction(async () => setMessage((await googleTest(account.id)).message), "Failed to test Google account")}
                  type="button"
                >
                  Test
                </button>
                <button
                  className={`rounded border border-slate-700 px-3 py-2 ${
                    account.is_oauth_connected ? "" : "cursor-not-allowed opacity-60"
                  }`}
                  disabled={!account.is_oauth_connected}
                  onClick={() => void runAction(async () => {
                    setMessage((await googleSync(account.id)).message);
                    await loadAccounts();
                    if (selectedAccountId === account.id) {
                      await loadRuns(account.id);
                    }
                  }, "Failed to sync Google account")}
                  type="button"
                >
                  Sync
                </button>
                <button
                  className="rounded border border-red-700 px-3 py-2 text-red-200"
                  onClick={() => void runAction(async () => {
                    const confirmed = window.confirm("Disconnect this Google account and remove its indexed documents?");
                    if (!confirmed) {
                      return;
                    }
                    const result = await deleteGoogleAccount(account.id);
                    setMessage(`${result.message}. Soft-deleted documents: ${result.deleted_docs_count}`);
                    await loadAccounts();
                  }, "Failed to disconnect Google account")}
                  type="button"
                >
                  Disconnect
                </button>
              </div>
            </article>
          ))}
        </section>

        <ConnectorRuns runs={runs} status={selectedAccount?.status ?? null} />
      </div>

      <section className="mt-4 rounded-lg bg-panel p-4">
        <h2 className="mb-2 text-lg font-semibold">Calendar Event Actions {selectedAccount ? `(${selectedAccount.label || selectedAccount.google_account_email || selectedAccount.id})` : ""}</h2>
        {!selectedAccount && <p className="mb-2 text-sm text-slate-300">Select an account first.</p>}

        <div className="grid gap-2 md:grid-cols-2">
          <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" onChange={(e) => setEventId(e.target.value)} placeholder="Event ID (for update/delete)" value={eventId} />
          <select
            className="w-full rounded border border-slate-700 bg-slate-900 p-2"
            onChange={(e) => setEventCalendarId(e.target.value)}
            value={eventCalendarId}
          >
            {((selectedAccount ? selectedAccount.calendar_ids : []) || ["primary"]).map((calendarId) => (
              <option key={calendarId} value={calendarId}>
                {calendarId}
              </option>
            ))}
          </select>
          <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" onChange={(e) => setEventSummary(e.target.value)} placeholder="Summary" value={eventSummary} />
          <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" onChange={(e) => setEventLocation(e.target.value)} placeholder="Location" value={eventLocation} />
          <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" onChange={(e) => setEventStart(e.target.value)} placeholder="Start datetime (ISO)" value={eventStart} />
          <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" onChange={(e) => setEventEnd(e.target.value)} placeholder="End datetime (ISO)" value={eventEnd} />
          <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" onChange={(e) => setEventTimezone(e.target.value)} placeholder="Timezone" value={eventTimezone} />
          <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" onChange={(e) => setEventAttendees(e.target.value)} placeholder="Attendees comma-separated" value={eventAttendees} />
        </div>
        <textarea className="mt-2 w-full rounded border border-slate-700 bg-slate-900 p-2" onChange={(e) => setEventDescription(e.target.value)} placeholder="Description" value={eventDescription} />

        <div className="mt-3 flex flex-wrap gap-2">
          <button
            className="rounded border border-slate-700 px-4 py-2"
            disabled={!selectedAccount}
            onClick={() => void runAction(async () => {
              if (!selectedAccount) return;
              const created = await createGoogleCalendarEvent(selectedAccount.id, calendarPayload);
              setMessage(`Created event ${created.id}`);
              setEventId(created.id);
            }, "Failed to create calendar event")}
            type="button"
          >
            Create Event
          </button>
          <button
            className="rounded border border-slate-700 px-4 py-2"
            disabled={!selectedAccount || !eventId}
            onClick={() => void runAction(async () => {
              if (!selectedAccount || !eventId) return;
              const updated = await updateGoogleCalendarEvent(selectedAccount.id, eventId, calendarPayload);
              setMessage(`Updated event ${updated.id}`);
            }, "Failed to update calendar event")}
            type="button"
          >
            Update Event
          </button>
          <button
            className="rounded border border-red-700 px-4 py-2 text-red-200"
            disabled={!selectedAccount || !eventId}
            onClick={() => void runAction(async () => {
              if (!selectedAccount || !eventId) return;
              const deleted = await deleteGoogleCalendarEvent(selectedAccount.id, eventId, eventCalendarId);
              setMessage(deleted.message);
              setEventId("");
            }, "Failed to delete calendar event")}
            type="button"
          >
            Delete Event
          </button>
        </div>
      </section>
    </main>
  );
}
