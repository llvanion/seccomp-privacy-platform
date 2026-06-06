import type { RouteObject } from "react-router-dom";
import { Navigate } from "react-router-dom";

import { AppLayout } from "./components/layout";
import { ErrorBoundary } from "./components/error-boundary";

import { HomeRoute } from "./routes/home";
import { JobsRoute } from "./routes/jobs";
import { JobDetailRoute } from "./routes/jobs.detail";
import { JobStartRoute } from "./routes/jobs.start";
import { RequestsRoute } from "./routes/requests";
import { RequestDetailRoute } from "./routes/requests.detail";
import { RequestSubmitRoute } from "./routes/requests.submit";
import { PrivacyBudgetApprovalsRoute } from "./routes/privacy-budget-approvals";
import { SseQueryRoute } from "./routes/sse-query";
import { PjcOnlyRoute } from "./routes/pjc-only";
import { AuditRoute } from "./routes/audit";
import { CatalogRoute } from "./routes/catalog";
import { BusinessAccessRoute } from "./routes/business-access";
import { PermissionsRoute } from "./routes/permissions";
import { RecoveryRoute } from "./routes/recovery";
import { ObservabilityRoute } from "./routes/observability";
import { ComplianceRoute } from "./routes/compliance";
import { SecurityRoute } from "./routes/security";
import { SettingsRoute } from "./routes/settings";

export const router: RouteObject[] = [
  {
    path: "/",
    element: <AppLayout />,
    errorElement: <ErrorBoundary />,
    children: [
      { index: true, element: <Navigate to="/home" replace /> },
      { path: "home", element: <HomeRoute /> },
      { path: "jobs", element: <JobsRoute /> },
      { path: "jobs/start", element: <JobStartRoute /> },
      { path: "jobs/:jobId", element: <JobDetailRoute /> },
      { path: "requests", element: <RequestsRoute /> },
      { path: "requests/submit", element: <RequestSubmitRoute /> },
      { path: "requests/:submissionId", element: <RequestDetailRoute /> },
      { path: "privacy-budget-approvals", element: <PrivacyBudgetApprovalsRoute /> },
      { path: "sse-query", element: <SseQueryRoute /> },
      { path: "pjc-only", element: <PjcOnlyRoute /> },
      { path: "audit/*", element: <AuditRoute /> },
      { path: "catalog/*", element: <CatalogRoute /> },
      { path: "business-access", element: <BusinessAccessRoute /> },
      { path: "permissions/*", element: <PermissionsRoute /> },
      { path: "recovery/*", element: <RecoveryRoute /> },
      { path: "observability/*", element: <ObservabilityRoute /> },
      { path: "compliance/*", element: <ComplianceRoute /> },
      { path: "security/*", element: <SecurityRoute /> },
      { path: "settings", element: <SettingsRoute /> },
      { path: "*", element: <Navigate to="/home" replace /> },
    ],
  },
];
