import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DataGrid, type ColumnDef } from "./data-grid";

type R = { id: number; name: string; score: number };
const rows: R[] = [
  { id: 1, name: "Alpha", score: 70 },
  { id: 2, name: "Beta", score: 90 },
  { id: 3, name: "Gamma", score: 80 },
];
const cols: ColumnDef<R, unknown>[] = [
  { id: "name", header: "Name", accessorKey: "name" },
  { id: "score", header: "Score", accessorKey: "score" },
];

describe("DataGrid", () => {
  it("sorts, selects with ctrl/shift, moves with arrows and copies TSV", async () => {
    const onSelect = vi.fn();
    const onActivate = vi.fn();
    const write = vi.fn(() => Promise.resolve());
    Object.assign(navigator, { clipboard: { writeText: write } });
    render(<DataGrid label="Test" data={rows} columns={cols} getRowId={(r) => String(r.id)} onSelect={onSelect} onActivate={onActivate} initialSort={[{ id: "score", desc: true }]} />);
    const body = () => screen.getAllByRole("row").slice(1);
    expect(body().map((r) => r.textContent)).toEqual(["Beta90", "Gamma80", "Alpha70"]);
    fireEvent.click(body()[0]!);
    fireEvent.click(body()[2]!, { shiftKey: true });
    expect(onSelect).toHaveBeenLastCalledWith(["2", "3", "1"]);
    fireEvent.click(body()[1]!, { ctrlKey: true });
    expect(onSelect).toHaveBeenLastCalledWith(["2", "1"]);
    const grid = screen.getByRole("grid", { name: "Test" });
    fireEvent.keyDown(grid, { key: "c", ctrlKey: true });
    expect(write).toHaveBeenCalledWith("Name\tScore\nBeta\t90\nAlpha\t70");
    fireEvent.click(body()[0]!);
    fireEvent.keyDown(grid, { key: "ArrowDown" });
    expect(onSelect).toHaveBeenLastCalledWith(["3"]);
    fireEvent.keyDown(grid, { key: "Enter" });
    expect(onActivate).toHaveBeenCalledWith(rows[2]);
    fireEvent.click(screen.getByRole("button", { name: /Name/ }));
    expect(body().map((r) => r.textContent)).toEqual(["Alpha70", "Beta90", "Gamma80"]);
  });
});
