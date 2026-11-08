import * as React from "react";

import { cn } from "@/lib/utils";

export const Table = ({ className, ...props }: React.TableHTMLAttributes<HTMLTableElement>) => (
  <div className="relative w-full overflow-auto">
    <table className={cn("w-full caption-bottom text-sm max-md:block", className)} {...props} />
  </div>
);
export const TableHeader = (props: React.HTMLAttributes<HTMLTableSectionElement>) => (
  <thead className="[&_tr]:border-b max-md:hidden" {...props} />
);
export const TableBody = (props: React.HTMLAttributes<HTMLTableSectionElement>) => (
  <tbody className="[&_tr:last-child]:border-0 max-md:block" {...props} />
);
export const TableRow = ({ className, ...props }: React.HTMLAttributes<HTMLTableRowElement>) => (
  <tr className={cn("border-b transition-colors hover:bg-muted/50 max-md:mb-3 max-md:flex max-md:flex-col max-md:rounded-md max-md:border max-md:p-3", className)} {...props} />
);
export const TableHead = ({ className, ...props }: React.ThHTMLAttributes<HTMLTableCellElement>) => (
  <th className={cn("h-10 px-3 text-left align-middle text-xs font-medium text-muted-foreground", className)} {...props} />
);
export const TableCell = ({ className, ...props }: React.TdHTMLAttributes<HTMLTableCellElement>) => (
  <td className={cn("px-3 py-2 align-middle max-md:flex max-md:items-start max-md:gap-3 max-md:text-left max-md:px-0 max-md:py-1 max-md:before:w-24 max-md:before:shrink-0 max-md:before:text-right max-md:before:text-xs max-md:before:font-medium max-md:before:text-muted-foreground max-md:before:content-[attr(data-label)]", className)} {...props} />
);
