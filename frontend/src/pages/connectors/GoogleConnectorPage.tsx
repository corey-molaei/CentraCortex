import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  createGoogleAccount,
  deleteGoogleAccount,
  getGoogleSyncOptions,
  googleListCalendars,
  googleListContactGroups,
  googleListDriveFiles,
  googleListDriveFolders,
  googleListSheetTabs,
  googleListSpreadsheets,
  googleOAuthCallback,
  googleOAuthStart,
  googleStatus,
  googleSync,
  googleTest,
  listGoogleAccounts,
  updateGoogleAccount,
  updateGoogleSyncOptions,
  type GoogleAccountRead,
  type GoogleCalendarListItem
} from "../../api/connectors";
import { ConnectorRuns } from "../../components/connectors/ConnectorRuns";
import type { SyncRun } from "../../types/connectors";

type FolderItem = { id: string; name: string };
type DriveFileItem = { id: string; name: string; mime_type?: string | null };
type SheetItem = { spreadsheet_id: string; title: string };
type SheetTabItem = { title: string; sheet_id?: number | null };
type ContactGroupItem = { resource_name: string; name: string };

export function GoogleConnectorPage() {
  const [accounts, setAccounts] = useState<GoogleAccountRead[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState<string | null>(null);
  const [runs, setRuns] = useState<SyncRun[]>([]);

  const [newLabel, setNewLabel] = useState("");
  const [newGoogleAccountEmail, setNewGoogleAccountEmail] = useState("");
  const [newEnabled, setNewEnabled] = useState(true);
  const [newGmailEnabled, setNewGmailEnabled] = useState(true);
  const [newGmailLabels, setNewGmailLabels] = useState("INBOX,SENT");
  const [newCalendarEnabled, setNewCalendarEnabled] = useState(true);
  const [newDriveEnabled, setNewDriveEnabled] = useState(false);
  const [newSheetsEnabled, setNewSheetsEnabled] = useState(false);
  const [newContactsEnabled, setNewContactsEnabled] = useState(false);

  const [availableCalendarsByAccount, setAvailableCalendarsByAccount] = useState<Record<string, GoogleCalendarListItem[]>>({});
  const [availableFoldersByAccount, setAvailableFoldersByAccount] = useState<Record<string, FolderItem[]>>({});
  const [availableFilesByAccount, setAvailableFilesByAccount] = useState<Record<string, DriveFileItem[]>>({});
  const [availableSheetsByAccount, setAvailableSheetsByAccount] = useState<Record<string, SheetItem[]>>({});
  const [sheetTabsByAccountSheet, setSheetTabsByAccountSheet] = useState<Record<string, SheetTabItem[]>>({});
  const [contactGroupsByAccount, setContactGroupsByAccount] = useState<Record<string, ContactGroupItem[]>>({});
  const [driveFileQueryByAccount, setDriveFileQueryByAccount] = useState<Record<string, string>>({});
  const [sheetQueryByAccount, setSheetQueryByAccount] = useState<Record<string, string>>({});

  const [loadingCalendarsForAccount, setLoadingCalendarsForAccount] = useState<string | null>(null);
  const [loadingFoldersForAccount, setLoadingFoldersForAccount] = useState<string | null>(null);
  const [loadingFilesForAccount, setLoadingFilesForAccount] = useState<string | null>(null);
  const [loadingSheetsForAccount, setLoadingSheetsForAccount] = useState<string | null>(null);
  const [loadingGroupsForAccount, setLoadingGroupsForAccount] = useState<string | null>(null);

  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creatingAccount, setCreatingAccount] = useState(false);
  const [connectingAccountId, setConnectingAccountId] = useState<string | null>(null);

  const redirectUri = useMemo(() => `${window.location.origin}/connectors/google`, []);
  const selectedAccount = accounts.find((account) => account.id === selectedAccountId) ?? null;

  const errorMessage = (err: unknown, fallback: string) => (err instanceof Error ? err.message : fallback);
  const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

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
          if (account.id !== accountId) return account;
          const filtered = (account.calendar_ids || []).filter((calendarId) => validIds.has(calendarId));
          return { ...account, calendar_ids: filtered.length > 0 ? filtered : [primary] };
        })
      );
    } finally {
      setLoadingCalendarsForAccount((current) => (current === accountId ? null : current));
    }
  }

  async function loadFolders(accountId: string) {
    setLoadingFoldersForAccount(accountId);
    try {
      const folders = await googleListDriveFolders(accountId);
      setAvailableFoldersByAccount((prev) => ({ ...prev, [accountId]: folders }));
    } finally {
      setLoadingFoldersForAccount((current) => (current === accountId ? null : current));
    }
  }

  async function loadFiles(accountId: string) {
    setLoadingFilesForAccount(accountId);
    try {
      const account = accounts.find((item) => item.id === accountId);
      const folderId = account?.drive_folder_ids?.[0];
      const rows = await googleListDriveFiles(accountId, folderId, driveFileQueryByAccount[accountId]);
      setAvailableFilesByAccount((prev) => ({ ...prev, [accountId]: rows }));
    } finally {
      setLoadingFilesForAccount((current) => (current === accountId ? null : current));
    }
  }

  async function loadSheets(accountId: string) {
    setLoadingSheetsForAccount(accountId);
    try {
      const rows = await googleListSpreadsheets(accountId, sheetQueryByAccount[accountId]);
      setAvailableSheetsByAccount((prev) => ({ ...prev, [accountId]: rows }));
    } finally {
      setLoadingSheetsForAccount((current) => (current === accountId ? null : current));
    }
  }

  async function loadSheetTabs(accountId: string, spreadsheetId: string) {
    const key = `${accountId}:${spreadsheetId}`;
    const tabs = await googleListSheetTabs(accountId, spreadsheetId);
    setSheetTabsByAccountSheet((prev) => ({ ...prev, [key]: tabs }));
  }

  async function loadContactGroups(accountId: string) {
    setLoadingGroupsForAccount(accountId);
    try {
      const rows = await googleListContactGroups(accountId);
      setContactGroupsByAccount((prev) => ({ ...prev, [accountId]: rows }));
    } finally {
      setLoadingGroupsForAccount((current) => (current === accountId ? null : current));
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
    if (!code || !state) return;

    googleOAuthCallback(code, state)
      .then((res) => {
        setMessage(res.message);
        window.history.replaceState({}, document.title, window.location.pathname);
        return loadAccounts();
      })
      .catch((err) => setError(errorMessage(err, "Google OAuth callback failed")));
  }, []);

  async function createAccountAndMaybeConnect(connectAfterCreate: boolean) {
    if (creatingAccount) return;
    const trimmedEmail = newGoogleAccountEmail.trim();
    if (trimmedEmail && !EMAIL_RE.test(trimmedEmail)) {
      setError("Google account email must be a valid email address.");
      return;
    }
    setCreatingAccount(true);
    setError(null);
    try {
      const created = await createGoogleAccount({
        label: newLabel.trim() || null,
        google_account_email: trimmedEmail || null,
        enabled: newEnabled,
        gmail_enabled: newGmailEnabled,
        gmail_labels: newGmailLabels.split(",").map((value) => value.trim()).filter(Boolean),
        calendar_enabled: newCalendarEnabled,
        drive_enabled: newDriveEnabled,
        sheets_enabled: newSheetsEnabled,
        contacts_enabled: newContactsEnabled,
        calendar_ids: ["primary"],
        sync_scope_configured: false
      });
      await loadAccounts();
      setSelectedAccountId(created.id);
      if (connectAfterCreate) {
        const oauth = await googleOAuthStart(created.id, redirectUri, trimmedEmail || created.google_account_email || undefined);
        window.location.href = oauth.auth_url;
        return;
      }
      setMessage("Google account added. Click Connect to sign in with Google.");
    } catch (err) {
      setError(errorMessage(err, "Failed to add Google account"));
    } finally {
      setCreatingAccount(false);
    }
  }

  async function onCreateAccount(event: FormEvent) {
    event.preventDefault();
    await createAccountAndMaybeConnect(false);
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
        is_workspace_default: account.is_workspace_default,
        gmail_enabled: account.gmail_enabled,
        gmail_labels: account.gmail_labels,
        calendar_enabled: account.calendar_enabled,
        calendar_ids: account.calendar_ids,
        drive_enabled: account.drive_enabled,
        drive_folder_ids: account.drive_folder_ids,
        drive_file_ids: account.drive_file_ids,
        sheets_enabled: account.sheets_enabled,
        sheets_targets: account.sheets_targets,
        contacts_enabled: account.contacts_enabled,
        contacts_sync_mode: account.contacts_sync_mode as "all" | "groups" | "max_count",
        contacts_group_ids: account.contacts_group_ids,
        contacts_max_count: account.contacts_max_count,
        meet_enabled: account.meet_enabled,
        crm_sheet_spreadsheet_id: account.crm_sheet_spreadsheet_id,
        crm_sheet_tab_name: account.crm_sheet_tab_name,
        sync_scope_configured: account.sync_scope_configured
      });
      setMessage("Google account configuration saved.");
      await loadAccounts();
    }, "Failed to save Google account");
  }

  async function onSaveScope(account: GoogleAccountRead) {
    await runAction(async () => {
      const updated = await updateGoogleSyncOptions(account.id, {
        gmail_sync_mode: account.gmail_sync_mode as "all" | "last_n_days" | "max_count" | "query",
        gmail_last_n_days: account.gmail_last_n_days,
        gmail_max_messages: account.gmail_max_messages,
        gmail_query: account.gmail_query,
        calendar_sync_mode: account.calendar_sync_mode as "range_days" | "upcoming_count" | "all",
        calendar_days_back: account.calendar_days_back,
        calendar_days_forward: account.calendar_days_forward,
        calendar_max_events: account.calendar_max_events,
        drive_enabled: account.drive_enabled,
        drive_folder_ids: account.drive_folder_ids,
        drive_file_ids: account.drive_file_ids,
        sheets_enabled: account.sheets_enabled,
        sheets_targets: account.sheets_targets,
        contacts_enabled: account.contacts_enabled,
        contacts_sync_mode: account.contacts_sync_mode as "all" | "groups" | "max_count",
        contacts_group_ids: account.contacts_group_ids,
        contacts_max_count: account.contacts_max_count
      });
      setMessage("Sync scope saved.");
      updateLocalAccount(account.id, { ...updated, sync_scope_configured: true });
      await loadAccounts();
    }, "Failed to save sync scope");
  }

  async function onConnectAccount(account: GoogleAccountRead) {
    if (connectingAccountId) return;
    setError(null);
    setConnectingAccountId(account.id);
    try {
      await updateGoogleAccount(account.id, {
        gmail_enabled: account.gmail_enabled,
        calendar_enabled: account.calendar_enabled,
        drive_enabled: account.drive_enabled,
        sheets_enabled: account.sheets_enabled,
        contacts_enabled: account.contacts_enabled
      });
      setMessage("Permissions updated. Redirecting to Google consent.");
      const oauth = await googleOAuthStart(account.id, redirectUri, account.google_account_email || undefined);
      window.location.href = oauth.auth_url;
    } catch (err) {
      setError(errorMessage(err, "Failed to start Google OAuth"));
    } finally {
      setConnectingAccountId((current) => (current === account.id ? null : current));
    }
  }

  useEffect(() => {
    if (!selectedAccountId) return;
    const account = accounts.find((item) => item.id === selectedAccountId);
    if (!account || !account.is_oauth_connected || !account.calendar_enabled) return;
    if (availableCalendarsByAccount[account.id]) return;
    loadCalendars(account.id).catch((err) => setError(errorMessage(err, "Failed loading Google calendars")));
  }, [accounts, selectedAccountId, availableCalendarsByAccount]);

  useEffect(() => {
    if (!selectedAccountId) return;
    let cancelled = false;
    setError(null);
    getGoogleSyncOptions(selectedAccountId)
      .then((data) => {
        if (cancelled) return;
        updateLocalAccount(selectedAccountId, {
          gmail_sync_mode: data.gmail_sync_mode,
          gmail_last_n_days: data.gmail_last_n_days,
          gmail_max_messages: data.gmail_max_messages,
          gmail_query: data.gmail_query,
          calendar_sync_mode: data.calendar_sync_mode,
          calendar_days_back: data.calendar_days_back,
          calendar_days_forward: data.calendar_days_forward,
          calendar_max_events: data.calendar_max_events,
          drive_enabled: data.drive_enabled,
          drive_folder_ids: data.drive_folder_ids,
          drive_file_ids: data.drive_file_ids,
          sheets_enabled: data.sheets_enabled,
          sheets_targets: data.sheets_targets,
          contacts_enabled: data.contacts_enabled,
          contacts_sync_mode: data.contacts_sync_mode,
          contacts_group_ids: data.contacts_group_ids,
          contacts_max_count: data.contacts_max_count,
          sync_scope_configured: data.sync_scope_configured
        });
      })
      .catch((err) => {
        if (cancelled) return;
        setError(errorMessage(err, "Failed loading sync options"));
      });
    return () => {
      cancelled = true;
    };
  }, [selectedAccountId]);

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
            onChange={(e) => setNewGoogleAccountEmail(e.target.value)}
            placeholder="Google account email (optional)"
            value={newGoogleAccountEmail}
          />
          <input
            className="w-full rounded border border-slate-700 bg-slate-900 p-2"
            onChange={(e) => setNewGmailLabels(e.target.value)}
            placeholder="Gmail labels, e.g. INBOX,SENT"
            value={newGmailLabels}
          />
          <p className="w-full rounded border border-slate-700 bg-slate-900 p-2 text-sm text-slate-300">
            Calendars are discovered after connect. Use "Add & Connect Google" to open Google sign-in immediately.
            The optional email is used as Google login hint.
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
            <label className="flex items-center gap-2">
              <input checked={newDriveEnabled} onChange={(e) => setNewDriveEnabled(e.target.checked)} type="checkbox" /> Drive
            </label>
            <label className="flex items-center gap-2">
              <input checked={newSheetsEnabled} onChange={(e) => setNewSheetsEnabled(e.target.checked)} type="checkbox" /> Sheets
            </label>
            <label className="flex items-center gap-2">
              <input checked={newContactsEnabled} onChange={(e) => setNewContactsEnabled(e.target.checked)} type="checkbox" /> Contacts
            </label>
          </div>
          <div className="md:col-span-2">
            <div className="flex flex-wrap gap-2">
              <button className="rounded bg-accent px-4 py-2 font-semibold text-slate-950 disabled:cursor-not-allowed disabled:opacity-60" disabled={creatingAccount} type="submit">
                {creatingAccount ? "Adding..." : "Add Account"}
              </button>
              <button
                className="rounded border border-slate-700 px-4 py-2 font-semibold disabled:cursor-not-allowed disabled:opacity-60"
                disabled={creatingAccount}
                onClick={() => void createAccountAndMaybeConnect(true)}
                type="button"
              >
                {creatingAccount ? "Adding..." : "Add & Connect Google"}
              </button>
            </div>
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
                <button className="text-left" onClick={() => setSelectedAccountId(account.id)} type="button">
                  <h3 className="font-semibold">{account.label || account.google_account_email || "Unconnected Google account"}</h3>
                  <p className="text-xs text-slate-400">{account.google_account_email || "Not connected yet"}</p>
                </button>
                <div className="flex items-center gap-2 text-xs text-slate-300">
                  {account.is_primary && <span className="rounded border border-emerald-500/60 px-2 py-0.5 text-emerald-200">Primary</span>}
                  {account.is_workspace_default && (
                    <span className="rounded border border-cyan-500/60 px-2 py-0.5 text-cyan-200">Workspace Default</span>
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
                  onChange={(e) =>
                    updateLocalAccount(account.id, {
                      gmail_labels: e.target.value
                        .split(",")
                        .map((value) => value.trim())
                        .filter(Boolean)
                    })
                  }
                  placeholder="Gmail labels"
                  value={(account.gmail_labels || []).join(",")}
                />
                <div className="flex flex-wrap items-center gap-3 md:col-span-2">
                  <label className="flex items-center gap-2">
                    <input
                      checked={account.status.enabled}
                      onChange={(e) => updateLocalAccount(account.id, { status: { ...account.status, enabled: e.target.checked } })}
                      type="checkbox"
                    />
                    Enabled
                  </label>
                  <label className="flex items-center gap-2">
                    <input checked={account.gmail_enabled} onChange={(e) => updateLocalAccount(account.id, { gmail_enabled: e.target.checked })} type="checkbox" />
                    Gmail
                  </label>
                  <label className="flex items-center gap-2">
                    <input checked={account.calendar_enabled} onChange={(e) => updateLocalAccount(account.id, { calendar_enabled: e.target.checked })} type="checkbox" />
                    Calendar
                  </label>
                  <label className="flex items-center gap-2">
                    <input checked={account.drive_enabled} onChange={(e) => updateLocalAccount(account.id, { drive_enabled: e.target.checked })} type="checkbox" />
                    Drive
                  </label>
                  <label className="flex items-center gap-2">
                    <input checked={account.sheets_enabled} onChange={(e) => updateLocalAccount(account.id, { sheets_enabled: e.target.checked })} type="checkbox" />
                    Sheets
                  </label>
                  <label className="flex items-center gap-2">
                    <input checked={account.contacts_enabled} onChange={(e) => updateLocalAccount(account.id, { contacts_enabled: e.target.checked })} type="checkbox" />
                    Contacts
                  </label>
                  <label className="flex items-center gap-2">
                    <input checked={account.meet_enabled} onChange={(e) => updateLocalAccount(account.id, { meet_enabled: e.target.checked })} type="checkbox" />
                    Meet in calendar
                  </label>
                </div>
              </div>

              <div className="mt-3 rounded border border-slate-800 bg-slate-900/60 p-3">
                <div className="mb-2 flex items-center justify-between">
                  <p className="text-sm font-medium">Calendar selection</p>
                  <button
                    className="rounded border border-slate-700 px-2 py-1 text-xs"
                    disabled={!account.is_oauth_connected || loadingCalendarsForAccount === account.id}
                    onClick={() => void runAction(async () => loadCalendars(account.id), "Failed loading Google calendars")}
                    type="button"
                  >
                    {loadingCalendarsForAccount === account.id ? "Loading..." : "Refresh Calendars"}
                  </button>
                </div>
                <div className="space-y-1">
                  {(availableCalendarsByAccount[account.id] || []).map((calendar) => {
                    const checked = (account.calendar_ids || []).includes(calendar.id);
                    return (
                      <label className="flex items-center gap-2 text-sm" key={`${account.id}:${calendar.id}`}>
                        <input
                          checked={checked}
                          onChange={(e) => {
                            const current = new Set(account.calendar_ids || []);
                            if (e.target.checked) current.add(calendar.id);
                            else current.delete(calendar.id);
                            updateLocalAccount(account.id, { calendar_ids: Array.from(current) });
                          }}
                          type="checkbox"
                        />
                        <span>
                          {calendar.summary} <span className="text-xs text-slate-400">[{calendar.id}]</span>
                        </span>
                      </label>
                    );
                  })}
                </div>
              </div>

              <div className="mt-3 rounded border border-slate-800 bg-slate-900/60 p-3">
                <h4 className="mb-2 text-sm font-semibold">Sync Scope</h4>

                <div className="grid gap-2 md:grid-cols-2">
                  <label className="text-xs text-slate-300">
                    Gmail mode
                    <select
                      className="mt-1 w-full rounded border border-slate-700 bg-slate-900 p-2"
                      value={account.gmail_sync_mode}
                      onChange={(e) => updateLocalAccount(account.id, { gmail_sync_mode: e.target.value })}
                    >
                      <option value="all">all</option>
                      <option value="last_n_days">last_n_days</option>
                      <option value="max_count">max_count</option>
                      <option value="query">query</option>
                    </select>
                  </label>
                  <label className="text-xs text-slate-300">
                    Gmail last_n_days
                    <input
                      className="mt-1 w-full rounded border border-slate-700 bg-slate-900 p-2"
                      type="number"
                      value={account.gmail_last_n_days ?? ""}
                      onChange={(e) => updateLocalAccount(account.id, { gmail_last_n_days: e.target.value ? Number(e.target.value) : null })}
                    />
                  </label>
                  <label className="text-xs text-slate-300">
                    Gmail max_messages
                    <input
                      className="mt-1 w-full rounded border border-slate-700 bg-slate-900 p-2"
                      type="number"
                      value={account.gmail_max_messages ?? ""}
                      onChange={(e) => updateLocalAccount(account.id, { gmail_max_messages: e.target.value ? Number(e.target.value) : null })}
                    />
                  </label>
                  <label className="text-xs text-slate-300">
                    Gmail query
                    <input
                      className="mt-1 w-full rounded border border-slate-700 bg-slate-900 p-2"
                      value={account.gmail_query ?? ""}
                      onChange={(e) => updateLocalAccount(account.id, { gmail_query: e.target.value || null })}
                    />
                  </label>

                  <label className="text-xs text-slate-300">
                    Calendar mode
                    <select
                      className="mt-1 w-full rounded border border-slate-700 bg-slate-900 p-2"
                      value={account.calendar_sync_mode}
                      onChange={(e) => updateLocalAccount(account.id, { calendar_sync_mode: e.target.value })}
                    >
                      <option value="range_days">range_days</option>
                      <option value="upcoming_count">upcoming_count</option>
                      <option value="all">all</option>
                    </select>
                  </label>
                  <label className="text-xs text-slate-300">
                    Calendar days_back
                    <input
                      className="mt-1 w-full rounded border border-slate-700 bg-slate-900 p-2"
                      type="number"
                      value={account.calendar_days_back ?? ""}
                      onChange={(e) => updateLocalAccount(account.id, { calendar_days_back: e.target.value ? Number(e.target.value) : null })}
                    />
                  </label>
                  <label className="text-xs text-slate-300">
                    Calendar days_forward
                    <input
                      className="mt-1 w-full rounded border border-slate-700 bg-slate-900 p-2"
                      type="number"
                      value={account.calendar_days_forward ?? ""}
                      onChange={(e) => updateLocalAccount(account.id, { calendar_days_forward: e.target.value ? Number(e.target.value) : null })}
                    />
                  </label>
                  <label className="text-xs text-slate-300">
                    Calendar max_events
                    <input
                      className="mt-1 w-full rounded border border-slate-700 bg-slate-900 p-2"
                      type="number"
                      value={account.calendar_max_events ?? ""}
                      onChange={(e) => updateLocalAccount(account.id, { calendar_max_events: e.target.value ? Number(e.target.value) : null })}
                    />
                  </label>
                </div>

                <div className="mt-3 rounded border border-slate-800 p-2">
                  <div className="mb-2 flex flex-wrap items-center gap-2">
                    <button className="rounded border border-slate-700 px-2 py-1 text-xs" type="button" onClick={() => void runAction(async () => loadFolders(account.id), "Failed loading drive folders")}>{loadingFoldersForAccount === account.id ? "Loading..." : "Load Drive Folders"}</button>
                    <input
                      className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs"
                      placeholder="Drive file search"
                      value={driveFileQueryByAccount[account.id] ?? ""}
                      onChange={(e) => setDriveFileQueryByAccount((prev) => ({ ...prev, [account.id]: e.target.value }))}
                    />
                    <button className="rounded border border-slate-700 px-2 py-1 text-xs" type="button" onClick={() => void runAction(async () => loadFiles(account.id), "Failed loading drive files")}>{loadingFilesForAccount === account.id ? "Loading..." : "Load Drive Files"}</button>
                  </div>
                  <p className="mb-1 text-xs text-slate-400">Drive folders</p>
                  {(availableFoldersByAccount[account.id] || []).map((item) => {
                    const checked = account.drive_folder_ids.includes(item.id);
                    return (
                      <label className="flex items-center gap-2 text-xs" key={`${account.id}:folder:${item.id}`}>
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={(e) => {
                            const set = new Set(account.drive_folder_ids || []);
                            if (e.target.checked) set.add(item.id);
                            else set.delete(item.id);
                            updateLocalAccount(account.id, { drive_folder_ids: Array.from(set) });
                          }}
                        />
                        {item.name}
                      </label>
                    );
                  })}
                  <p className="mb-1 mt-2 text-xs text-slate-400">Drive files</p>
                  {(availableFilesByAccount[account.id] || []).map((item) => {
                    const checked = account.drive_file_ids.includes(item.id);
                    return (
                      <label className="flex items-center gap-2 text-xs" key={`${account.id}:file:${item.id}`}>
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={(e) => {
                            const set = new Set(account.drive_file_ids || []);
                            if (e.target.checked) set.add(item.id);
                            else set.delete(item.id);
                            updateLocalAccount(account.id, { drive_file_ids: Array.from(set) });
                          }}
                        />
                        {item.name}
                      </label>
                    );
                  })}
                </div>

                <div className="mt-3 rounded border border-slate-800 p-2">
                  <div className="mb-2 flex flex-wrap items-center gap-2">
                    <input
                      className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs"
                      placeholder="Sheets search"
                      value={sheetQueryByAccount[account.id] ?? ""}
                      onChange={(e) => setSheetQueryByAccount((prev) => ({ ...prev, [account.id]: e.target.value }))}
                    />
                    <button className="rounded border border-slate-700 px-2 py-1 text-xs" type="button" onClick={() => void runAction(async () => loadSheets(account.id), "Failed loading spreadsheets")}>{loadingSheetsForAccount === account.id ? "Loading..." : "Load Spreadsheets"}</button>
                  </div>
                  {(availableSheetsByAccount[account.id] || []).map((sheet) => {
                    const key = `${account.id}:${sheet.spreadsheet_id}`;
                    const tabs = sheetTabsByAccountSheet[key] || [];
                    return (
                      <div className="mb-2 rounded border border-slate-800 p-2" key={key}>
                        <div className="mb-1 flex items-center justify-between gap-2 text-xs">
                          <span>{sheet.title}</span>
                          <button className="rounded border border-slate-700 px-2 py-1" type="button" onClick={() => void runAction(async () => loadSheetTabs(account.id, sheet.spreadsheet_id), "Failed loading sheet tabs")}>Load Tabs</button>
                        </div>
                        {tabs.map((tab) => {
                          const exists = (account.sheets_targets || []).some(
                            (target) => target.spreadsheet_id === sheet.spreadsheet_id && target.tab === tab.title
                          );
                          return (
                            <label className="flex items-center gap-2 text-xs" key={`${key}:${tab.title}`}>
                              <input
                                type="checkbox"
                                checked={exists}
                                onChange={(e) => {
                                  const targets = [...(account.sheets_targets || [])];
                                  if (e.target.checked) {
                                    targets.push({ spreadsheet_id: sheet.spreadsheet_id, tab: tab.title, range: "A:Z", enabled: true });
                                  } else {
                                    const filtered = targets.filter(
                                      (target) => !(target.spreadsheet_id === sheet.spreadsheet_id && target.tab === tab.title)
                                    );
                                    updateLocalAccount(account.id, { sheets_targets: filtered });
                                    return;
                                  }
                                  updateLocalAccount(account.id, { sheets_targets: targets });
                                }}
                              />
                              {tab.title}
                            </label>
                          );
                        })}
                      </div>
                    );
                  })}
                </div>

                <div className="mt-3 rounded border border-slate-800 p-2">
                  <div className="mb-2 flex items-center gap-2">
                    <button className="rounded border border-slate-700 px-2 py-1 text-xs" type="button" onClick={() => void runAction(async () => loadContactGroups(account.id), "Failed loading contact groups")}>{loadingGroupsForAccount === account.id ? "Loading..." : "Load Contact Groups"}</button>
                    <label className="text-xs text-slate-300">
                      Contacts mode
                      <select
                        className="ml-2 rounded border border-slate-700 bg-slate-900 px-2 py-1"
                        value={account.contacts_sync_mode}
                        onChange={(e) => updateLocalAccount(account.id, { contacts_sync_mode: e.target.value })}
                      >
                        <option value="all">all</option>
                        <option value="groups">groups</option>
                        <option value="max_count">max_count</option>
                      </select>
                    </label>
                    <input
                      className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs"
                      type="number"
                      placeholder="contacts max"
                      value={account.contacts_max_count ?? ""}
                      onChange={(e) => updateLocalAccount(account.id, { contacts_max_count: e.target.value ? Number(e.target.value) : null })}
                    />
                  </div>
                  {(contactGroupsByAccount[account.id] || []).map((group) => {
                    const checked = (account.contacts_group_ids || []).includes(group.resource_name);
                    return (
                      <label className="flex items-center gap-2 text-xs" key={`${account.id}:group:${group.resource_name}`}>
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={(e) => {
                            const set = new Set(account.contacts_group_ids || []);
                            if (e.target.checked) set.add(group.resource_name);
                            else set.delete(group.resource_name);
                            updateLocalAccount(account.id, { contacts_group_ids: Array.from(set) });
                          }}
                        />
                        {group.name}
                      </label>
                    );
                  })}
                </div>

                <div className="mt-3 grid gap-2 md:grid-cols-2">
                  <label className="text-xs text-slate-300">
                    CRM spreadsheet id
                    <input
                      className="mt-1 w-full rounded border border-slate-700 bg-slate-900 p-2"
                      value={account.crm_sheet_spreadsheet_id ?? ""}
                      onChange={(e) => updateLocalAccount(account.id, { crm_sheet_spreadsheet_id: e.target.value || null })}
                    />
                  </label>
                  <label className="text-xs text-slate-300">
                    CRM tab name
                    <input
                      className="mt-1 w-full rounded border border-slate-700 bg-slate-900 p-2"
                      value={account.crm_sheet_tab_name ?? ""}
                      onChange={(e) => updateLocalAccount(account.id, { crm_sheet_tab_name: e.target.value || null })}
                    />
                  </label>
                </div>

                <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                  <button className="rounded border border-slate-700 px-3 py-2" type="button" onClick={() => void onSaveScope(account)}>Save Scope</button>
                  <span className={account.sync_scope_configured ? "text-emerald-300" : "text-amber-300"}>
                    Scope status: {account.sync_scope_configured ? "configured" : "not configured"}
                  </span>
                </div>
              </div>

              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  className="rounded border border-slate-700 px-3 py-2"
                  disabled={connectingAccountId !== null}
                  onClick={() => void onConnectAccount(account)}
                  type="button"
                >
                  {connectingAccountId === account.id ? "Connecting..." : account.is_oauth_connected ? "Reconnect" : "Connect"}
                </button>
                <span className="self-center text-xs text-slate-400">
                  Reconnect after changing capability checkboxes to update requested permissions.
                </span>
                <button className="rounded border border-slate-700 px-3 py-2" onClick={() => void onSaveAccount(account)} type="button">Save</button>
                <button
                  className={`rounded border border-slate-700 px-3 py-2 ${account.is_primary ? "opacity-60" : ""}`}
                  disabled={account.is_primary}
                  onClick={() =>
                    void runAction(async () => {
                      await updateGoogleAccount(account.id, { is_primary: true });
                      setMessage("Primary Google account updated.");
                      await loadAccounts();
                    }, "Failed to set primary account")
                  }
                  type="button"
                >
                  Set as Primary
                </button>
                <button
                  className={`rounded border border-slate-700 px-3 py-2 ${account.is_workspace_default ? "opacity-60" : ""}`}
                  disabled={account.is_workspace_default}
                  onClick={() =>
                    void runAction(async () => {
                      await updateGoogleAccount(account.id, { is_workspace_default: true });
                      setMessage("Workspace default Google account updated.");
                      await loadAccounts();
                    }, "Failed to set workspace default")
                  }
                  type="button"
                >
                  Set Workspace Default
                </button>
                <button
                  className={`rounded border border-slate-700 px-3 py-2 ${account.is_oauth_connected ? "" : "cursor-not-allowed opacity-60"}`}
                  disabled={!account.is_oauth_connected}
                  onClick={() => void runAction(async () => setMessage((await googleTest(account.id)).message), "Failed to test Google account")}
                  type="button"
                >
                  Test
                </button>
                <button
                  className={`rounded border border-slate-700 px-3 py-2 ${account.is_oauth_connected && account.sync_scope_configured ? "" : "cursor-not-allowed opacity-60"}`}
                  disabled={!account.is_oauth_connected || !account.sync_scope_configured}
                  onClick={() =>
                    void runAction(async () => {
                      setMessage((await googleSync(account.id)).message);
                      await loadAccounts();
                      if (selectedAccountId === account.id) await loadRuns(account.id);
                    }, "Failed to sync Google account")
                  }
                  type="button"
                >
                  Sync
                </button>
                <button
                  className="rounded border border-red-700 px-3 py-2 text-red-200"
                  onClick={() =>
                    void runAction(async () => {
                      const confirmed = window.confirm("Disconnect this Google account and remove its indexed documents?");
                      if (!confirmed) return;
                      const result = await deleteGoogleAccount(account.id);
                      setMessage(`${result.message}. Soft-deleted documents: ${result.deleted_docs_count}`);
                      await loadAccounts();
                    }, "Failed to disconnect Google account")
                  }
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
    </main>
  );
}
