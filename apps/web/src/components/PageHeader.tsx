import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/** `compactOnMobile` drops the title bar on a phone (the nav already names the page) so the list
 *  gets the space; the actions stay in the DOM for the page to place itself (e.g. a floating button). */
export function PageHeader({ title, actions, compactOnMobile }: { title: string; actions?: ReactNode; compactOnMobile?: boolean }) {
  return (
    <div className={cn("mb-5 flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b pb-3", compactOnMobile && "max-md:m-0 max-md:border-0 max-md:p-0")}>
      <h1 className={cn("text-xl font-semibold tracking-tight text-primary", compactOnMobile && "max-md:sr-only")}>{title}</h1>
      <div className="flex items-center gap-2">{actions}</div>
    </div>
  );
}

export function FieldError({ message }: { message?: string }) {
  return message ? <p className="text-xs text-destructive">{message}</p> : null;
}
