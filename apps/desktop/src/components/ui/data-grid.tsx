import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type Row,
  type RowData,
  type SortingState,
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { ContextMenu, type MenuItem } from "./menu";

declare module "@tanstack/react-table" {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface ColumnMeta<TData extends RowData, TValue> {
    align?: "right" | "center";
    mono?: boolean;
    /** grow share; fixed width when absent */
    flex?: number;
    /** text used by Ctrl+C (defaults to the raw value) */
    copy?: (row: TData) => string;
  }
}

export type DataGridProps<T> = {
  data: T[];
  columns: ColumnDef<T, unknown>[];
  getRowId: (row: T) => string;
  label: string;
  selected?: string[];
  onSelect?: (ids: string[]) => void;
  onActivate?: (row: T) => void;
  contextMenu?: (row: T, selected: T[]) => MenuItem[];
  rowClassName?: (row: T) => string | undefined;
  empty?: ReactNode;
  className?: string;
  rowHeight?: number;
  initialSort?: SortingState;
  /** render rows only when they scroll into view (Library, agent events) */
  virtual?: boolean;
};

function gridTemplate<T>(cols: { getSize: () => number; columnDef: ColumnDef<T, unknown> }[]): string {
  return cols
    .map((c) => {
      const flex = c.columnDef.meta?.flex;
      return flex ? `minmax(${c.getSize()}px, ${flex}fr)` : `${c.getSize()}px`;
    })
    .join(" ");
}

function cellText<T>(row: Row<T>): string[] {
  return row.getVisibleCells().map((cell) => {
    const copy = cell.column.columnDef.meta?.copy;
    if (copy) return copy(row.original);
    const v = cell.getValue();
    return v === null || v === undefined ? "" : typeof v === "object" ? JSON.stringify(v) : String(v);
  });
}

/**
 * Windows-style data grid: sortable/resizable columns, click/Ctrl/Shift selection, arrow keys,
 * Enter or double-click to open, right-click menu, Ctrl+C copies the selected rows as TSV.
 */
