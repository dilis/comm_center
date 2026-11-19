import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDownLeft, ArrowUpRight, CornerUpLeft, Eye, Plus, RotateCw, Smartphone, Trash2, User } from "lucide-react";
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
import { Tip } from "@/components/ui/tooltip";
import { useListParams } from "@/lib/useListParams";
import { cn, formatDateTime, formatRelative } from "@/lib/utils";

import { POLL } from "./polling";
import { DeviceAlert } from "./DeviceAlert";
import { MessageDetailDialog, directionLabel, type Message } from "./MessageDetailDialog";
import { ReplyDialog } from "./ReplyDialog";
import { SendMessageDialog } from "./SendMessageDialog";

const STATUSES = ["queued", "sending", "sent", "failed", "delivered", "received"] as const;
type Status = (typeof STATUSES)[number];
type Direction = "all" | "sent" | "received";
type Dialog =
  | { kind: "new" }
  | { kind: "view"; message: Message }
  | { kind: "reply"; message: Message }
  | { kind: "retry"; message: Message }
  | { kind: "delete"; message: Message }
  | null;

const STATUS_VARIANT = {
  queued: "secondary", sending: "warning", sent: "success", delivered: "success", failed: "destructive", received: "info",
} as const;

// The same two arrows mark a message's direction in the table and the Sent/Received tabs.
const SentArrow = ({ className }: { className?: string }) => <ArrowUpRight className={cn("h-4 w-4 text-sky-600", className)} aria-hidden />;
const ReceivedArrow = ({ className }: { className?: string }) => <ArrowDownLeft className={cn("h-4 w-4 text-emerald-600", className)} aria-hidden />;

/** Which way a message went, for the All tab (the other tabs already say). */
function DirectionArrow({ message }: { message: Message }) {
  return (
    <span className="max-md:hidden" role="img" aria-label={directionLabel(message)} title={directionLabel(message)}>
      {message.direction === "inbound" ? <ReceivedArrow /> : <SentArrow />}
    </span>
  );
}

const pending = (m: Message) => m.status === "queued" || m.status === "sending";

