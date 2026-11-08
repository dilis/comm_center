import { useQuery } from "@tanstack/react-query";
import { TriangleAlert } from "lucide-react";

import { api, unwrap } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { formatDateTime } from "@/lib/utils";

const CHECK_MS = 10_000;

/** Says so when a modem is in error or offline (queued messages wait until it is back). Shown
 *  only to people who can read every message, the same people the API lets see `/devices`. */
export function DeviceAlert() {
  const { can } = useAuth();
  const allowed = can("messages:read_all");
  const devices = useQuery({
    queryKey: ["devices"],
    queryFn: () => unwrap(api.GET("/devices")),
    enabled: allowed,
    refetchInterval: CHECK_MS,
    refetchOnWindowFocus: true,
  });
  const troubled = (devices.data ?? []).filter((d) => d.status !== "online");
  if (!allowed || troubled.length === 0) return null;
  return (
    <div role="alert" className="mb-4 space-y-1 rounded-md border border-destructive/50 bg-destructive/10 p-3 text-sm">
      {troubled.map((d) => (
        <p key={d.id} className="flex items-start gap-2">
          <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-destructive" aria-hidden />
          <span>
            <strong>{d.name}</strong> ({d.phone_number}) is {d.status}
            {d.status === "offline" ? "; queued messages wait until it is back" : ""}.
            {d.last_error && (
              <span className="block text-muted-foreground">
                Last error{d.last_error_at ? ` (${formatDateTime(d.last_error_at)})` : ""}: {d.last_error}
              </span>
            )}
          </span>
        </p>
      ))}
    </div>
  );
}
