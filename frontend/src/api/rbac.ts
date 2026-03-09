import type { Group, InviteResponse, Policy, Role, UserDetail, UserListItem } from "../types/rbac";
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

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers
  });

  if (!response.ok) {
    throw new Error(await response.text());
  }

  return response.json() as Promise<T>;
}

export function listUsers(query?: string) {
  const suffix = query ? `?q=${encodeURIComponent(query)}` : "";
  return request<UserListItem[]>(`/api/v1/admin/users${suffix}`);
}

export function inviteUser(email: string, role: string) {
  return request<InviteResponse>("/api/v1/admin/users/invite", {
    method: "POST",
    body: JSON.stringify({ email, role })
  });
}

export function getUserDetail(userId: string) {
  return request<UserDetail>(`/api/v1/admin/users/${userId}`);
}

export function assignUserGroup(userId: string, groupId: string) {
  return request<{ message: string }>(`/api/v1/admin/users/${userId}/groups`, {
    method: "POST",
    body: JSON.stringify({ group_id: groupId })
  });
}

export function assignUserRole(userId: string, roleId: string) {
  return request<{ message: string }>(`/api/v1/admin/users/${userId}/roles`, {
    method: "POST",
    body: JSON.stringify({ role_id: roleId })
  });
}

export function listGroups() {
  return request<Group[]>("/api/v1/admin/groups");
}

export function getGroup(groupId: string) {
  return request<Group>(`/api/v1/admin/groups/${groupId}`);
}

export function listGroupMembers(groupId: string) {
  return request<UserListItem[]>(`/api/v1/admin/groups/${groupId}/members`);
}

export function createGroup(name: string, description: string) {
  return request<Group>("/api/v1/admin/groups", {
    method: "POST",
    body: JSON.stringify({ name, description })
  });
}

export function listRoles() {
  return request<Role[]>("/api/v1/admin/roles");
}

export function createRole(name: string, description: string) {
  return request<Role>("/api/v1/admin/roles", {
    method: "POST",
    body: JSON.stringify({ name, description })
  });
}

export function listPolicies(policyType?: string) {
  const suffix = policyType ? `?policy_type=${encodeURIComponent(policyType)}` : "";
  return request<Policy[]>(`/api/v1/admin/policies${suffix}`);
}

export function createPolicy(payload: {
  name: string;
  policy_type: "document" | "tool" | "data_source";
  resource_id: string;
  allow_all?: boolean;
  allowed_user_ids?: string[];
  allowed_group_ids?: string[];
  allowed_role_names?: string[];
  active?: boolean;
}) {
  return request<Policy>("/api/v1/admin/policies", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}
