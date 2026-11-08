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
import { formatDateTime } from "@/lib/utils";
import { useListParams } from "@/lib/useListParams";

import { ContactDialog, type Contact } from "./ContactDialog";

type Dialog = { kind: "new" } | { kind: "edit"; contact: Contact } | { kind: "delete"; contact: Contact } | null;
type TypeFilter = "" | "person" | "entity";

export default function ContactsPage() {
  const { can, canActOn } = useAuth();
  const queryClient = useQueryClient();
  const list = useListParams({ sort: "created_at", order: "desc", filters: ["q", "type"] });
  const [dialog, setDialog] = useState<Dialog>(null);
  const { q, type } = list.filters;

  const query = useQuery({
    queryKey: ["contacts", "list", list.page, list.pageSize, list.sort, list.order, q, type],
    queryFn: () =>
      unwrap(
        api.GET("/contacts", {
          params: {
            query: {
              page: list.page,
              page_size: list.pageSize,
              sort: list.sort as "name" | "created_at" | "updated_at",
              order: list.order,
              q: q || undefined,
              type: (type || undefined) as TypeFilter extends infer T ? Exclude<T, ""> | undefined : never,
            },
          },
        }),
      ),
    placeholderData: keepPreviousData,
  });

  const remove = useMutation({
    mutationFn: (contact: Contact) =>
      unwrap(api.DELETE("/contacts/{contact_id}", { params: { path: { contact_id: contact.id } } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["contacts"] }),
  });

  const columns: Column<Contact>[] = [
    { id: "name", header: "Name", sortKey: "name", cell: (c) => <span className="font-medium">{c.name}</span> },
    { id: "type", header: "Type", cell: (c) => <Badge variant="outline">{c.type}</Badge> },
    { id: "email", header: "Email", cell: (c) => c.email ?? "" },
    {
      id: "phones",
      header: "Phones",
      cell: (c) => (
        <ul className="space-y-0.5">
          {c.phones.map((p) => (
            <li key={p.phone}>
              <span>{p.phone}</span> {p.label && <span className="text-xs text-muted-foreground">{p.label}</span>}
              {p.is_primary && <Badge className="ml-1">primary</Badge>}
            </li>
          ))}
        </ul>
      ),
    },
    { id: "user", header: "Account", cell: (c) => (c.user_id ? <Badge variant="success">User</Badge> : "") },
    { id: "created", header: "Created", sortKey: "created_at", cell: (c) => formatDateTime(c.created_at) },
    {
      id: "actions",
      header: "Actions",
      className: "text-right",
      hideLabelOnMobile: true,
      cell: (c) => (
        <div className="flex justify-end gap-1">
          {canActOn("contacts", "update", c.owner_id) && (
            <Button variant="ghost" size="icon" aria-label={`Edit ${c.name}`} onClick={() => setDialog({ kind: "edit", contact: c })}>
              <Pencil className="h-4 w-4" aria-hidden />
            </Button>
          )}
          {canActOn("contacts", "delete", c.owner_id) && (
            <Button variant="ghost" size="icon" aria-label={`Delete ${c.name}`} onClick={() => setDialog({ kind: "delete", contact: c })}>
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
        title="Contacts"
        actions={
          can("contacts:create") && (
            <Button onClick={() => setDialog({ kind: "new" })}>
              <Plus className="h-4 w-4" aria-hidden />
              New contact
            </Button>
          )
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <SearchBox label="Search contacts" placeholder="Search name, email or phone" value={q} onChange={(v) => list.setFilter("q", v)} />
        <label className="flex items-center gap-2 text-sm">
          Type
          <Select className="w-32" value={type} onChange={(e) => list.setFilter("type", e.target.value)}>
            <option value="">All</option>
            <option value="person">person</option>
            <option value="entity">entity</option>
          </Select>
        </label>
      </div>
      <DataTable
        label="Contacts"
        columns={columns}
        rows={query.data?.items}
        total={query.data?.total ?? 0}
        page={list.page}
        pageSize={list.pageSize}
        sort={{ key: list.sort, order: list.order }}
        isLoading={query.isPending}
        error={query.error ? errorMessage(query.error) : null}
        emptyMessage="No contacts found."
        getRowId={(c) => c.id}
        onPageChange={list.setPage}
        onPageSizeChange={list.setPageSize}
        onSortChange={list.setSort}
      />
      {(dialog?.kind === "new" || dialog?.kind === "edit") && (
        <ContactDialog contact={dialog.kind === "edit" ? dialog.contact : undefined} onClose={() => setDialog(null)} />
      )}
      {dialog?.kind === "delete" && (
        <ConfirmDialog
          title="Delete contact"
          description={`Delete ${dialog.contact.name}? Their phone numbers are freed for reuse. Past messages are kept.`}
          confirmLabel="Delete"
          onConfirm={() => remove.mutateAsync(dialog.contact)}
          onClose={() => setDialog(null)}
        />
      )}
    </>
  );
}