export default function MessagesPage() {
  const { can, canDeleteMessage } = useAuth();
  const queryClient = useQueryClient();
  const list = useListParams({ sort: "created_at", order: "desc", filters: ["q", "status", "direction"] });
  const [dialog, setDialog] = useState<Dialog>(null);
  // Only received messages can be answered, by someone who may create messages.
  const canReply = (m: Message) => m.direction === "inbound" && can("messages:create");
  // Only a sent message that failed, or that the phone has not confirmed yet, can be put back in the queue.
  const canRetry = (m: Message) => m.direction === "outbound" && (m.status === "failed" || m.status === "sent") && can("messages:create");
  const { q, status } = list.filters;
  const direction: Direction = list.filters.direction === "sent" || list.filters.direction === "received" ? list.filters.direction : "all";

  const counts = useQuery({
    queryKey: ["messages", "counts"],
    queryFn: () => unwrap(api.GET("/messages/counts")),
    placeholderData: keepPreviousData,
    refetchInterval: POLL.idleMs, // new messages change the tab numbers too
    refetchOnWindowFocus: true,
  });
  // "<unread>/<total>" for the tabs that hold received messages.
  const hasUnread = (counts.data?.unread ?? 0) > 0;
  const unreadOf = (total: number | undefined) => (total === undefined || counts.data === undefined ? undefined : `${counts.data.unread}/${total}`);
  const query = useQuery({
    queryKey: ["messages", "list", list.page, list.pageSize, list.order, q, direction === "received" ? "" : status, direction],
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
              status: (direction === "received" ? undefined : status || undefined) as Status | undefined,
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

  const retry = useMutation({
    mutationFn: (message: Message) => unwrap(api.POST("/messages/{message_id}/retry", { params: { path: { message_id: message.id } } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["messages"] }),
  });

  const remove = useMutation({
    mutationFn: (message: Message) => unwrap(api.DELETE("/messages/{message_id}", { params: { path: { message_id: message.id } } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["messages"] }),
  });

  // Opening a received message marks it read for this user only (the server keeps it per person).
  const markRead = useMutation({
    mutationFn: (message: Message) => unwrap(api.POST("/messages/{message_id}/read", { params: { path: { message_id: message.id } } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["messages"] }),
  });
  const view = (message: Message) => {
    setDialog({ kind: "view", message });
    if (message.unread) markRead.mutate(message);
  };

  const columns: Column<Message>[] = [
    {
      id: "contact",
      header: direction === "received" ? "From" : direction === "sent" ? "To" : "Contact",
      // On a phone card the sender leads. For a received message that is this contact (From); for
      // a sent one it is the owner, and this contact is the receiver (To), second.
      mobileLabel: (m) => (m.direction === "inbound" ? "From" : "To"),
      cellClassName: (m) => (m.direction === "inbound" ? "max-md:order-[-2]" : "max-md:order-[-1]"),
      cell: (m) => (
        <div>
          <div className="flex items-center gap-1.5 font-medium">
            {direction === "all" && <DirectionArrow message={m} />}
            {m.unread && <span role="img" aria-label="Unread" className="h-2 w-2 shrink-0 rounded-full bg-sky-600" />}
            {m.contact_name}
          </div>
          <div className="text-xs text-muted-foreground">{m.phone_number}</div>
          {m.reply_to_id != null && <div className="mt-1 text-xs text-muted-foreground">Reply to #{m.reply_to_id}</div>}
        </div>
      ),
    },
    {
      id: "owner",
      header: direction === "sent" ? "From" : direction === "received" ? "Device" : "Owner",
      // The owner is the sender of a sent message (first, From) and the receiving device of a
      // received one, which a phone card hides.
      mobileLabel: () => "From",
      cellClassName: (m) => (m.direction === "inbound" ? "max-md:hidden" : "max-md:order-[-2]"),
      cell: (m) =>
        direction === "all" ? (
          <span className="flex items-center gap-1.5">
            {m.owner_is_system ? (
              <Smartphone className="h-4 w-4 shrink-0 max-md:hidden text-teal-600 dark:text-teal-400" role="img" aria-label="Agent" />
            ) : (
              <User className="h-4 w-4 shrink-0 max-md:hidden text-indigo-600 dark:text-indigo-400" role="img" aria-label="User" />
            )}
            {m.owner_name}
          </span>
        ) : (
          m.owner_name
        ),
    },
    {
      id: "content",
      header: "Message",
      className: "max-md:order-last", // last in the stacked phone card
      cell: (m) => <p className={cn("line-clamp-2 max-w-md whitespace-pre-wrap break-words", m.unread && "font-semibold")}>{m.content}</p>,
    },
    ...(direction === "received" ? [] : [{
      id: "status",
      header: "Status",
      cell: (m) => (
        <div>
          <Badge variant={STATUS_VARIANT[m.status]}>{m.status}</Badge>
          {m.error_message && <div className="mt-1 max-w-48 break-words text-xs text-destructive">{m.error_message}</div>}
        </div>
      ),
    }] satisfies Column<Message>[]),
    {
      id: "date",
      header: "Date",
      sortKey: "created_at",
      // Humanized for scanning; the exact time is on hover and in the message's details.
      cell: (m) => (
        <Tip content={formatDateTime(m.created_at)}>
          <time dateTime={m.created_at} tabIndex={0} className="cursor-default underline decoration-dotted decoration-muted-foreground/50 underline-offset-4">
            {formatRelative(m.created_at)}
          </time>
        </Tip>
      ),
    },
    {
      id: "actions",
      header: "Actions",
      className: "text-right max-md:order-last max-md:mt-1 max-md:border-t max-md:pt-2", // bottom of the stacked phone card
      hideLabelOnMobile: true,
      cell: (m) => (
        <div className="flex justify-end gap-1 max-md:flex-wrap max-md:justify-start">
          <Tip content="View">
              <Button variant="ghost" size="icon" className="max-md:w-auto max-md:gap-1.5 max-md:px-3" aria-label={`View message ${m.id}`} onClick={() => view(m)}>
              <Eye className="h-4 w-4" aria-hidden />
              <span className="md:hidden">View</span>
            </Button>
          </Tip>
          {canReply(m) && (
            <Tip content="Reply">
                <Button variant="ghost" size="icon" className="max-md:w-auto max-md:gap-1.5 max-md:px-3" aria-label={`Reply to message ${m.id}`} onClick={() => setDialog({ kind: "reply", message: m })}>
                <CornerUpLeft className="h-4 w-4" aria-hidden />
                <span className="md:hidden">Reply</span>
              </Button>
            </Tip>
          )}
          {canRetry(m) && (
            <Tip content="Retry">
                <Button variant="ghost" size="icon" className="max-md:w-auto max-md:gap-1.5 max-md:px-3" aria-label={`Retry message ${m.id}`} onClick={() => setDialog({ kind: "retry", message: m })}>
                <RotateCw className="h-4 w-4" aria-hidden />
                <span className="md:hidden">Retry</span>
              </Button>
            </Tip>
          )}
          {canDeleteMessage(m) && (
            <Tip content="Delete">
                <Button variant="ghost" size="icon" className="max-md:w-auto max-md:gap-1.5 max-md:px-3" aria-label={`Delete message ${m.id}`} onClick={() => setDialog({ kind: "delete", message: m })}>
                <Trash2 className="h-4 w-4" aria-hidden />
                <span className="md:hidden">Delete</span>
              </Button>
            </Tip>
          )}
        </div>
      ),
    },
  ];

  const cellOf = (id: string, m: Message) => columns.find((c) => c.id === id)!.cell(m);

  // The All tab reads like a chat: received on the left, sent on the right.
  const bubbles = (rows: Message[]) => (
    <div className="space-y-3">
      {rows.map((m) => {
        const mine = m.direction === "outbound";
        // Sent bubbles are filled, so their secondary text is a tint of white, not the page's grey.
        const soft = mine ? "text-sky-100" : "text-muted-foreground";
        return (
          <div key={m.id} role="listitem" className={cn("flex flex-col gap-1", mine ? "items-end justify-end" : "items-start justify-start", mine && pending(m) && "opacity-60")}>
            {/* A received message's sender sits above its bubble; a sent one is from us, so only the recipient shows, inside. */}
            {!mine && (
              <div className="flex flex-wrap items-baseline gap-x-2 px-1 text-xs text-muted-foreground">
                {m.unread && <span role="img" aria-label="Unread" className="h-2 w-2 shrink-0 self-center rounded-full bg-sky-600" />}
                <span className="font-medium text-foreground">{m.contact_name}</span>
                <span>{m.phone_number}</span>
              </div>
            )}
            <div
              className={cn(
                "flex max-w-[85%] flex-col gap-1 rounded-2xl px-4 py-2.5 shadow-sm md:max-w-[65%]",
                mine ? "rounded-br-sm bg-sky-600 text-white dark:bg-sky-700" : "rounded-bl-sm bg-muted text-foreground",
              )}
            >
              {mine && (
                <div className={cn("flex flex-wrap items-baseline gap-x-2 text-xs", soft)}>
                  <span className="font-medium text-white">To {m.contact_name}</span>
                  <span>{m.phone_number}</span>
                </div>
              )}
              {m.reply_to_id != null && <div className={cn("text-xs", soft)}>Reply to #{m.reply_to_id}</div>}
              <p className={cn("whitespace-pre-wrap break-words", m.unread && "font-semibold")}>{m.content}</p>
              <div className={cn("flex flex-wrap items-center gap-2 text-xs", soft)}>
                {cellOf("date", m)}
                {mine && <Badge variant={STATUS_VARIANT[m.status]}>{m.status}</Badge>}
              </div>
              {m.error_message && <div className={cn("break-words text-xs", mine ? "font-medium text-red-100" : "text-destructive")}>{m.error_message}</div>}
              <div className={cn("-mx-2", mine && "[&_button]:text-white [&_button:hover]:bg-white/20")}>{cellOf("actions", m)}</div>
            </div>
          </div>
        );
      })}
    </div>
  );

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
      <DeviceAlert />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Tabs
          label="Direction"
          value={direction}
          onChange={(v) => list.setFilter("direction", v === "all" ? "" : v)}
          items={[
            { value: "all", label: "All", count: unreadOf(counts.data?.all), attention: hasUnread },
            { value: "sent", label: "Sent", icon: <SentArrow />, count: counts.data?.sent },
            { value: "received", label: "Received", icon: <ReceivedArrow />, count: unreadOf(counts.data?.received), attention: hasUnread },
          ]}
        />
        <SearchBox label="Search messages" placeholder="Search text or number" value={q} onChange={(v) => list.setFilter("q", v)} />
        {direction !== "received" && <label className="flex items-center gap-2 text-sm">
          Status
          <Select className="w-36" value={status} onChange={(e) => list.setFilter("status", e.target.value)}>
            <option value="">All</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </Select>
        </label>}
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
        // Outgoing messages the modem has not finished with are dimmed until they are sent.
        rowClassName={(m) => (m.direction === "outbound" && pending(m) ? "opacity-60" : undefined)}
        renderList={direction === "all" ? bubbles : undefined}
        onPageChange={list.setPage}
        onPageSizeChange={list.setPageSize}
        onSortChange={(_, order) => list.setSort("created_at", order)}
      />
      {dialog?.kind === "new" && <SendMessageDialog onClose={() => setDialog(null)} />}
      {dialog?.kind === "view" && (
        <MessageDetailDialog
          message={dialog.message}
          onClose={() => setDialog(null)}
          onReply={canReply(dialog.message) ? () => setDialog({ kind: "reply", message: dialog.message }) : undefined}
          onRetry={canRetry(dialog.message) ? () => setDialog({ kind: "retry", message: dialog.message }) : undefined}
        />
      )}
      {dialog?.kind === "retry" && (
        <ConfirmDialog
          title="Retry message"
          description={`Queue this message to ${dialog.message.contact_name} again? ${dialog.message.status === "sent" ? "The phone accepted it but has not confirmed delivery." : `It failed with: ${dialog.message.error_message ?? "no reason given"}.`} The first attempt may already have reached the person, who could then receive it twice.`}
          confirmLabel="Retry"
          onConfirm={() => retry.mutateAsync(dialog.message)}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog?.kind === "reply" && <ReplyDialog message={dialog.message} onClose={() => setDialog(null)} />}
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
