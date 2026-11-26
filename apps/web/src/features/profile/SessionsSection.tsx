import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, errorMessage, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { DataTable, type Column } from "@/components/DataTable";
import { Badge } from "@/components/ui/badge";
import { describeDevice } from "@/lib/userAgent";
import { formatDateTime } from "@/lib/utils";

type Session = components["schemas"]["MySessionOut"];

const columns: Column<Session>[] = [
  {
    id: "device",
    header: "Device",
    cell: (s) => (
      <span className="inline-flex flex-wrap items-center gap-2">
        <span className="break-all" title={s.user_agent ?? undefined}>{describeDevice(s.user_agent)}</span>
        {s.current && <Badge variant="success">This device</Badge>}
      </span>
    ),
  },
  { id: "ip", header: "Address", cell: (s) => s.ip ?? "Unknown" },
  { id: "signed_in", header: "Signed in", cell: (s) => formatDateTime(s.signed_in_at) },
  { id: "active", header: "Last active", cell: (s) => formatDateTime(s.last_active_at) },
];

export function SessionsSection() {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const sessions = useQuery({
    queryKey: ["auth", "sessions", page, pageSize],
    queryFn: () => unwrap(api.GET("/auth/me/sessions", { params: { query: { page, page_size: pageSize } } })),
    placeholderData: keepPreviousData,
  });
  return (
    <DataTable
      label="Sessions"
      columns={columns}
      rows={sessions.data?.items}
      total={sessions.data?.total ?? 0}
      page={page}
      pageSize={pageSize}
      onPageChange={setPage}
      onPageSizeChange={(size) => {
        setPageSize(size);
        setPage(1);
      }}
      isLoading={sessions.isPending}
      error={sessions.error ? errorMessage(sessions.error) : null}
      emptyMessage="No sessions."
      getRowId={(s) => s.id}
    />
  );
}
