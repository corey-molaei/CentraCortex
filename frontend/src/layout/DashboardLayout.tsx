import { useCallback, useEffect, useState } from "react";
import { Outlet } from "react-router-dom";
import { getSession } from "../api/client";
import { Alert } from "../components/ui/Alert";
import type { UserSession } from "../types/auth";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

export function DashboardLayout() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [desktopOpen, setDesktopOpen] = useState(() => {
    const stored = window.localStorage.getItem("cc_sidebar_open");
    if (stored === null) {
      return true;
    }
    return stored === "1";
  });
  const [loadingSession, setLoadingSession] = useState(false);
  const [session, setSession] = useState<UserSession | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadSession = useCallback(async () => {
    setLoadingSession(true);
    setError(null);
    try {
      const data = await getSession();
      setSession(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load session");
    } finally {
      setLoadingSession(false);
    }
  }, []);

  useEffect(() => {
    loadSession().catch((err) => {
      setError(err instanceof Error ? err.message : "Failed to load session");
      setLoadingSession(false);
    });
  }, [loadSession]);

  useEffect(() => {
    window.localStorage.setItem("cc_sidebar_open", desktopOpen ? "1" : "0");
  }, [desktopOpen]);

  const toggleMenu = useCallback(() => {
    if (typeof window !== "undefined" && window.matchMedia && window.matchMedia("(min-width: 768px)").matches) {
      setDesktopOpen((value) => !value);
      return;
    }
    setMobileOpen((value) => !value);
  }, []);

  return (
    <div
      className={`min-h-screen bg-transparent md:grid ${desktopOpen ? "md:grid-cols-[18rem_1fr]" : "md:grid-cols-[1fr]"}`}
    >
      <Sidebar desktopOpen={desktopOpen} open={mobileOpen} onClose={() => setMobileOpen(false)} />
      <div className="min-h-screen">
        <Topbar
          loadingSession={loadingSession}
          onMenuToggle={toggleMenu}
          onTenantChanged={loadSession}
          sidebarOpen={desktopOpen}
          session={session}
        />
        {error && (
          <div className="px-4 pt-4 md:px-6">
            <Alert title="Session Warning" variant="warning">
              {error}
            </Alert>
          </div>
        )}
        <Outlet />
      </div>
    </div>
  );
}
