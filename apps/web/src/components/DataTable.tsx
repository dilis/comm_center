import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import { useEffect, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

export type Column<T> = {
  id: string;
  header: string;
  /** The API's ``sort`` value; leave out for columns that cannot be sorted. */
  sortKey?: string;
  cell: (row: T) => ReactNode;
  className?: string;
  /** Hide the "Header:" label on a stacked (phone) row, e.g. for an actions column. */
  hideLabelOnMobile?: boolean;
};

export type SortState = { key: string; order: "asc" | "desc" };
export const PAGE_SIZES = [10, 20, 50, 100];

type Props<T> = {
  label: string;
  columns: Column<T>[];
  rows: T[] | undefined;
  total: number;
  page: number;
  pageSize: number;
  sort?: SortState;
  isLoading?: boolean;
  error?: string | null;
  emptyMessage?: string;
  getRowId: (row: T) => string | number;
  onPageChange: (page: number) => void;
  onPageSizeChange: (size: number) => void;
  onSortChange?: (key: string, order: "asc" | "desc") => void;
};

/** Server-driven table: the parent owns page, size and sort and fetches accordingly. */
export function DataTable<T>({
  label, columns, rows, total, page, pageSize, sort, isLoading, error, emptyMessage = "Nothing to show.",
  getRowId, onPageChange, onPageSizeChange, onSortChange,
}: Props<T>) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const first = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const last = (page - 1) * pageSize + (rows?.length ?? 0);

  // After deleting the last row of the last page, step back instead of showing an empty page.
  useEffect(() => {
    if (!isLoading && !error && rows && rows.length === 0 && total > 0 && page > pages) {
      onPageChange(pages);
    }
  }, [isLoading, error, rows, total, page, pages, onPageChange]);

  const sortable = columns.filter((c) => c.sortKey);

  function header(column: Column<T>) {
    if (!column.sortKey || !onSortChange) return column.header;
    const active = sort?.key === column.sortKey;
    const Icon = !active ? ArrowUpDown : sort.order === "asc" ? ArrowUp : ArrowDown;
    return (
      <button
        type="button"
        className="inline-flex items-center gap-1 hover:text-foreground"
        onClick={() => onSortChange(column.sortKey!, active && sort.order === "asc" ? "desc" : "asc")}
      >
        {column.header}
        <Icon className="h-3 w-3" aria-hidden />
      </button>
    );
  }

  return (
    <div className="space-y-3">
      {onSortChange && sortable.length > 0 && (
        <label className="flex items-center gap-2 text-sm md:hidden">
          Sort by
          <Select
            className="h-8 flex-1"
            value={`${sort?.key ?? ""}:${sort?.order ?? "asc"}`}
            onChange={(e) => {
              const [key, order] = e.target.value.split(":");
              onSortChange(key, order as "asc" | "desc");
            }}
          >
            {sortable.flatMap((c) => [
              <option key={`${c.id}:asc`} value={`${c.sortKey}:asc`}>{c.header} (ascending)</option>,
              <option key={`${c.id}:desc`} value={`${c.sortKey}:desc`}>{c.header} (descending)</option>,
            ])}
          </Select>
        </label>
      )}
      <Table aria-label={label}>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            {columns.map((c) => (
              <TableHead
                key={c.id}
                className={c.className}
                aria-sort={
                  c.sortKey && sort?.key === c.sortKey ? (sort.order === "asc" ? "ascending" : "descending") : undefined
                }
              >
                {header(c)}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {error ? (
            <TableRow>
              <TableCell colSpan={columns.length} role="alert" className="py-8 text-center text-destructive">
                {error}
              </TableCell>
            </TableRow>
          ) : isLoading ? (
            <TableRow>
              <TableCell colSpan={columns.length} className="py-8 text-center text-muted-foreground">
                Loading…
              </TableCell>
            </TableRow>
          ) : rows && rows.length > 0 ? (
            rows.map((row) => (
              <TableRow key={getRowId(row)}>
                {columns.map((c) => (
                  <TableCell key={c.id} className={c.className} data-label={c.hideLabelOnMobile ? undefined : c.header}>
                    {c.cell(row)}
                  </TableCell>
                ))}
              </TableRow>
            ))
          ) : (
            <TableRow>
              <TableCell colSpan={columns.length} className="py-8 text-center text-muted-foreground">
                {emptyMessage}
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
      <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-muted-foreground">
        <span>{total === 0 ? "No results" : `Showing ${first}–${last} of ${total}`}</span>
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2">
            Rows per page
            <Select
              className="h-8 w-20"
              value={pageSize}
              onChange={(e) => onPageSizeChange(Number(e.target.value))}
            >
              {PAGE_SIZES.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </Select>
          </label>
          <span>
            Page {page} of {pages}
          </span>
          <Button variant="outline" size="sm" aria-label="Previous page" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>
            Previous
          </Button>
          <Button variant="outline" size="sm" aria-label="Next page" disabled={page >= pages} onClick={() => onPageChange(page + 1)}>
            Next
          </Button>
        </div>
      </div>
    </div>
  );
}
