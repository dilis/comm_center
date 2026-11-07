import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Trash2 } from "lucide-react";
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
import { useListParams } from "@/lib/useListParams";
import { formatDateTime } from "@/lib/utils";

import { CreateUserDialog, EditUserDialog, type User } from "./UserDialog";

type Dialog = { kind: "new" } | { kind: "edit"; user: User } | { kind: "delete"; user: User } | null;

export default function UsersPage() {
  const { can, canActOn, me } = useAuth();
  const queryClient = useQueryClient();
  const list = useListParams({ sort: "created_at", order: "desc", filters: ["q", "status"] });
  const [dialog, setDialog] = useState<Dialog>(null);
  const { q, status } = list.filters;
  const isActive = status === "active" ? true : status === "inactive" ? false : undefined;

  const query = useQuery({
    queryKey: ["users", "list", list.page, list.pageSize, list.sort, list.order, q, status],
    queryFn: () =>
      unwrap(
        api.GET("/users", {
          params: {
            query: {
              page: list.page,
              page_size: list.pageSize,
              sort: list.sort as "username" | "created_at",
              order: list.order,
              q: q || undefined,
              is_active: isActive,
            },
          },
        }),
      ),
    placeholderData: keepPreviousData,
  });

  const remove = useMutation({
    mutationFn: (user: User) => unwrap(api.DELETE("/users/{user_id}", { params: { path: { user_id: user.id } } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["users"] }),
  });

  const columns: Column<User>[] = [
    { id: "username", header: "Username", sortKey: "username", cell: (u) => <span className="font-medium">{u.username}</span> },
    { id: "name", header: "Name", cell: (u) => u.name },
    {
      id: "groups",
      header: "Groups",
      cell: (u) => (
        <div className="flex flex-wrap gap-1">
          {u.groups.map((g) => (
            <Badge key={g.id} variant="outline">
              {g.name}
            </Badge>
          ))}
        </div>
      ),
    },
    { id: "status", header: "Status", cell: (u) => <Badge variant={u.is_active ? "success" : "warning"}>{u.is_active ? "Active" : "Inactive"}</Badge> },
    { id: "created", header: "Created", sortKey: "created_at", cell: (u) => formatDateTime(u.created_at) },
    {
      id: "actions",
      header: "Actions",
      className: "text-right",
      cell: (u) => (
        <div className="flex justify-end gap-1">
          {canActOn("users", "update", u.owner_id) && (
            <Button variant="ghost" size="icon" aria-label={`Edit ${u.username}`} onClick={() => setDialog({ kind: "edit", user: u })}>
              <Pencil className="h-4 w-4" aria-hidden />
            </Button>
          )}
          {canActOn("users", "delete", u.owner_id) && u.id !== me?.id && (
            <Button variant="ghost" size="icon" aria-label={`Delete ${u.username}`} onClick={() => setDialog({ kind: "delete", user: u })}>
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
        title="Users"
        actions={
          can("users:create") && (
            <Button onClick={() => setDialog({ kind: "new" })}>
              <Plus className="h-4 w-4" aria-hidden />
              New user
            </Button>
          )
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <SearchBox label="Search users" placeholder="Search username or name" value={q} onChange={(v) => list.setFilter("q", v)} />
        <label className="flex items-center gap-2 text-sm">
          Status
          <Select className="w-32" value={status} onChange={(e) => list.setFilter("status", e.target.value)}>
            <option value="">All</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </Select>
        </label>
      </div>
      <DataTable
        label="Users"
        columns={columns}
        rows={query.data?.items}
        total={query.data?.total ?? 0}
        page={list.page}
        pageSize={list.pageSize}
        sort={{ key: list.sort, order: list.order }}
        isLoading={query.isPending}
        error={query.error ? errorMessage(query.error) : null}
        emptyMessage="No users found."
        getRowId={(u) => u.id}
        onPageChange={list.setPage}
        onPageSizeChange={list.setPageSize}
        onSortChange={list.setSort}
      />
      {dialog?.kind === "new" && <CreateUserDialog onClose={() => setDialog(null)} />}
      {dialog?.kind === "edit" && <EditUserDialog user={dialog.user} onClose={() => setDialog(null)} />}
      {dialog?.kind === "delete" && (
        <ConfirmDialog
          title="Delete user"
          description={`Delete ${dialog.user.username}? They can no longer sign in and their sessions end. Their contact and messages are kept.`}
          confirmLabel="Delete"
          onConfirm={() => remove.mutateAsync(dialog.user)}
          onClose={() => setDialog(null)}
        />
      )}
    </>
  );
}
