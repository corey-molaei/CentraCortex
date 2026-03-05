import { Link } from "react-router-dom";
import { Badge } from "../../components/ui/Badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/Card";
import { PageContainer } from "../../layout/PageContainer";

const CONNECTOR_LINKS = [
  { path: "/connectors/jira", label: "Jira", state: "Configured" },
  { path: "/connectors/slack", label: "Slack", state: "Configured" },
  { path: "/connectors/google-workspace", label: "Google Workspace Integration", state: "Workspace Shared" },
  { path: "/connectors/google", label: "Google (Gmail + Calendar)", state: "Per-user" },
  { path: "/connectors/email", label: "Email", state: "Configured" },
  { path: "/connectors/code-repo", label: "GitHub/GitLab", state: "Configured" },
  { path: "/connectors/confluence", label: "Confluence", state: "Configured" },
  { path: "/connectors/sharepoint", label: "SharePoint/Graph", state: "Configured" },
  { path: "/connectors/db", label: "DB Read-only", state: "Configured" },
  { path: "/connectors/logs", label: "Logs", state: "Configured" },
  { path: "/connectors/file-upload", label: "File Upload", state: "Configured" }
];

export function ConnectorsHubPage() {
  return (
    <PageContainer>
      <Card>
        <CardHeader>
          <CardTitle>Connectors</CardTitle>
          <CardDescription>
            Each connector has a dedicated setup wizard, connection test, and sync status timeline.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {CONNECTOR_LINKS.map((connector) => (
            <Link
              className="rounded-xl border border-white/10 bg-white/5 p-4 transition hover:bg-white/10"
              key={connector.path}
              to={connector.path}
            >
              <div className="mb-2 flex items-center justify-between">
                <h2 className="text-lg font-semibold text-white">{connector.label}</h2>
                <Badge variant="info">{connector.state}</Badge>
              </div>
              <p className="text-sm text-slate-300">Open setup wizard</p>
            </Link>
          ))}
        </CardContent>
      </Card>
    </PageContainer>
  );
}
