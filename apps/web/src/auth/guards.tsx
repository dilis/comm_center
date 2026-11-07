import { Navigate, Outlet, useLocation } from "react-router";

import { Button } from "@/components/ui/button";

import { useAuth } from "./AuthContext";
import { canReadResource } from "./permissions";

export function RequireAuth() {
  const { status, retry } = useAuth();
  const location = useLocation();
  if (status === "loading") {
    return <p className="p-6 text-sm text-muted-foreground">Loading…</p>;
  }
  if (status === "error") {
    return (
      <div className="flex flex-col items-start gap-3 p-6">
        <p role="alert">Cannot reach the server. Check your connection and try again.</p>
        <Button onClick={retry}>Retry</Button>
      </div>
    );
  }
  if (status === "anonymous") {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  }
  return <Outlet />;
}

/** Renders the page only for callers who may read ``resource`` (the API enforces it again). */
export function RequireRead({ resource }: { resource: "messages" | "contacts" | "users" }) {
  const { permissions } = useAuth();
  if (!canReadResource(permissions, resource)) {
    return <p className="p-6">You don't have access to this page.</p>;
  }
  return <Outlet />;
}
