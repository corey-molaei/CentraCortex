import type { ApprovalQueueItem, AuditLogItem } from "../types/governance";
import { sessionStore } from "./session";
import { API_BASE_URL } from "./base";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = sessionStore.getAccessToken();
  const tenantId = sessionStore.getTenantId();
  const headers = new Headers(init?.headers);
  headers.set("Content-Type", "application/json");
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  if (tenantId) {
    headers.set("X-Tenant-ID", tenantId);
  }

  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json() as Promise<T>;
}

function buildQuery(params: Record<string, string | number | undefined>) {
  const q = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === "") {
      continue;
    }
    q.set(key, String(value));
  }
  const encoded = q.toString();
  return encoded ? `?${encoded}` : "";
}

export function listAuditLogs(filters: {
  user_id?: string;
  event_type?: string;
  tool?: string;
  start_at?: string;
  end_at?: string;
  limit?: number;
  offset?: number;
}) {
  return request<AuditLogItem[]>(`/api/v1/governance/audit-logs${buildQuery(filters)}`);
}

export async function exportAuditLogsCsv(filters: {
  user_id?: string;
  event_type?: string;
  tool?: string;
  start_at?: string;
  end_at?: string;
  limit?: number;
}) {
  const token = sessionStore.getAccessToken();
  const tenantId = sessionStore.getTenantId();
  const headers = new Headers();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  if (tenantId) {
    headers.set("X-Tenant-ID", tenantId);
  }

  const response = await fetch(
    `${API_BASE_URL}/api/v1/governance/audit-logs/export${buildQuery(filters)}`,
    { headers }
  );
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.text();
}

export function listApprovalQueue(status = "pending") {
  return request<ApprovalQueueItem[]>(`/api/v1/governance/approval-queue${buildQuery({ status })}`);
}

export function approveQueueItem(approvalId: string, note?: string) {
  return request<ApprovalQueueItem>(`/api/v1/governance/approval-queue/${approvalId}/approve`, {
    method: "POST",
    body: JSON.stringify({ note })
  });
}

export function rejectQueueItem(approvalId: string, note?: string) {
  return request<ApprovalQueueItem>(`/api/v1/governance/approval-queue/${approvalId}/reject`, {
    method: "POST",
    body: JSON.stringify({ note })
  });
}
