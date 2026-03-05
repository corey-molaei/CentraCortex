import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getCurrentTenant, getSession } from "../api/client";
import { listConversations } from "../api/llm";
import { getWorkspaceGoogleConfig, listChannelConnectors } from "../api/workspace";
import { Alert } from "../components/ui/Alert";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/Card";
import { PageContainer } from "../layout/PageContainer";
import type { Tenant, UserSession } from "../types/auth";
import type { ConversationSummary } from "../types/llm";
import type { ChannelConnector, WorkspaceGoogleIntegration } from "../types/workspace";

const shortcuts = [
  { label: "Users", to: "/admin/users" },
  { label: "Groups", to: "/admin/groups" },
  { label: "Roles", to: "/admin/roles" },
  { label: "Policies", to: "/admin/policies" },
  { label: "AI Models", to: "/settings/ai-models" },
  { label: "Chat", to: "/chat" },
  { label: "Agents", to: "/agents" },
  { label: "Agent Builder", to: "/agent-builder" },
  { label: "Governance", to: "/governance" },
  { label: "Documents", to: "/documents" },
  { label: "Connectors", to: "/connectors" }
];

export function HomePage() {
  const [session, setSession] = useState<UserSession | null>(null);
  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [workspaceGoogle, setWorkspaceGoogle] = useState<WorkspaceGoogleIntegration | null>(null);
  const [channels, setChannels] = useState<ChannelConnector[]>([]);
  const [recentConversations, setRecentConversations] = useState<ConversationSummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [sessionData, currentTenant, googleCfg, channelRows, conversations] = await Promise.all([
        getSession(),
        getCurrentTenant(),
        getWorkspaceGoogleConfig().catch(() => null),
        listChannelConnectors().catch(() => []),
        listConversations().catch(() => [])
      ]);
      setSession(sessionData);
      setTenant(currentTenant);
      setWorkspaceGoogle(googleCfg);
      setChannels(channelRows);
      setRecentConversations(conversations.slice(0, 5));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed loading dashboard");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <PageContainer>
      {error && (
        <Alert title="Dashboard Error" variant="danger">
          {error}
        </Alert>
      )}

      {session && (
        <div className="grid gap-4 lg:grid-cols-3">
          <Card className="lg:col-span-1">
            <CardHeader>
              <CardTitle>Session</CardTitle>
              <CardDescription>Tenant-isolated session context for your account.</CardDescription>
            </CardHeader>
            <CardContent className="text-sm text-slate-200">
              <p>User: {session.email}</p>
              <p>Full name: {session.full_name ?? "-"}</p>
              <p>Active tenant: {tenant?.name ?? "N/A"}</p>
              <p>Memberships: {session.memberships.length}</p>
            </CardContent>
          </Card>

          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle>Quick Access</CardTitle>
              <CardDescription>Navigate directly to module administration and operations pages.</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-2 md:grid-cols-3">
              {shortcuts.map((shortcut) => (
                <Link
                  className="rounded-xl border border-white/10 bg-white/5 px-3 py-3 text-sm font-medium text-slate-100 transition hover:bg-white/10"
                  key={shortcut.to}
                  to={shortcut.to}
                >
                  {shortcut.label}
                </Link>
              ))}
            </CardContent>
          </Card>

          <Card className="lg:col-span-1">
            <CardHeader>
              <CardTitle>Google Workspace</CardTitle>
              <CardDescription>Shared automation account for channel workflows.</CardDescription>
            </CardHeader>
            <CardContent className="text-sm text-slate-200">
              <p>Connected: {workspaceGoogle?.is_oauth_connected ? "Yes" : "No"}</p>
              <p>Account: {workspaceGoogle?.google_account_email ?? "-"}</p>
              <p>Last sync: {workspaceGoogle?.status.last_sync_at ?? "-"}</p>
              <p>Last error: {workspaceGoogle?.status.last_error ?? "-"}</p>
              <Link className="mt-3 inline-block text-accent underline" to="/connectors/google-workspace">
                Open integration
              </Link>
            </CardContent>
          </Card>

          <Card className="lg:col-span-1">
            <CardHeader>
              <CardTitle>Channel Status</CardTitle>
              <CardDescription>Telegram, WhatsApp, and Facebook connector readiness.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-1 text-sm text-slate-200">
              {channels.length === 0 && <p>No channels configured.</p>}
              {channels.map((channel) => (
                <p key={channel.channel}>
                  {channel.channel}: {channel.configured ? "configured" : "not configured"} /{" "}
                  {channel.enabled ? "enabled" : "disabled"}
                </p>
              ))}
              <Link className="mt-3 inline-block text-accent underline" to="/channels">
                Open channels
              </Link>
            </CardContent>
          </Card>

          <Card className="lg:col-span-1">
            <CardHeader>
              <CardTitle>Recent Conversations</CardTitle>
              <CardDescription>Latest conversations in this workspace.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-1 text-sm text-slate-200">
              {recentConversations.length === 0 && <p>No recent conversations.</p>}
              {recentConversations.map((conversation) => (
                <p key={conversation.id}>{conversation.title}</p>
              ))}
              <Link className="mt-3 inline-block text-accent underline" to="/chat">
                Open chat
              </Link>
            </CardContent>
          </Card>
        </div>
      )}
    </PageContainer>
  );
}
