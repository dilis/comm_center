import { useCallback } from "react";
import { useSearchParams } from "react-router";

import { PAGE_SIZES } from "@/components/DataTable";

type Defaults = { sort: string; order: "asc" | "desc"; filters: string[]; pageSize?: number };

/**
 * List state (page, page size, sort and filters) kept in the URL, so a filtered view can be
 * bookmarked, shared and survives Back. Defaults are left out of the URL; invalid values fall
 * back to the defaults; changing anything but the page returns to page 1.
 */
export function useListParams(defaults: Defaults) {
  const [params, setParams] = useSearchParams();
  const defaultSize = defaults.pageSize ?? 20;

  const pageRaw = Number(params.get("page"));
  const page = Number.isInteger(pageRaw) && pageRaw >= 1 ? pageRaw : 1;
  const sizeRaw = Number(params.get("page_size"));
  const pageSize = PAGE_SIZES.includes(sizeRaw) ? sizeRaw : defaultSize;
  const sort = params.get("sort") || defaults.sort;
  const order = params.get("order") === "desc" ? "desc" : params.get("order") === "asc" ? "asc" : defaults.order;
  const filters = Object.fromEntries(defaults.filters.map((k) => [k, params.get(k) ?? ""]));

  const update = useCallback(
    (changes: Record<string, string | null>, keepPage = false) => {
      setParams(
        (previous) => {
          const next = new URLSearchParams(previous);
          for (const [key, value] of Object.entries(changes)) {
            if (value === null || value === "") next.delete(key);
            else next.set(key, value);
          }
          if (!keepPage && !("page" in changes)) next.delete("page");
          return next;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  return {
    page,
    pageSize,
    sort,
    order: order as "asc" | "desc",
    filters,
    setPage: useCallback((p: number) => update({ page: p === 1 ? null : String(p) }, true), [update]),
    setPageSize: useCallback((n: number) => update({ page_size: n === defaultSize ? null : String(n) }), [update, defaultSize]),
    setSort: useCallback(
      (key: string, direction: "asc" | "desc") =>
        update({
          sort: key === defaults.sort ? null : key,
          order: direction === defaults.order ? null : direction,
        }),
      [update, defaults.sort, defaults.order],
    ),
    setFilter: useCallback((key: string, value: string) => update({ [key]: value }), [update]),
    /** Change several filters in one URL update (separate setFilter calls would overwrite each other). */
    setFilters: useCallback((changes: Record<string, string>) => update(changes), [update]),
  };
}
