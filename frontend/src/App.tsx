import type { ReactNode } from "react";
import { Route, Routes } from "react-router";
import { RequireAuth, RequirePermission } from "./auth/RequireAuth";
import { Layout } from "./components/Layout";
import { ActionsPage } from "./pages/ActionsPage";
import { ApprovalsPage } from "./pages/ApprovalsPage";
import { DemoPage } from "./pages/DemoPage";
import { EvaluationsPage } from "./pages/EvaluationsPage";
import { GovernancePage } from "./pages/GovernancePage";
import { IncidentDetailPage } from "./pages/IncidentDetailPage";
import { IncidentsPage } from "./pages/IncidentsPage";
import { InvestigationPage } from "./pages/InvestigationPage";
import { InvestigationsPage } from "./pages/InvestigationsPage";
import { DocumentPage, KnowledgePage } from "./pages/KnowledgePage";
import { LoginPage } from "./pages/LoginPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { ObservabilityPage } from "./pages/ObservabilityPage";
import { OverviewPage } from "./pages/OverviewPage";
import { SettingsPage } from "./pages/SettingsPage";

const guarded = (permission: string, page: ReactNode) => <RequirePermission permission={permission}>{page}</RequirePermission>;

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth><Layout /></RequireAuth>}>
        <Route index element={guarded("dashboard:read", <OverviewPage />)} />
        <Route path="incidents" element={guarded("incidents:read", <IncidentsPage />)} />
        <Route path="incidents/:incidentId" element={guarded("incidents:read", <IncidentDetailPage />)} />
        <Route path="investigations" element={guarded("investigations:read", <InvestigationsPage />)} />
        <Route path="investigations/:runId" element={guarded("investigations:read", <InvestigationPage />)} />
        <Route path="approvals" element={guarded("approvals:read", <ApprovalsPage />)} />
        <Route path="actions" element={guarded("actions:read", <ActionsPage />)} />
        <Route path="knowledge" element={guarded("knowledge:read", <KnowledgePage />)} />
        <Route path="knowledge/:docId" element={guarded("knowledge:read", <DocumentPage />)} />
        <Route path="governance" element={guarded("governance:read", <GovernancePage />)} />
        <Route path="evaluations" element={guarded("evaluations:read", <EvaluationsPage />)} />
        <Route path="observability" element={guarded("observability:read", <ObservabilityPage />)} />
        <Route path="settings" element={guarded("settings:read", <SettingsPage />)} />
        <Route path="demo" element={guarded("incidents:read", <DemoPage />)} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
