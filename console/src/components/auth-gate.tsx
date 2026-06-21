import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { operatorApi } from "@/api/operator";
import { ApiError } from "@/api/client";
import { useApiQuery } from "@/hooks/useApi";
import { Skeleton } from "@/components/ui";

export function AuthGate({ children }: { children: ReactNode }) {
  const location = useLocation();
  const sessionQ = useApiQuery(["operator", "session"], () => operatorApi.sessionStatus(), { retry: 0 });

  if (sessionQ.error instanceof ApiError && [401, 403].includes(sessionQ.error.status)) {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  }

  if (sessionQ.isLoading || !sessionQ.data) {
    return (
      <div className="min-h-screen p-10">
        <div className="max-w-2xl mx-auto space-y-3">
          <Skeleton className="h-10" />
          <Skeleton className="h-40" />
        </div>
      </div>
    );
  }

  const session = sessionQ.data;
  const authRequired = session.auth_required === true;
  const authenticated = session.status === "authenticated";
  if (authRequired && !authenticated) {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  }
  return <>{children}</>;
}
