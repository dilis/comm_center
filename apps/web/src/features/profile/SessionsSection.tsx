import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, errorMessage, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { useAuth } from "@/auth/AuthContext";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { DataTable, type Column } from "@/components/DataTable";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
  const { logout } = useAuth();
  const queryClient = useQueryClient();
  const [ending, setEnding] = useState<Session | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const sessions = useQuery({
    queryKey: ["auth", "sessions", page, pageSize],
    queryFn: () => unwrap(api.GET("/auth/me/sessions", { params: { query: { page, page_size: pageSize } } })),
    placeholderData: keepPreviousData,
  });
  const end = useMutation({
    mutationFn: (s: Session) =>
      unwrap(api.DELETE("/auth/me/sessions/{session_id}", { params: { path: { session_id: s.id } } })),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["auth", "sessions"] }),
  });
  const withSignOut: Column<Session>[] = [
    ...columns,
    {
      id: "actions",
      header: "",
      hideLabelOnMobile: true,
      cell: (s) => (
        <Button variant="outline" size="sm" onClick={() => setEnding(s)}>
          Sign out
        </Button>
      ),
    },
  ];
  return (
    <>
      <DataTable
        label="Sessions"
        columns={withSignOut}
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
      {ending && (
        <ConfirmDialog
          title="Sign out session"
          description={
            ending.current
              ? "Sign out of this device?"
              : `Sign out ${describeDevice(ending.user_agent)}? It stops getting notifications at once, and may keep working for a few minutes before it asks to sign in again.`
          }
          confirmLabel="Sign out"
          // this device takes the ordinary way out, which also tidies up the browser
          onConfirm={ending.current ? logout : () => end.mutateAsync(ending)}
          onClose={() => setEnding(null)}
        />
      )}
    </>
  );
}