export function DataGrid<T>({
  data,
  columns,
  getRowId,
  label,
  selected: selectedProp,
  onSelect,
  onActivate,
  contextMenu,
  rowClassName,
  empty,
  className,
  rowHeight = 28,
  initialSort = [],
  virtual = false,
}: DataGridProps<T>) {
  const [sorting, setSorting] = useState<SortingState>(initialSort);
  const [selectedLocal, setSelectedLocal] = useState<string[]>([]);
  const selected = selectedProp ?? selectedLocal;
  const anchor = useRef<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const table = useReactTable({
    data,
    columns,
    getRowId: (r) => getRowId(r),
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    columnResizeMode: "onChange",
    defaultColumn: { size: 100, minSize: 36 },
  });
  const rows = table.getRowModel().rows;
  const headers = table.getHeaderGroups()[0]?.headers ?? [];
  const template = gridTemplate(table.getVisibleLeafColumns());
  const selectedSet = useMemo(() => new Set(selected), [selected]);

  const virt = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => rowHeight,
    overscan: 12,
    enabled: virtual,
  });

  const setSel = (ids: string[]) => {
    if (!selectedProp) setSelectedLocal(ids);
    onSelect?.(ids);
  };

  const clickRow = (e: React.MouseEvent, id: string, index: number) => {
    if (e.shiftKey && anchor.current) {
      const a = rows.findIndex((r) => r.id === anchor.current);
      const [lo, hi] = a < index ? [a, index] : [index, a];
      setSel(rows.slice(lo, hi + 1).map((r) => r.id));
      return;
    }
    if (e.ctrlKey || e.metaKey) {
      setSel(selectedSet.has(id) ? selected.filter((s) => s !== id) : [...selected, id]);
    } else {
      setSel([id]);
    }
    anchor.current = id;
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "c") {
      const chosen = rows.filter((r) => selectedSet.has(r.id));
      if (!chosen.length) return;
      const head = table.getVisibleLeafColumns().map((c) => (typeof c.columnDef.header === "string" ? c.columnDef.header : c.id));
      const tsv = [head, ...chosen.map(cellText)].map((cells) => cells.join("\t")).join("\n");
      void navigator.clipboard?.writeText(tsv).catch(() => undefined);
      e.preventDefault();
      return;
    }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "a") {
      setSel(rows.map((r) => r.id));
      e.preventDefault();
      return;
    }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      const cur = rows.findIndex((r) => r.id === (anchor.current ?? selected[selected.length - 1]));
      const next = Math.max(0, Math.min(rows.length - 1, cur + (e.key === "ArrowDown" ? 1 : -1)));
      const id = rows[next]?.id;
      if (id) {
        setSel([id]);
        anchor.current = id;
        if (virtual) virt.scrollToIndex(next);
        else scrollRef.current?.querySelector(`[data-row-id="${CSS.escape(id)}"]`)?.scrollIntoView({ block: "nearest" });
      }
      e.preventDefault();
    }
    if (e.key === "Enter" && onActivate) {
      const r = rows.find((x) => x.id === (anchor.current ?? selected[0]));
      if (r) onActivate(r.original);
    }
  };

  const renderRow = (row: Row<T>, index: number, style?: React.CSSProperties) => {
    const isSel = selectedSet.has(row.id);
    const body = (
      <div
        role="row"
        aria-selected={isSel}
        data-row-id={row.id}
        style={{ gridTemplateColumns: template, height: rowHeight, ...style }}
        onClick={(e) => clickRow(e, row.id, index)}
        onDoubleClick={() => onActivate?.(row.original)}
        onContextMenu={() => {
          if (!isSel) setSel([row.id]);
          anchor.current = row.id;
        }}
        className={cn(
          "grid w-full items-center border-b border-line-soft",
          isSel ? "bg-accent-soft outline-1 -outline-offset-1 outline-accent" : "hover:bg-[color-mix(in_srgb,var(--fg)_4%,transparent)]",
          rowClassName?.(row.original),
        )}
      >
        {row.getVisibleCells().map((cell) => {
          const meta = cell.column.columnDef.meta;
          return (
            <div
              key={cell.id}
              role="gridcell"
              className={cn(
                "truncate-1 min-w-0 px-2",
                meta?.align === "right" && "text-right",
                meta?.align === "center" && "text-center",
                meta?.mono && "num",
              )}
            >
              {flexRender(cell.column.columnDef.cell, cell.getContext())}
            </div>
          );
        })}
      </div>
    );
    if (!contextMenu) return <div key={row.id}>{body}</div>;
    const chosen = isSel ? rows.filter((r) => selectedSet.has(r.id)).map((r) => r.original) : [row.original];
    return (
      <ContextMenu key={row.id} items={contextMenu(row.original, chosen)}>
        {body}
      </ContextMenu>
    );
  };

  return (
    <div
      role="grid"
      aria-label={label}
      aria-multiselectable
      tabIndex={0}
      onKeyDown={onKeyDown}
      className={cn("flex min-h-0 flex-col overflow-hidden rounded-[var(--radius)] border border-line bg-panel outline-none", className)}
    >
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-auto">
        <div role="rowgroup" className="sticky top-0 z-10 min-w-fit">
          <div role="row" className="grid h-[26px] items-center border-b border-line bg-panel-2 text-muted" style={{ gridTemplateColumns: template }}>
            {headers.map((h) => {
              const meta = h.column.columnDef.meta;
              const sort = h.column.getIsSorted();
              return (
                <div
                  key={h.id}
                  role="columnheader"
                  aria-sort={sort === "asc" ? "ascending" : sort === "desc" ? "descending" : "none"}
                  className={cn("relative flex h-full min-w-0 items-center px-2", meta?.align === "right" && "justify-end", meta?.align === "center" && "justify-center")}
                >
                  {h.column.getCanSort() ? (
                    <button type="button" className="truncate-1 flex items-center gap-1 hover:text-fg" onClick={h.column.getToggleSortingHandler()}>
                      {flexRender(h.column.columnDef.header, h.getContext())}
                      <span aria-hidden="true" className="text-[9px]">
                        {sort === "asc" ? "▲" : sort === "desc" ? "▼" : ""}
                      </span>
                    </button>
                  ) : (
                    <span className="truncate-1">{flexRender(h.column.columnDef.header, h.getContext())}</span>
                  )}
                  {h.column.getCanResize() && (
                    <span
                      aria-hidden="true"
                      onMouseDown={h.getResizeHandler()}
                      onDoubleClick={() => h.column.resetSize()}
                      className="absolute top-1 right-0 bottom-1 w-[5px] cursor-col-resize border-r border-line hover:border-accent"
                    />
                  )}
                </div>
              );
            })}
          </div>
        </div>
        <div role="rowgroup" className="relative min-w-fit">
          {rows.length === 0 ? (
            <div className="px-3 py-6 text-center text-muted">{empty ?? "Nothing here yet."}</div>
          ) : virtual ? (
            <div style={{ height: virt.getTotalSize(), position: "relative" }}>
              {virt.getVirtualItems().map((vi) =>
                renderRow(rows[vi.index]!, vi.index, { position: "absolute", top: 0, left: 0, transform: `translateY(${vi.start}px)` }),
              )}
            </div>
          ) : (
            rows.map((r, i) => renderRow(r, i))
          )}
        </div>
      </div>
    </div>
  );
}

export type { ColumnDef };
