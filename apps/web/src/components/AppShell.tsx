import { LogOut } from "lucide-react";
import { NavLink, Navigate, Outlet } from "react-router";

import { useAuth } from "@/auth/AuthContext";
import { canReadResource } from "@/auth/permissions";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const PAGES = [
  { to: "/messages", label: "Messages", resource: "messages" },
  { to: "/contacts", label: "Contacts", resource: "contacts" },
  { to: "/users", label: "Users", resource: "users" },
] as const;

export function useAllowedPages() {
  const { permissions } = useAuth();
  return PAGES.filter((p) => canReadResource(permissions, p.resource));
}

/** The landing route: the first page the caller may read. */
export function Home() {
  const pages = useAllowedPages();
  if (pages.length === 0) {
    return <p className="p-6">You don't have access to any pages. Ask an administrator for a group.</p>;
  }
  return <Navigate to={pages[0].to} replace />;
}

export default function AppShell() {
  const { me, logout } = useAuth();
  const pages = useAllowedPages();
  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex flex-wrap items-center gap-x-8 gap-y-2 border-b-2 border-accent-line bg-brand px-4 py-3 text-brand-foreground shadow-sm sm:px-6">
        <span className="text-sm font-semibold uppercase tracking-[0.14em]">Comm Center</span>
        <nav aria-label="Main" className="order-last flex w-full gap-1 overflow-x-auto sm:order-none sm:w-auto">
          {pages.map((p) => (
            <NavLink
              key={p.to}
              to={p.to}
              className={({ isActive }) =>
                cn(
                  "shrink-0 rounded px-3 py-1.5 text-sm font-medium text-brand-foreground/70 transition-colors hover:bg-white/10 hover:text-brand-foreground",
                  isActive && "bg-white/15 text-brand-foreground",
                )
              }
            >
              {p.label}
            </NavLink>
          ))}
        </nav>
        <div className="ml-auto flex min-w-0 items-center gap-3 text-sm">
          <span className="truncate text-brand-foreground/90">{me?.name}</span>
          <Button variant="outline" size="sm" className="border-white/30 bg-transparent text-brand-foreground hover:bg-white/10" onClick={() => void logout()}>
            <LogOut className="h-4 w-4" aria-hidden />
            Sign out
          </Button>
        </div>
      </header>
      <main className="mx-auto w-full min-w-0 max-w-7xl flex-1 p-4 sm:p-6">
        <Outlet />
      </main>
    </div>
  );
}
