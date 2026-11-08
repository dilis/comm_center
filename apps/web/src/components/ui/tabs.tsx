import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export type TabItem = { value: string; label: string; count?: number; icon?: ReactNode };

/** Link-style tab list (role=tablist). The active panel is rendered by the caller. */
export function Tabs({
  items,
  value,
  onChange,
  label,
}: {
  items: TabItem[];
  value: string;
  onChange: (value: string) => void;
  label: string;
}) {
  return (
    <div role="tablist" aria-label={label} className="inline-flex max-w-full overflow-x-auto rounded-lg bg-muted p-1">
      {items.map((item) => (
        <button
          key={item.value}
          role="tab"
          type="button"
          aria-selected={item.value === value}
          onClick={() => onChange(item.value)}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-md px-3 py-1 text-sm font-medium text-muted-foreground transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            item.value === value && "bg-background text-foreground shadow-sm",
          )}
        >
          {item.icon}
          {item.label}
          {item.count !== undefined && (
            <>
              {" "}
              <span className="ml-1 text-xs text-muted-foreground">{item.count}</span>
            </>
          )}
        </button>
      ))}
    </div>
  );
}
