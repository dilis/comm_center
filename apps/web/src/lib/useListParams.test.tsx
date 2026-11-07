import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router";

import { useListParams } from "./useListParams";

function Probe() {
  const p = useListParams({ sort: "name", order: "asc", filters: ["q", "type"] });
  const location = useLocation();
  return (
    <div>
      <output aria-label="state">{JSON.stringify({ ...p, setPage: undefined, setPageSize: undefined, setSort: undefined, setFilter: undefined })}</output>
      <output aria-label="url">{location.search}</output>
      <button onClick={() => p.setPage(3)}>page3</button>
      <button onClick={() => p.setPageSize(50)}>size50</button>
      <button onClick={() => p.setSort("created_at", "desc")}>sort</button>
      <button onClick={() => p.setFilter("q", "ana")}>filter</button>
      <button onClick={() => p.setFilter("q", "")}>clear</button>
    </div>
  );
}
const state = () => JSON.parse(screen.getByLabelText("state").textContent!);
const url = () => screen.getByLabelText("url").textContent;
const open = (path = "/") => render(<MemoryRouter initialEntries={[path]}><Probe /></MemoryRouter>);

test("defaults apply and keep the URL clean", () => {
  open();
  expect(state()).toMatchObject({ page: 1, pageSize: 20, sort: "name", order: "asc", filters: { q: "", type: "" } });
  expect(url()).toBe("");
});

test("state is read from the URL", () => {
  open("/?page=4&page_size=50&sort=created_at&order=desc&q=bea&type=entity");
  expect(state()).toMatchObject({ page: 4, pageSize: 50, sort: "created_at", order: "desc", filters: { q: "bea", type: "entity" } });
});

test("nonsense values fall back to the defaults", () => {
  const first = open("/?page=-2&page_size=7&order=sideways");
  expect(state()).toMatchObject({ page: 1, pageSize: 20, order: "asc" });
  first.unmount();
  open("/?page=abc");
  expect(state()).toMatchObject({ page: 1 });
});

test("changing a filter, the sort or the page size returns to page 1", async () => {
  open("/?page=3");
  await userEvent.click(screen.getByText("filter"));
  expect(state()).toMatchObject({ page: 1, filters: { q: "ana" } });
  expect(url()).toBe("?q=ana");
  await userEvent.click(screen.getByText("page3"));
  expect(url()).toBe("?q=ana&page=3");
  await userEvent.click(screen.getByText("sort"));
  expect(url()).toBe("?q=ana&sort=created_at&order=desc");
  await userEvent.click(screen.getByText("page3"));
  await userEvent.click(screen.getByText("size50"));
  expect(state()).toMatchObject({ page: 1, pageSize: 50 });
});

test("clearing a filter removes it from the URL", async () => {
  open("/?q=ana");
  await userEvent.click(screen.getByText("clear"));
  expect(url()).toBe("");
});
