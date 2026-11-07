import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { DataTable, type Column } from "./DataTable";

type Row = { id: number; name: string };
const columns: Column<Row>[] = [
  { id: "name", header: "Name", sortKey: "name", cell: (r) => r.name },
  { id: "note", header: "Note", cell: () => "—" },
];
const rows: Row[] = [
  { id: 1, name: "Ana" },
  { id: 2, name: "Bea" },
];

function setup(props: Partial<React.ComponentProps<typeof DataTable<Row>>> = {}) {
  const handlers = { onPageChange: vi.fn(), onPageSizeChange: vi.fn(), onSortChange: vi.fn() };
  render(
    <DataTable
      label="People"
      columns={columns}
      rows={rows}
      total={45}
      page={2}
      pageSize={20}
      sort={{ key: "name", order: "asc" }}
      getRowId={(r) => r.id}
      {...handlers}
      {...props}
    />,
  );
  return handlers;
}

test("shows the rows and where you are in the result set", () => {
  setup();
  expect(screen.getAllByRole("row")).toHaveLength(3); // header + 2
  expect(screen.getByText("Ana")).toBeInTheDocument();
  expect(screen.getByText("Showing 21–22 of 45")).toBeInTheDocument();
  expect(screen.getByText("Page 2 of 3")).toBeInTheDocument();
});

test("previous and next change the page; the ends are disabled", async () => {
  const h = setup();
  await userEvent.click(screen.getByRole("button", { name: "Next page" }));
  expect(h.onPageChange).toHaveBeenLastCalledWith(3);
  await userEvent.click(screen.getByRole("button", { name: "Previous page" }));
  expect(h.onPageChange).toHaveBeenLastCalledWith(1);
});

test("first page disables previous, last page disables next", () => {
  setup({ page: 1 });
  expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();
});

test("last page disables next", () => {
  setup({ page: 3 });
  expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
});

test("changing the page size is reported", async () => {
  const h = setup();
  await userEvent.selectOptions(screen.getByLabelText("Rows per page"), "50");
  expect(h.onPageSizeChange).toHaveBeenCalledWith(50);
});

test("sortable headers report a sort; the current one flips direction", async () => {
  const h = setup();
  const header = screen.getByRole("columnheader", { name: /Name/ });
  expect(header).toHaveAttribute("aria-sort", "ascending");
  await userEvent.click(within(header).getByRole("button"));
  expect(h.onSortChange).toHaveBeenCalledWith("name", "desc");
  expect(within(screen.getByRole("columnheader", { name: "Note" })).queryByRole("button")).toBeNull();
});

test("sorting by a different column starts ascending", async () => {
  const h = setup({ sort: { key: "created_at", order: "desc" } });
  await userEvent.click(within(screen.getByRole("columnheader", { name: /Name/ })).getByRole("button"));
  expect(h.onSortChange).toHaveBeenCalledWith("name", "asc");
});

test("loading, error and empty states replace the rows", () => {
  const { unmount } = render(
    <DataTable label="x" columns={columns} rows={undefined} total={0} page={1} pageSize={20} isLoading
      getRowId={(r: Row) => r.id} onPageChange={() => {}} onPageSizeChange={() => {}} />,
  );
  expect(screen.getByText("Loading…")).toBeInTheDocument();
  unmount();
  const second = render(
    <DataTable label="x" columns={columns} rows={undefined} total={0} page={1} pageSize={20} error="boom"
      getRowId={(r: Row) => r.id} onPageChange={() => {}} onPageSizeChange={() => {}} />,
  );
  expect(screen.getByRole("alert")).toHaveTextContent("boom");
  second.unmount();
  render(
    <DataTable label="x" columns={columns} rows={[]} total={0} page={1} pageSize={20} emptyMessage="Nobody here"
      getRowId={(r: Row) => r.id} onPageChange={() => {}} onPageSizeChange={() => {}} />,
  );
  expect(screen.getByText("Nobody here")).toBeInTheDocument();
});

test("a page past the end (rows deleted) steps back to the last page", () => {
  const h = setup({ rows: [], total: 5, page: 4, pageSize: 2 });
  expect(h.onPageChange).toHaveBeenCalledWith(3);
});
