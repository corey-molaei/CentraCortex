import type { AgentDefinition } from "../types/agents";
import type { SpecVersion, SpecVersionDetail } from "../types/agentBuilder";
import { sessionStore } from "./session";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

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

  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json() as Promise<T>;
}

export function listBuilderAgents() {
  return request<AgentDefinition[]>("/api/v1/agent-builder/agents");
}

export function createBuilderAgent(payload: { name: string; description?: string }) {
  return request<AgentDefinition>("/api/v1/agent-builder/agents", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function uploadBuilderExamples(agentId: string, files: File[]) {
  const form = new FormData();
  for (const file of files) {
    form.append("files", file);
  }
  return request<{ uploaded_count: number; message: string }>(`/api/v1/agent-builder/agents/${agentId}/examples/upload`, {
    method: "POST",
    body: form
  });
}

export function generateSpecVersion(agentId: string, payload: {
  prompt: string;
  selected_tools: string[];
  selected_data_sources: string[];
  risk_level: "low" | "medium" | "high" | "critical";
  example_texts: string[];
  generate_tests_count: number;
}) {
  return request<SpecVersion>(`/api/v1/agent-builder/agents/${agentId}/generate`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function listAgentSpecVersions(agentId: string) {
  return request<SpecVersion[]>(`/api/v1/agent-builder/agents/${agentId}/versions`);
}

export function getSpecVersion(versionId: string) {
  return request<SpecVersionDetail>(`/api/v1/agent-builder/versions/${versionId}`);
}

export function updateSpecVersion(versionId: string, specJson: unknown) {
  return request<SpecVersion>(`/api/v1/agent-builder/versions/${versionId}`, {
    method: "PATCH",
    body: JSON.stringify({ spec_json: specJson })
  });
}

export function deploySpecVersion(versionId: string) {
  return request<{ status: string; version: SpecVersion }>(`/api/v1/agent-builder/versions/${versionId}/deploy`, {
    method: "POST"
  });
}

export function rollbackSpecVersion(agentId: string, targetVersionId: string, note?: string) {
  return request<{ status: string; version: SpecVersion }>(`/api/v1/agent-builder/agents/${agentId}/rollback`, {
    method: "POST",
    body: JSON.stringify({ target_version_id: targetVersionId, note })
  });
}
