import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { switchTenant } from "../api/client";
import { sessionStore } from "../api/session";
import { Button } from "../components/ui/Button";
import type { UserSession } from "../types/auth";

type TopbarProps = {
  session: UserSession | null;
  loadingSession: boolean;
  onMenuToggle: () => void;
  onTenantChanged: () => Promise<void>;
  sidebarOpen: boolean;
};

export function Topbar({ session, loadingSession, onMenuToggle, onTenantChanged, sidebarOpen }: TopbarProps) {
  const [switchingTenant, setSwitchingTenant] = useState(false);
  const selectedTenantId = sessionStore.getTenantId() ?? session?.tenant_id ?? "";

  const options = useMemo(() => {
    if (!session) {
      return [];
    }
    return session.memberships.map((membership) => ({
      value: membership.tenant_id,
      label: `${membership.tenant_name} (${membership.role})`
    }));
  }, [session]);

  return (
    <header className="sticky top-0 z-20 flex items-center justify-between border-b border-white/10 bg-ink/70 px-4 py-3 backdrop-blur-md md:px-6">
      <div className="flex items-center gap-3">
        <Button size="sm" variant="secondary" onClick={onMenuToggle}>
          {sidebarOpen ? "Hide Menu" : "Show Menu"}
        </Button>
        <div>
          <p className="text-xs uppercase tracking-[0.16em] text-slate-400">Enterprise Knowledge OS</p>
          <h2 className="text-base font-semibold text-white">CentraCortex Control Plane</h2>
        </div>
      </div>

      <div className="flex items-center gap-2 md:gap-3">
        <div className="hidden md:block">
          <select
            className="w-72 rounded-lg border border-white/15 bg-white/5 px-3 py-2 text-sm text-slate-100"
            disabled={loadingSession || switchingTenant || options.length === 0}
            value={selectedTenantId}
            onChange={async (event) => {
              const tenantId = event.target.value;
              if (!tenantId) {
                return;
              }
              setSwitchingTenant(true);
              try {
                const switched = await switchTenant(tenantId);
                sessionStore.setTenantId(switched.tenant_id);
                sessionStore.setAccessToken(switched.access_token);
                await onTenantChanged();
              } finally {
                setSwitchingTenant(false);
              }
            }}
          >
            {options.map((option) => (
              <option className="bg-ink" key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <Link className="rounded-lg border border-white/15 bg-white/5 px-3 py-2 text-sm text-slate-100 hover:bg-white/10" to="/profile">
          Profile
        </Link>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => {
            sessionStore.clear();
            window.location.href = "/login";
          }}
        >
          Sign out
        </Button>
      </div>
    </header>
  );
}
