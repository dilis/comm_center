import type { ReactNode } from "react";

export function PageHeader({ title, actions }: { title: string; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b pb-3">
      <h1 className="text-xl font-semibold tracking-tight text-primary">{title}</h1>
      <div className="flex items-center gap-2">{actions}</div>
    </div>
  );
}

export function FieldError({ message }: { message?: string }) {
  return message ? <p className="text-xs text-destructive">{message}</p> : null;
}
