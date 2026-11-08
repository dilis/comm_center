import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { api, errorMessage, unwrap } from "@/api/client";
import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { SearchBox } from "@/components/SearchBox";
import { Badge } from "@/components/ui/badge";
import { Select } from "@/components/ui/input";
import { Tabs } from "@/components/ui/tabs";
import { useListParams } from "@/lib/useListParams";
import type { components } from "@/api/schema";
import { formatDateTime } from "@/lib/utils";

type Activity = components["schemas"]["ActivityOut"];
type SignIn = components["schemas"]["LoginOut"];

const ACTIONS = ["create", "update", "delete", "send", "send_bulk", "reply", "unlock", "change_password"];
const EVENTS = ["login", "login_failed", "login_blocked", "logout", "sessions_revoked"];
const EVENT_VARIANT: Record<string, "success" | "warning" | "destructive" | "secondary"> = {
  login: "success", login_failed: "warning", login_blocked: "destructive", logout: "secondary", sessions_revoked: "destructive",
};

const activityColumns: Column<Activity>[] = [
  { id: "when", header: "When", cell: (e) => formatDateTime(e.created_at) },
  { id: "who", header: "Person", cell: (e) => <span title={e.username}>{e.name}</span> },
  { id: "action", header: "Action", cell: (e) => <Badge>{e.action}</Badge> },
  { id: "resource", header: "Resource", cell: (e) => e.resource },
  { id: "summary", header: "Details", cell: (e) => <span className="break-words">{e.summary}</span> },
  { id: "ip", header: "Address", cell: (e) => e.ip },
];

const signInColumns: Column<SignIn>[] = [
  { id: "when", header: "When", cell: (e) => formatDateTime(e.created_at) },
  { id: "username", header: "Username", cell: (e) => <span className="font-medium">{e.username}</span> },
  { id: "event", header: "Event", cell: (e) => <Badge variant={EVENT_VARIANT[e.event] ?? "secondary"}>{e.event}</Badge> },
  { id: "ip", header: "Address", cell: (e) => e.ip },
];

export default function LogsPage() {
  const list = useListParams({ sort: "created_at", order: "desc", filters: ["tab", "q", "action"] });
  const { q, action } = list.filters;
  const tab = list.filters.tab === "logins" ? "logins" : "activity";

  const activity = useQuery({
    queryKey: ["logs", "activity", list.page, list.pageSize, q, action],
    enabled: tab === "activity",
    queryFn: () =>
      unwrap(
        api.GET("/logs/activity", {
          params: { query: { page: list.page, page_size: list.pageSize, q: q || undefined, action: action || undefined } },
        }),
      ),
    placeholderData: keepPreviousData,
  });
  const logins = useQuery({
    queryKey: ["logs", "logins", list.page, list.pageSize, q, action],
    enabled: tab === "logins",
    queryFn: () =>
      unwrap(
        api.GET("/logs/logins", {
          params: { query: { page: list.page, page_size: list.pageSize, q: q || undefined, event: action || undefined } },
        }),
      ),
    placeholderData: keepPreviousData,
  });

  const switchTab = (value: string) => {
    list.setFilters({ tab: value === "activity" ? "" : value, q: "", action: "" });
  };
  const shared = {
    page: list.page, pageSize: list.pageSize, sort: { key: "created_at", order: "desc" as const },
    onPageChange: list.setPage, onPageSizeChange: list.setPageSize,
  };

  return (
    <>
      <PageHeader title="Logs" />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Tabs
          label="Log type"
          value={tab}
          onChange={switchTab}
          items={[
            { value: "activity", label: "Activity" },
            { value: "logins", label: "Sign-ins" },
          ]}
        />
        <SearchBox
          label="Search logs"
          placeholder={tab === "activity" ? "Search details or username" : "Search username or address"}
          value={q}
          onChange={(v) => list.setFilter("q", v)}
        />
        <label className="flex items-center gap-2 text-sm">
          {tab === "activity" ? "Action" : "Event"}
          <Select className="w-44" value={action} onChange={(e) => list.setFilter("action", e.target.value)}>
            <option value="">All</option>
            {(tab === "activity" ? ACTIONS : EVENTS).map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </Select>
        </label>
      </div>
      {tab === "activity" ? (
        <DataTable
          {...shared}
          label="Activity"
          columns={activityColumns}
          rows={activity.data?.items}
          total={activity.data?.total ?? 0}
          isLoading={activity.isPending}
          error={activity.error ? errorMessage(activity.error) : null}
          emptyMessage="No activity recorded."
          getRowId={(e) => e.id}
        />
      ) : (
        <DataTable
          {...shared}
          label="Sign-ins"
          columns={signInColumns}
          rows={logins.data?.items}
          total={logins.data?.total ?? 0}
          isLoading={logins.isPending}
          error={logins.error ? errorMessage(logins.error) : null}
          emptyMessage="No sign-ins recorded."
          getRowId={(e) => e.id}
        />
      )}
    </>
  );
}
