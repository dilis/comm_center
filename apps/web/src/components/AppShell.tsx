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
      <header className="flex items-center gap-6 border-b px-6 py-3">
        <span className="font-semibold">Comm Center</span>
        <nav aria-label="Main" className="flex gap-1">
          {pages.map((p) => (
            <NavLink
              key={p.to}
              to={p.to}
              className={({ isActive }) =>
                cn(
                  "rounded-md px-3 py-1.5 text-sm font-medium text-muted-foreground hover:bg-muted",
                  isActive && "bg-muted text-foreground",
                )
              }
            >
              {p.label}
            </NavLink>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-3 text-sm">
          <span>{me?.name}</span>
          <Button variant="outline" size="sm" onClick={() => void logout()}>
            <LogOut className="h-4 w-4" aria-hidden />
            Sign out
          </Button>
        </div>
      </header>
      <main className="flex-1 p-6">
        <Outlet />
      </main>
    </div>
  );
}
