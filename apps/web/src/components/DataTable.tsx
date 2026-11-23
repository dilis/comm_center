import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/input";
import { cn } from "@/lib/utils";
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
  /** The label on a stacked (phone) row when it depends on the row; defaults to ``header``. */
  mobileLabel?: (row: T) => string;
  /** Extra classes for this column's cell in one row (the header keeps ``className``), e.g. to
   * reorder or hide it on a phone card. */
  cellClassName?: (row: T) => string | undefined;
};

export type SortState = { key: string; order: "asc" | "desc" };
export const PAGE_SIZES = [10, 20, 50, 100];

type Props<T> = {
  label: string;
  columns: Column<T>[];
  rows: T[] | undefined;
  total: number;
  page?: number;
  pageSize?: number;
  sort?: SortState;
  isLoading?: boolean;
  error?: string | null;
  emptyMessage?: string;
  getRowId: (row: T) => string | number;
  /** Extra classes for one row, e.g. to grey it out. */
  rowClassName?: (row: T) => string | undefined;
  onPageChange?: (page: number) => void;
  onPageSizeChange?: (size: number) => void;
  onSortChange?: (key: string, order: "asc" | "desc") => void;
  /** Show the rows through this instead of the table (e.g. chat bubbles); paging and states stay. */
  renderList?: (rows: T[]) => ReactNode;
  /** Fill the parent's height: the rows scroll while the sort bar and pager stay put. */
  fill?: boolean;
  /**
   * Show the rows as a feed instead of pages: ``rows`` are oldest first, the view starts at the
   * bottom (newest) and scrolling up near the top loads older rows. Replaces the pager.
   */
  feed?: {
    hasMore: boolean;
    isLoadingMore: boolean;
    onLoadMore: () => void;
    /** Changes when the feed shows a different list (a new filter), so the view jumps to the bottom again. */
    resetKey: string;
  };
};

const EDGE_PX = 120;

/** Server-driven table: the parent owns page, size and sort and fetches accordingly. */
export function DataTable<T>({
  label, columns, rows, total, page = 1, pageSize = 20, sort, isLoading, error, emptyMessage = "Nothing to show.",
  getRowId, rowClassName, onPageChange, onPageSizeChange, onSortChange, renderList, fill, feed,
}: Props<T>) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const first = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const last = (page - 1) * pageSize + (rows?.length ?? 0);

  // After deleting the last row of the last page, step back instead of showing an empty page.
  useEffect(() => {
    if (!feed && !isLoading && !error && rows && rows.length === 0 && total > 0 && page > pages) {
      onPageChange?.(pages);
    }
  }, [feed, isLoading, error, rows, total, page, pages, onPageChange]);

  // Feed scrolling: start at the newest row, keep the view still when older rows are added above
  // it, and follow new rows only while the reader is already at the bottom.
  const scroller = useRef<HTMLDivElement>(null);
  const seen = useRef<{ key: string; first: string | number | undefined; height: number; atBottom: boolean }>({ key: "", first: undefined, height: 0, atBottom: true });
  const firstId = rows && rows.length > 0 ? getRowId(rows[0]) : undefined;
  useLayoutEffect(() => {
    const el = scroller.current;
    if (!feed || !el || !rows || rows.length === 0) return;
    const before = seen.current;
    if (before.key !== feed.resetKey) {
      el.scrollTop = el.scrollHeight;
    } else if (before.first !== undefined && firstId !== before.first) {
      el.scrollTop += el.scrollHeight - before.height; // older rows arrived above
    } else if (before.atBottom) {
      el.scrollTop = el.scrollHeight;
    }
    seen.current = { key: feed.resetKey, first: firstId, height: el.scrollHeight, atBottom: before.key !== feed.resetKey || before.atBottom };
  });
  const loadMore = feed?.onLoadMore;
  const canLoad = !!feed && feed.hasMore && !feed.isLoadingMore && !error;
  function onScroll() {
    const el = scroller.current;
    if (!el) return;
    seen.current.atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < EDGE_PX;
    seen.current.height = el.scrollHeight;
    if (canLoad && el.scrollTop < EDGE_PX) loadMore?.();
  }
  // A first page too short to scroll would never trigger onScroll, so keep loading until it fills.
  useEffect(() => {
    const el = scroller.current;
    if (canLoad && el && el.clientHeight > 0 && el.scrollHeight <= el.clientHeight) loadMore?.();
  });

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
    <div className={cn(fill ? "flex min-h-0 flex-1 flex-col gap-3" : "space-y-3")}>
      {onSortChange && sortable.length > 0 && (
        <label className="flex shrink-0 items-center gap-2 text-sm md:hidden">
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
      <div ref={scroller} onScroll={feed ? onScroll : undefined} className={cn(fill && "min-h-0 flex-1 overflow-y-auto")}>
      {feed?.isLoadingMore && <p className="py-2 text-center text-xs text-muted-foreground">Loading older messages…</p>}
      {renderList ? (
        error ? (
          <p role="alert" className="py-8 text-center text-destructive">{error}</p>
        ) : isLoading ? (
          <p className="py-8 text-center text-muted-foreground">Loading…</p>
        ) : rows && rows.length > 0 ? (
          <div aria-label={label} role="list">{renderList(rows)}</div>
        ) : (
          <p className="py-8 text-center text-muted-foreground">{emptyMessage}</p>
        )
      ) : (
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
              <TableRow key={getRowId(row)} className={rowClassName?.(row)}>
                {columns.map((c) => (
                  <TableCell
                    key={c.id}
                    className={cn(c.className, c.cellClassName?.(row))}
                    data-label={c.hideLabelOnMobile ? undefined : (c.mobileLabel?.(row) ?? c.header)}
                  >
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
      )}
      </div>
      {feed ? (
        <div className="shrink-0 text-sm text-muted-foreground">{total === 0 ? "No results" : `Showing ${rows?.length ?? 0} of ${total}`}</div>
      ) : (
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 text-sm text-muted-foreground">
        <span>{total === 0 ? "No results" : `Showing ${first}–${last} of ${total}`}</span>
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2">
            Rows per page
            <Select
              className="h-8 w-20"
              value={pageSize}
              onChange={(e) => onPageSizeChange?.(Number(e.target.value))}
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
          <Button variant="outline" size="sm" aria-label="Previous page" disabled={page <= 1} onClick={() => onPageChange?.(page - 1)}>
            Previous
          </Button>
          <Button variant="outline" size="sm" aria-label="Next page" disabled={page >= pages} onClick={() => onPageChange?.(page + 1)}>
            Next
          </Button>
        </div>
      </div>
      )}
    </div>
  );
}
