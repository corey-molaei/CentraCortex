import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  createEmailAccount,
  deleteEmailAccount,
  emailAccountStatus,
  listEmailAccounts,
  syncEmailAccount,
  testEmailAccount,
  type EmailAccountRead,
  updateEmailAccount
} from "../../api/connectors";
import { ConnectorRuns } from "../../components/connectors/ConnectorRuns";
import type { SyncRun } from "../../types/connectors";

type EditableAccount = EmailAccountRead & { password?: string };

export function EmailConnectorPage() {
  const [accounts, setAccounts] = useState<EditableAccount[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState<string | null>(null);
  const [runs, setRuns] = useState<SyncRun[]>([]);

  const [label, setLabel] = useState("");
  const [emailAddress, setEmailAddress] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [imapHost, setImapHost] = useState("imap.gmail.com");
  const [imapPort, setImapPort] = useState(993);
  const [smtpHost, setSmtpHost] = useState("smtp.gmail.com");
  const [smtpPort, setSmtpPort] = useState(587);
  const [folders, setFolders] = useState("INBOX,Sent");
  const [enabled, setEnabled] = useState(true);
  const [useSsl, setUseSsl] = useState(true);
  const [smtpUseStarttls, setSmtpUseStarttls] = useState(true);

  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const selectedAccount = accounts.find((account) => account.id === selectedAccountId) ?? null;

  function updateLocalAccount(accountId: string, patch: Partial<EditableAccount>) {
    setAccounts((prev) => prev.map((account) => (account.id === accountId ? { ...account, ...patch } : account)));
  }

  async function loadAccounts() {
    const list = await listEmailAccounts();
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
    setRuns(await emailAccountStatus(accountId));
  }

  useEffect(() => {
    loadAccounts().catch((err) => setError(err instanceof Error ? err.message : "Failed loading email accounts"));
  }, []);

  useEffect(() => {
    loadRuns(selectedAccountId).catch((err) => setError(err instanceof Error ? err.message : "Failed loading email sync status"));
  }, [selectedAccountId]);

  async function onCreateAccount(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setMessage(null);
    try {
      const created = await createEmailAccount({
        label: label.trim() || null,
        email_address: emailAddress.trim(),
        username: username.trim(),
        password,
        imap_host: imapHost.trim(),
        imap_port: imapPort,
        use_ssl: useSsl,
        smtp_host: smtpHost.trim() || null,
        smtp_port: smtpPort || null,
        smtp_use_starttls: smtpUseStarttls,
        folders: folders.split(",").map((value) => value.trim()).filter(Boolean),
        enabled
      });
      setMessage("Email account added.");
      setPassword("");
      await loadAccounts();
      setSelectedAccountId(created.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed adding email account");
    }
  }

  async function onSaveAccount(account: EditableAccount) {
    setError(null);
    setMessage(null);
    setBusyId(account.id);
    try {
      const payload: Record<string, unknown> = {
        label: account.label,
        email_address: account.email_address,
        username: account.username,
        imap_host: account.imap_host,
        imap_port: account.imap_port,
        use_ssl: account.use_ssl,
        smtp_host: account.smtp_host,
        smtp_port: account.smtp_port,
        smtp_use_starttls: account.smtp_use_starttls,
        folders: account.folders,
        enabled: account.status.enabled
      };
      if (account.password && account.password.trim()) {
        payload.password = account.password.trim();
      }
      await updateEmailAccount(account.id, payload);
      setMessage("Email account configuration saved.");
      await loadAccounts();
      await loadRuns(account.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed saving email account");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <main className="mx-auto max-w-6xl p-6">
      <header className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">My Email Accounts</h1>
        <Link className="text-sm text-accent underline" to="/connectors">
          Back to connectors
        </Link>
      </header>

      <p className="mb-4 text-sm text-slate-300">
        Add IMAP/SMTP accounts for non-Google providers. For Gmail OAuth, use the Google connector.
      </p>

      {error && <div className="mb-4 rounded bg-red-500/15 p-3 text-red-200">{error}</div>}
      {message && <div className="mb-4 rounded bg-emerald-500/15 p-3 text-emerald-200">{message}</div>}

      <section className="mb-4 rounded-lg bg-panel p-4">
        <h2 className="mb-2 text-lg font-semibold">Add Email Account</h2>
        <form className="grid gap-2 md:grid-cols-2" onSubmit={onCreateAccount}>
          <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" placeholder="Label (optional)" value={label} onChange={(e) => setLabel(e.target.value)} />
          <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" placeholder="Email address" value={emailAddress} onChange={(e) => setEmailAddress(e.target.value)} />
          <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" placeholder="Username" value={username} onChange={(e) => setUsername(e.target.value)} />
          <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" placeholder="Password / App Password" value={password} onChange={(e) => setPassword(e.target.value)} />
          <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" placeholder="IMAP host" value={imapHost} onChange={(e) => setImapHost(e.target.value)} />
          <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" type="number" placeholder="IMAP port" value={imapPort} onChange={(e) => setImapPort(Number(e.target.value))} />
          <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" placeholder="SMTP host" value={smtpHost} onChange={(e) => setSmtpHost(e.target.value)} />
          <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" type="number" placeholder="SMTP port" value={smtpPort} onChange={(e) => setSmtpPort(Number(e.target.value))} />
          <input className="w-full rounded border border-slate-700 bg-slate-900 p-2 md:col-span-2" placeholder="Folders (comma separated)" value={folders} onChange={(e) => setFolders(e.target.value)} />
          <div className="flex flex-wrap items-center gap-3 text-sm md:col-span-2">
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
              Enabled
            </label>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={useSsl} onChange={(e) => setUseSsl(e.target.checked)} />
              IMAP SSL
            </label>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={smtpUseStarttls} onChange={(e) => setSmtpUseStarttls(e.target.checked)} />
              SMTP STARTTLS
            </label>
          </div>
          <div className="md:col-span-2">
            <button className="rounded bg-accent px-4 py-2 font-semibold text-slate-950" type="submit">
              Add Account
            </button>
          </div>
        </form>
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="space-y-3">
          {accounts.length === 0 && <p className="rounded-lg bg-panel p-4 text-sm text-slate-300">No email accounts added yet.</p>}
          {accounts.map((account) => (
            <article
              key={account.id}
              className={`rounded-lg border p-4 ${selectedAccountId === account.id ? "border-accent bg-panel" : "border-slate-800 bg-panel/70"}`}
            >
              <div className="mb-3 flex items-center justify-between gap-2">
                <button className="text-left" onClick={() => setSelectedAccountId(account.id)} type="button">
                  <h3 className="font-semibold">{account.label || account.email_address}</h3>
                  <p className="text-xs text-slate-400">{account.email_address}</p>
                </button>
                {account.is_primary && (
                  <span className="rounded border border-emerald-500/60 px-2 py-0.5 text-xs text-emerald-200">Primary</span>
                )}
              </div>

              <div className="grid gap-2 text-sm md:grid-cols-2">
                <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" value={account.label ?? ""} placeholder="Label" onChange={(e) => updateLocalAccount(account.id, { label: e.target.value })} />
                <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" value={account.email_address} placeholder="Email address" onChange={(e) => updateLocalAccount(account.id, { email_address: e.target.value })} />
                <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" value={account.username} placeholder="Username" onChange={(e) => updateLocalAccount(account.id, { username: e.target.value })} />
                <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" value={account.password ?? ""} placeholder="New password (optional)" onChange={(e) => updateLocalAccount(account.id, { password: e.target.value })} />
                <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" value={account.imap_host} placeholder="IMAP host" onChange={(e) => updateLocalAccount(account.id, { imap_host: e.target.value })} />
                <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" type="number" value={account.imap_port} placeholder="IMAP port" onChange={(e) => updateLocalAccount(account.id, { imap_port: Number(e.target.value) })} />
                <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" value={account.smtp_host ?? ""} placeholder="SMTP host" onChange={(e) => updateLocalAccount(account.id, { smtp_host: e.target.value })} />
                <input className="w-full rounded border border-slate-700 bg-slate-900 p-2" type="number" value={account.smtp_port ?? 0} placeholder="SMTP port" onChange={(e) => updateLocalAccount(account.id, { smtp_port: Number(e.target.value) })} />
                <input className="w-full rounded border border-slate-700 bg-slate-900 p-2 md:col-span-2" value={(account.folders || []).join(",")} placeholder="Folders" onChange={(e) => updateLocalAccount(account.id, { folders: e.target.value.split(",").map((value) => value.trim()).filter(Boolean) })} />
                <div className="flex flex-wrap items-center gap-3 md:col-span-2">
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={account.status.enabled}
                      onChange={(e) => updateLocalAccount(account.id, { status: { ...account.status, enabled: e.target.checked } })}
                    />
                    Enabled
                  </label>
                  <label className="flex items-center gap-2">
                    <input type="checkbox" checked={account.use_ssl} onChange={(e) => updateLocalAccount(account.id, { use_ssl: e.target.checked })} />
                    IMAP SSL
                  </label>
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={account.smtp_use_starttls}
                      onChange={(e) => updateLocalAccount(account.id, { smtp_use_starttls: e.target.checked })}
                    />
                    SMTP STARTTLS
                  </label>
                </div>
              </div>

              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  className="rounded bg-accent px-3 py-1.5 text-sm font-semibold text-slate-950 disabled:opacity-50"
                  onClick={() => void onSaveAccount(account)}
                  disabled={busyId === account.id}
                  type="button"
                >
                  Save
                </button>
                <button
                  className="rounded border border-slate-700 px-3 py-1.5 text-sm disabled:opacity-50"
                  onClick={async () => {
                    setBusyId(account.id);
                    try {
                      const result = await testEmailAccount(account.id);
                      setMessage(result.message);
                    } catch (err) {
                      setError(err instanceof Error ? err.message : "Email test failed");
                    } finally {
                      setBusyId(null);
                    }
                  }}
                  disabled={busyId === account.id}
                  type="button"
                >
                  Test
                </button>
                <button
                  className="rounded border border-slate-700 px-3 py-1.5 text-sm disabled:opacity-50"
                  onClick={async () => {
                    setBusyId(account.id);
                    try {
                      const result = await syncEmailAccount(account.id);
                      setMessage(result.message);
                      await loadRuns(account.id);
                    } catch (err) {
                      setError(err instanceof Error ? err.message : "Email sync failed");
                    } finally {
                      setBusyId(null);
                    }
                  }}
                  disabled={busyId === account.id}
                  type="button"
                >
                  Sync
                </button>
                <button
                  className="rounded border border-slate-700 px-3 py-1.5 text-sm"
                  onClick={async () => {
                    try {
                      await updateEmailAccount(account.id, { is_primary: true });
                      setMessage("Primary account updated.");
                      await loadAccounts();
                    } catch (err) {
                      setError(err instanceof Error ? err.message : "Failed to set primary account");
                    }
                  }}
                  type="button"
                >
                  Set Primary
                </button>
                <button
                  className="rounded border border-red-500/70 px-3 py-1.5 text-sm text-red-300"
                  onClick={async () => {
                    if (!window.confirm("Delete this email account? This action cannot be undone.")) {
                      return;
                    }
                    try {
                      const result = await deleteEmailAccount(account.id);
                      setMessage(result.message);
                      await loadAccounts();
                    } catch (err) {
                      setError(err instanceof Error ? err.message : "Failed to delete email account");
                    }
                  }}
                  type="button"
                >
                  Delete
                </button>
              </div>
            </article>
          ))}
        </section>

        <ConnectorRuns status={selectedAccount?.status ?? null} runs={runs} />
      </div>
    </main>
  );
}
