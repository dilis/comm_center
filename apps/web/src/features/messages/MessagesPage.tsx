import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { api, errorMessage, unwrap } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { SearchBox } from "@/components/SearchBox";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/input";
import { Tabs } from "@/components/ui/tabs";
import { useListParams } from "@/lib/useListParams";
import { formatDateTime } from "@/lib/utils";

import { POLL } from "./polling";
import { MessageDetailDialog, directionLabel, type Message } from "./MessageDetailDialog";
import { SendMessageDialog } from "./SendMessageDialog";

const STATUSES = ["queued", "sending", "sent", "failed", "delivered", "received"] as const;
type Status = (typeof STATUSES)[number];
type Direction = "all" | "sent" | "received";
type Dialog = { kind: "new" } | { kind: "view"; message: Message } | { kind: "delete"; message: Message } | null;

const STATUS_VARIANT = {
  queued: "secondary", sending: "warning", sent: "success", delivered: "success", failed: "destructive", received: "default",
} as const;

const pending = (m: Message) => m.status === "queued" || m.status === "sending";

export default function MessagesPage() {
  const { can, canDeleteMessage } = useAuth();
  const queryClient = useQueryClient();
  const list = useListParams({ sort: "created_at", order: "desc", filters: ["q", "status", "direction"] });
  const [dialog, setDialog] = useState<Dialog>(null);
  const { q, status } = list.filters;
  const direction: Direction = list.filters.direction === "sent" || list.filters.direction === "received" ? list.filters.direction : "all";

  const counts = useQuery({
    queryKey: ["messages", "counts"],
    queryFn: () => unwrap(api.GET("/messages/counts")),
    placeholderData: keepPreviousData,
    refetchInterval: POLL.idleMs, // new messages change the tab numbers too
    refetchOnWindowFocus: true,
  });
  const query = useQuery({
    queryKey: ["messages", "list", list.page, list.pageSize, list.order, q, status, direction],
    queryFn: () =>
      unwrap(
        api.GET("/messages", {
          params: {
            query: {
              direction,
              page: list.page,
              page_size: list.pageSize,
              order: list.order,
              q: q || undefined,
              status: (status || undefined) as Status | undefined,
            },
          },
        }),
      ),
    placeholderData: keepPreviousData,
    // Keep checking: quickly while something is still being sent (statuses change every few
    // seconds), and slowly otherwise so received messages appear without a reload. Background
    // tabs pause, and coming back to the tab refreshes at once.
    refetchInterval: (state) => (state.state.data?.items.some(pending) ? POLL.pendingMs : POLL.idleMs),
    refetchOnWindowFocus: true,
  });

  const remove = useMutation({
    mutationFn: (message: Message) => unwrap(api.DELETE("/messages/{message_id}", { params: { path: { message_id: message.id } } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["messages"] }),
  });

  const columns: Column<Message>[] = [
    { id: "direction", header: "Direction", cell: (m) => <Badge variant="outline">{directionLabel(m)}</Badge> },
    {
      id: "contact",
      header: "Contact",
      cell: (m) => (
        <div>
          <div className="font-medium">{m.contact_name}</div>
          <div className="text-xs text-muted-foreground">{m.phone_number}</div>
        </div>
      ),
    },
    {
      id: "content",
      header: "Message",
      cell: (m) => <p className="line-clamp-2 max-w-md whitespace-pre-wrap break-words">{m.content}</p>,
    },
    {
      id: "status",
      header: "Status",
      cell: (m) => (
        <div>
          <Badge variant={STATUS_VARIANT[m.status]}>{m.status}</Badge>
          {m.error_message && <div className="mt-1 max-w-48 break-words text-xs text-destructive">{m.error_message}</div>}
        </div>
      ),
    },
    { id: "date", header: "Date", sortKey: "created_at", cell: (m) => formatDateTime(m.created_at) },
    {
      id: "actions",
      header: "Actions",
      className: "text-right",
      cell: (m) => (
        <div className="flex justify-end gap-1">
          <Button variant="ghost" size="icon" aria-label={`View message ${m.id}`} onClick={() => setDialog({ kind: "view", message: m })}>
            <Eye className="h-4 w-4" aria-hidden />
          </Button>
          {canDeleteMessage(m) && (
            <Button variant="ghost" size="icon" aria-label={`Delete message ${m.id}`} onClick={() => setDialog({ kind: "delete", message: m })}>
              <Trash2 className="h-4 w-4" aria-hidden />
            </Button>
          )}
        </div>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title="Messages"
        actions={
          can("messages:create") && (
            <Button onClick={() => setDialog({ kind: "new" })}>
              <Plus className="h-4 w-4" aria-hidden />
              New message
            </Button>
          )
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Tabs
          label="Direction"
          value={direction}
          onChange={(v) => list.setFilter("direction", v === "all" ? "" : v)}
          items={[
            { value: "all", label: "All", count: counts.data?.all },
            { value: "sent", label: "Sent", count: counts.data?.sent },
            { value: "received", label: "Received", count: counts.data?.received },
          ]}
        />
        <SearchBox label="Search messages" placeholder="Search text or number" value={q} onChange={(v) => list.setFilter("q", v)} />
        <label className="flex items-center gap-2 text-sm">
          Status
          <Select className="w-36" value={status} onChange={(e) => list.setFilter("status", e.target.value)}>
            <option value="">All</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </Select>
        </label>
      </div>
      <DataTable
        label="Messages"
        columns={columns}
        rows={query.data?.items}
        total={query.data?.total ?? 0}
        page={list.page}
        pageSize={list.pageSize}
        sort={{ key: "created_at", order: list.order }}
        isLoading={query.isPending}
        // A failed background refresh keeps the rows already on screen; only a first load (or a
        // new filter with nothing to show yet) reports the error in the table.
        error={query.isError && (!query.data || query.isPlaceholderData) ? errorMessage(query.error) : null}
        emptyMessage="No messages found."
        getRowId={(m) => m.id}
        onPageChange={list.setPage}
        onPageSizeChange={list.setPageSize}
        onSortChange={(_, order) => list.setSort("created_at", order)}
      />
      {dialog?.kind === "new" && <SendMessageDialog onClose={() => setDialog(null)} />}
      {dialog?.kind === "view" && <MessageDetailDialog message={dialog.message} onClose={() => setDialog(null)} />}
      {dialog?.kind === "delete" && (
        <ConfirmDialog
          title="Delete message"
          description="Delete this message from the log? A message that is still queued will not be sent."
          confirmLabel="Delete"
          onConfirm={() => remove.mutateAsync(dialog.message)}
          onClose={() => setDialog(null)}
        />
      )}
    </>
  );
}
