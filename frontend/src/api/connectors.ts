import { sessionStore } from "./session";
import { API_BASE_URL } from "./base";
import type { ConnectionTestResult, SyncRun } from "../types/connectors";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = sessionStore.getAccessToken();
  const tenantId = sessionStore.getTenantId();
  const headers = new Headers(init?.headers);
  if (!(init?.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  if (tenantId) {
    headers.set("X-Tenant-ID", tenantId);
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers
  });

  if (!response.ok) {
    let message = await response.text();
    try {
      const parsed = JSON.parse(message) as { detail?: string; message?: string };
      if (parsed.detail) {
        message = parsed.detail;
      } else if (parsed.message) {
        message = parsed.message;
      }
    } catch {
      // Keep raw payload when it is not JSON.
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export function getConnectorConfig<T>(key: string) {
  return request<T | null>(`/api/v1/connectors/${key}/config`);
}

export function putConnectorConfig<T>(key: string, payload: Record<string, unknown>) {
  return request<T>(`/api/v1/connectors/${key}/config`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export function testConnector(key: string) {
  return request<ConnectionTestResult>(`/api/v1/connectors/${key}/test`, { method: "POST" });
}

export function syncConnector(key: string) {
  return request<{ status: string; items_synced: number; message: string }>(`/api/v1/connectors/${key}/sync`, {
    method: "POST"
  });
}

export function connectorStatus(key: string) {
  return request<SyncRun[]>(`/api/v1/connectors/${key}/status`);
}

export function slackOAuthStart(redirectUri: string) {
  const encoded = encodeURIComponent(redirectUri);
  return request<{ auth_url: string; state: string }>(`/api/v1/connectors/slack/oauth/start?redirect_uri=${encoded}`);
}

export function slackOAuthCallback(code: string, state: string) {
  return request<{ message: string }>(`/api/v1/connectors/slack/oauth/callback?code=${encodeURIComponent(code)}&state=${encodeURIComponent(state)}`);
}

export type GoogleAccountPayload = {
  label?: string | null;
  enabled: boolean;
  is_primary?: boolean;
  gmail_enabled: boolean;
  gmail_labels: string[];
  calendar_enabled: boolean;
  calendar_ids: string[];
};

export type GoogleAccountRead = {
  id: string;
  tenant_id: string;
  user_id: string;
  label: string | null;
  google_account_email: string | null;
  google_account_sub: string | null;
  is_oauth_connected: boolean;
  is_primary: boolean;
  scopes: string[];
  gmail_enabled: boolean;
  gmail_labels: string[];
  calendar_enabled: boolean;
  calendar_ids: string[];
  status: {
    enabled: boolean;
    last_sync_at: string | null;
    last_items_synced: number;
    last_error: string | null;
  };
};

export type GoogleCalendarEventPayload = {
  calendar_id: string;
  summary: string;
  description?: string | null;
  location?: string | null;
  start_datetime: string;
  end_datetime: string;
  timezone?: string | null;
  attendees?: string[];
};

export type GoogleCalendarListItem = {
  id: string;
  summary: string;
  primary: boolean;
  access_role?: string | null;
  selected: boolean;
};

export type EmailAccountPayload = {
  label?: string | null;
  email_address: string;
  username: string;
  password?: string;
  imap_host: string;
  imap_port: number;
  use_ssl: boolean;
  smtp_host?: string | null;
  smtp_port?: number | null;
  smtp_use_starttls: boolean;
  folders: string[];
  enabled: boolean;
  is_primary?: boolean;
};

export type EmailAccountRead = {
  id: string;
  tenant_id: string;
  user_id: string;
  label: string | null;
  email_address: string;
  username: string;
  imap_host: string;
  imap_port: number;
  use_ssl: boolean;
  smtp_host: string | null;
  smtp_port: number | null;
  smtp_use_starttls: boolean;
  folders: string[];
  is_primary: boolean;
  status: {
    enabled: boolean;
    last_sync_at: string | null;
    last_items_synced: number;
    last_error: string | null;
  };
};

export function listGoogleAccounts() {
  return request<GoogleAccountRead[]>("/api/v1/connectors/google/accounts");
}

export function createGoogleAccount(payload: GoogleAccountPayload) {
  return request<GoogleAccountRead>("/api/v1/connectors/google/accounts", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function updateGoogleAccount(accountId: string, payload: Partial<GoogleAccountPayload>) {
  return request<GoogleAccountRead>(`/api/v1/connectors/google/accounts/${encodeURIComponent(accountId)}`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export function deleteGoogleAccount(accountId: string) {
  return request<{ message: string; deleted_docs_count: number }>(
    `/api/v1/connectors/google/accounts/${encodeURIComponent(accountId)}`,
    { method: "DELETE" }
  );
}

export function googleOAuthStart(accountId: string, redirectUri: string) {
  const encoded = encodeURIComponent(redirectUri);
  return request<{ auth_url: string; state: string }>(
    `/api/v1/connectors/google/accounts/${encodeURIComponent(accountId)}/oauth/start?redirect_uri=${encoded}`
  );
}

export function googleOAuthCallback(code: string, state: string) {
  return request<{ message: string }>(
    `/api/v1/connectors/google/oauth/callback?code=${encodeURIComponent(code)}&state=${encodeURIComponent(state)}`
  );
}

export function googleTest(accountId: string) {
  return request<ConnectionTestResult>(`/api/v1/connectors/google/accounts/${encodeURIComponent(accountId)}/test`, {
    method: "POST"
  });
}

export function googleSync(accountId: string) {
  return request<{ status: string; items_synced: number; message: string }>(
    `/api/v1/connectors/google/accounts/${encodeURIComponent(accountId)}/sync`,
    { method: "POST" }
  );
}

export function googleStatus(accountId: string) {
  return request<SyncRun[]>(`/api/v1/connectors/google/accounts/${encodeURIComponent(accountId)}/status`);
}

export function googleListCalendars(accountId: string) {
  return request<GoogleCalendarListItem[]>(
    `/api/v1/connectors/google/accounts/${encodeURIComponent(accountId)}/calendars`
  );
}

export function createGoogleCalendarEvent(accountId: string, payload: GoogleCalendarEventPayload) {
  return request<{
    id: string;
    calendar_id: string;
    status: string;
    html_link: string | null;
    summary: string | null;
    start_datetime: string | null;
    end_datetime: string | null;
  }>(`/api/v1/connectors/google/accounts/${encodeURIComponent(accountId)}/calendar/events`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function updateGoogleCalendarEvent(accountId: string, eventId: string, payload: GoogleCalendarEventPayload) {
  return request<{
    id: string;
    calendar_id: string;
    status: string;
    html_link: string | null;
    summary: string | null;
    start_datetime: string | null;
    end_datetime: string | null;
  }>(`/api/v1/connectors/google/accounts/${encodeURIComponent(accountId)}/calendar/events/${encodeURIComponent(eventId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export function deleteGoogleCalendarEvent(accountId: string, eventId: string, calendarId: string) {
  return request<{ message: string }>(
    `/api/v1/connectors/google/accounts/${encodeURIComponent(accountId)}/calendar/events/${encodeURIComponent(eventId)}?calendar_id=${encodeURIComponent(calendarId)}`,
    { method: "DELETE" }
  );
}

export function listEmailAccounts() {
  return request<EmailAccountRead[]>("/api/v1/connectors/email/accounts");
}

export function createEmailAccount(payload: EmailAccountPayload) {
  return request<EmailAccountRead>("/api/v1/connectors/email/accounts", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function updateEmailAccount(accountId: string, payload: Partial<EmailAccountPayload>) {
  return request<EmailAccountRead>(`/api/v1/connectors/email/accounts/${encodeURIComponent(accountId)}`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export function deleteEmailAccount(accountId: string) {
  return request<{ message: string; deleted_docs_count: number }>(
    `/api/v1/connectors/email/accounts/${encodeURIComponent(accountId)}`,
    { method: "DELETE" }
  );
}

export function testEmailAccount(accountId: string) {
  return request<ConnectionTestResult>(`/api/v1/connectors/email/accounts/${encodeURIComponent(accountId)}/test`, {
    method: "POST"
  });
}

export function syncEmailAccount(accountId: string) {
  return request<{ status: string; items_synced: number; message: string }>(
    `/api/v1/connectors/email/accounts/${encodeURIComponent(accountId)}/sync`,
    { method: "POST" }
  );
}

export function emailAccountStatus(accountId: string) {
  return request<SyncRun[]>(`/api/v1/connectors/email/accounts/${encodeURIComponent(accountId)}/status`);
}

export async function uploadFiles(files: File[]) {
  const token = sessionStore.getAccessToken();
  const tenantId = sessionStore.getTenantId();
  const headers = new Headers();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  if (tenantId) {
    headers.set("X-Tenant-ID", tenantId);
  }

  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));

  const response = await fetch(`${API_BASE_URL}/api/v1/connectors/file-upload/upload`, {
    method: "POST",
    headers,
    body: formData
  });

  if (!response.ok) {
    let errorMessage = await response.text();
    try {
      const parsed = JSON.parse(errorMessage) as { detail?: string };
      if (parsed.detail) {
        errorMessage = parsed.detail;
      }
    } catch {
      // Keep raw response text when payload is not JSON.
    }
    throw new Error(errorMessage);
  }
  return response.json() as Promise<{
    status: string;
    items_synced: number;
    document_ids: string[];
    indexing_queued?: boolean;
  }>;
}
