import { Navigate, Route, Routes } from "react-router-dom";
import { sessionStore } from "./api/session";
import { AuthGuard } from "./components/AuthGuard";
import { DashboardLayout } from "./layout/DashboardLayout";
import { AdminUsersPage } from "./pages/AdminUsersPage";
import { AIModelsPage } from "./pages/AIModelsPage";
import { AgentCatalogPage } from "./pages/AgentCatalogPage";
import { AgentTracePage } from "./pages/AgentTracePage";
import { AgentBuilderPage } from "./pages/AgentBuilderPage";
import { ChannelsPage } from "./pages/ChannelsPage";
import { ChatPage } from "./pages/ChatPage";
import { CodeRepoConnectorPage } from "./pages/connectors/CodeRepoConnectorPage";
import { ConfluenceConnectorPage } from "./pages/connectors/ConfluenceConnectorPage";
import { ConnectorsHubPage } from "./pages/connectors/ConnectorsHubPage";
import { DBConnectorPage } from "./pages/connectors/DBConnectorPage";
import { EmailConnectorPage } from "./pages/connectors/EmailConnectorPage";
import { FileUploadConnectorPage } from "./pages/connectors/FileUploadConnectorPage";
import { GoogleConnectorPage } from "./pages/connectors/GoogleConnectorPage";
import { GoogleWorkspaceConnectorPage } from "./pages/connectors/GoogleWorkspaceConnectorPage";
import { JiraConnectorPage } from "./pages/connectors/JiraConnectorPage";
import { LogsConnectorPage } from "./pages/connectors/LogsConnectorPage";
import { SharePointConnectorPage } from "./pages/connectors/SharePointConnectorPage";
import { SlackConnectorPage } from "./pages/connectors/SlackConnectorPage";
import { DocumentDetailPage } from "./pages/DocumentDetailPage";
import { DocumentsPage } from "./pages/DocumentsPage";
import { GroupDetailPage } from "./pages/GroupDetailPage";
import { GroupsPage } from "./pages/GroupsPage";
import { GovernancePage } from "./pages/GovernancePage";
import { HomePage } from "./pages/HomePage";
import { KnowledgeHealthPage } from "./pages/KnowledgeHealthPage";
import { LoginPage } from "./pages/LoginPage";
import { GoogleLoginCallbackPage } from "./pages/GoogleLoginCallbackPage";
import { PoliciesPage } from "./pages/PoliciesPage";
import { ProfilePage } from "./pages/ProfilePage";
import { RecipesPage } from "./pages/RecipesPage";
import { RolesPage } from "./pages/RolesPage";
import { RunAgentPage } from "./pages/RunAgentPage";
import { UserDetailPage } from "./pages/UserDetailPage";
import { CodexOAuthCallbackPage } from "./pages/CodexOAuthCallbackPage";
import { WorkspaceSettingsPage } from "./pages/WorkspaceSettingsPage";

export function App() {
  const isAuthenticated = Boolean(sessionStore.getAccessToken());

  return (
    <Routes>
      <Route element={<CodexOAuthCallbackPage />} path="/auth/callback" />
      <Route element={<GoogleLoginCallbackPage />} path="/login/google/callback" />
      <Route element={isAuthenticated ? <Navigate replace to="/" /> : <LoginPage />} path="/login" />
      <Route
        element={
          <AuthGuard>
            <DashboardLayout />
          </AuthGuard>
        }
      >
        <Route element={<HomePage />} path="/" />
        <Route element={<ProfilePage />} path="/profile" />
        <Route element={<AdminUsersPage />} path="/admin/users" />
        <Route element={<UserDetailPage />} path="/admin/users/:userId" />
        <Route element={<GroupsPage />} path="/admin/groups" />
        <Route element={<GroupDetailPage />} path="/admin/groups/:groupId" />
        <Route element={<RolesPage />} path="/admin/roles" />
        <Route element={<PoliciesPage />} path="/admin/policies" />
        <Route element={<AIModelsPage />} path="/settings/ai-models" />
        <Route element={<WorkspaceSettingsPage />} path="/settings/workspace" />
        <Route element={<AgentCatalogPage />} path="/agents" />
        <Route element={<RunAgentPage />} path="/agents/run" />
        <Route element={<AgentTracePage />} path="/agents/runs/:runId" />
        <Route element={<AgentBuilderPage />} path="/agent-builder" />
        <Route element={<GovernancePage />} path="/governance" />
        <Route element={<ChannelsPage />} path="/channels" />
        <Route element={<ChatPage />} path="/chat" />
        <Route element={<DocumentsPage />} path="/documents" />
        <Route element={<DocumentDetailPage />} path="/documents/:documentId" />
        <Route element={<KnowledgeHealthPage />} path="/knowledge/health" />
        <Route element={<RecipesPage />} path="/recipes" />
        <Route element={<ConnectorsHubPage />} path="/connectors" />
        <Route element={<JiraConnectorPage />} path="/connectors/jira" />
        <Route element={<SlackConnectorPage />} path="/connectors/slack" />
        <Route element={<GoogleConnectorPage />} path="/connectors/google" />
        <Route element={<GoogleWorkspaceConnectorPage />} path="/connectors/google-workspace" />
        <Route element={<EmailConnectorPage />} path="/connectors/email" />
        <Route element={<CodeRepoConnectorPage />} path="/connectors/code-repo" />
        <Route element={<ConfluenceConnectorPage />} path="/connectors/confluence" />
        <Route element={<SharePointConnectorPage />} path="/connectors/sharepoint" />
        <Route element={<DBConnectorPage />} path="/connectors/db" />
        <Route element={<LogsConnectorPage />} path="/connectors/logs" />
        <Route element={<FileUploadConnectorPage />} path="/connectors/file-upload" />
      </Route>
      <Route element={<Navigate replace to={isAuthenticated ? "/" : "/login"} />} path="*" />
    </Routes>
  );
}
