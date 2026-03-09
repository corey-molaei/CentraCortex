import type { ChunkSearchResultItem, DocumentDetail, DocumentListItem, ReindexResponse } from "../types/documents";
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

export interface DocumentListFilters {
  source_type?: string;
  tag?: string;
  acl_policy_id?: string;
  created_from?: string;
  created_to?: string;
  q?: string;
}

function toQueryString(filters: DocumentListFilters) {
  const search = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value) {
      search.set(key, value);
    }
  });
  const query = search.toString();
  return query ? `?${query}` : "";
}

export function listDocuments(filters: DocumentListFilters) {
  return request<DocumentListItem[]>(`/api/v1/documents${toQueryString(filters)}`);
}

export function getDocument(documentId: string) {
  return request<DocumentDetail>(`/api/v1/documents/${documentId}`);
}

export function reindexDocument(documentId: string) {
  return request<ReindexResponse>(`/api/v1/documents/${documentId}/reindex`, { method: "POST" });
}

export function reindexDocuments(payload: { document_ids: string[]; source_type?: string; acl_policy_id?: string }) {
  return request<ReindexResponse>("/api/v1/documents/reindex", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function forgetDocument(documentId: string) {
  return request<{ status: string; document_id: string }>(`/api/v1/documents/${documentId}`, {
    method: "DELETE"
  });
}

export function searchDocumentChunks(query: string, limit = 8) {
  return request<{ results: ChunkSearchResultItem[] }>("/api/v1/documents/search", {
    method: "POST",
    body: JSON.stringify({ query, limit })
  });
}
