import { useMemo } from "react";
import { switchTenant } from "../api/client";
import { sessionStore } from "../api/session";
import type { TenantMembership } from "../types/auth";

type Props = {
  memberships: TenantMembership[];
  onTenantChanged: () => Promise<void>;
};

export function TenantSwitcher({ memberships, onTenantChanged }: Props) {
  const selectedTenant = sessionStore.getTenantId();

  const options = useMemo(
    () => memberships.map((m) => ({ value: m.tenant_id, label: `${m.tenant_name} (${m.role})` })),
    [memberships]
  );

  return (
    <div className="rounded-lg bg-panel p-4">
      <label className="mb-2 block text-sm text-slate-300" htmlFor="tenant-select">
        Active Tenant
      </label>
      <select
        id="tenant-select"
        className="w-full rounded border border-slate-700 bg-slate-900 p-2"
        value={selectedTenant ?? ""}
        onChange={async (e) => {
          const tenantId = e.target.value;
          if (!tenantId) {
            return;
          }
          const switched = await switchTenant(tenantId);
          sessionStore.setTenantId(switched.tenant_id);
          sessionStore.setAccessToken(switched.access_token);
          await onTenantChanged();
        }}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}
