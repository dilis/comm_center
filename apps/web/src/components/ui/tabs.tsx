import { cn } from "@/lib/utils";

export type TabItem = { value: string; label: string; count?: number };

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
    <div role="tablist" aria-label={label} className="inline-flex rounded-lg bg-muted p-1">
      {items.map((item) => (
        <button
          key={item.value}
          role="tab"
          type="button"
          aria-selected={item.value === value}
          onClick={() => onChange(item.value)}
          className={cn(
            "rounded-md px-3 py-1 text-sm font-medium text-muted-foreground transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            item.value === value && "bg-background text-foreground shadow-sm",
          )}
        >
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
