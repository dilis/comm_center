import { useQuery } from "@tanstack/react-query";

import { api, errorMessage, unwrap } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { isSubset } from "@/auth/permissions";

/** Checkboxes for the seeded groups. A group whose permissions the caller does not hold is
 *  disabled: the API refuses it too, so this only saves a round trip. Renders nothing without
 *  ``groups:read_all``. */
export function GroupPicker({ value, onChange }: { value: number[]; onChange: (ids: number[]) => void }) {
  const { can, permissions } = useAuth();
  const allowed = can("groups:read_all");
  const groups = useQuery({
    queryKey: ["groups"],
    queryFn: () => unwrap(api.GET("/groups", { params: { query: { page_size: 100 } } })),
    enabled: allowed,
    staleTime: 60_000,
  });
  if (!allowed) return null;

  return (
    <fieldset className="space-y-2">
      <legend className="mb-1 text-sm font-medium">Groups</legend>
      {groups.error && (
        <p role="alert" className="text-xs text-destructive">
          {errorMessage(groups.error)}
        </p>
      )}
      <div className="grid grid-cols-2 gap-x-4 gap-y-1">
        {groups.data?.items.map((g) => {
          const assignable = isSubset(g.permissions, permissions);
          const checked = value.includes(g.id);
          return (
            <label key={g.id} className="flex items-center gap-2 text-sm" title={g.permissions.join(", ")}>
              <input
                type="checkbox"
                checked={checked}
                disabled={!assignable}
                onChange={() => onChange(checked ? value.filter((id) => id !== g.id) : [...value, g.id])}
              />
              <span>{g.name}</span>
              {!assignable && <span className="text-xs text-muted-foreground">(needs permissions you don't have)</span>}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
