import { sessionStore } from "./session";
import { API_BASE_URL } from "./base";
import type { AgentDefinition, AgentRun, AgentRunDetail, ToolApproval } from "../types/agents";

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

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers
  });

  if (!response.ok) {
    throw new Error(await response.text());
  }

  return response.json() as Promise<T>;
}

export function listAgents() {
  return request<AgentDefinition[]>("/api/v1/agents/catalog");
}

export function createAgent(payload: {
  name: string;
  description?: string;
  system_prompt: string;
  default_agent_type: "knowledge" | "comms" | "ops" | "sql" | "guard";
  allowed_tools: string[];
  enabled: boolean;
  config_json: Record<string, unknown>;
}) {
  return request<AgentDefinition>("/api/v1/agents/catalog", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function updateAgent(agentId: string, payload: Record<string, unknown>) {
  return request<AgentDefinition>(`/api/v1/agents/catalog/${agentId}`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export function deleteAgent(agentId: string) {
  return request<{ message: string }>(`/api/v1/agents/catalog/${agentId}`, {
    method: "DELETE"
  });
}

export function runAgent(payload: {
  agent_id: string;
  input_text: string;
  tool_inputs?: Record<string, Record<string, unknown>>;
  metadata_json?: Record<string, unknown>;
}) {
  return request<AgentRun>("/api/v1/agents/runs", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function listAgentRuns(limit = 50) {
  return request<AgentRun[]>(`/api/v1/agents/runs?limit=${limit}`);
}

export function getAgentRun(runId: string) {
  return request<AgentRunDetail>(`/api/v1/agents/runs/${runId}`);
}

export function listApprovals(status?: string) {
  const suffix = status ? `?status=${encodeURIComponent(status)}` : "";
  return request<ToolApproval[]>(`/api/v1/agents/approvals${suffix}`);
}

export function approveRunTool(approvalId: string, note?: string) {
  return request<ToolApproval>(`/api/v1/agents/approvals/${approvalId}/approve`, {
    method: "POST",
    body: JSON.stringify({ note })
  });
}

export function rejectRunTool(approvalId: string, note?: string) {
  return request<ToolApproval>(`/api/v1/agents/approvals/${approvalId}/reject`, {
    method: "POST",
    body: JSON.stringify({ note })
  });
}
