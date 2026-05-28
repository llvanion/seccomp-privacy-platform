import { useMemo, useState, type ReactNode } from "react";
import { ChevronDown, ChevronsUpDown, ChevronUp } from "lucide-react";
import { cx } from "@/lib/cx";

export type Column<T> = {
  id: string;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  sortKey?: (row: T) => string | number | null | undefined;
  className?: string;
  thClassName?: string;
  width?: string;
};

export function DataTable<T>({
  rows,
  columns,
  rowKey,
  empty,
  caption,
  className,
  onRowClick,
  initialSort,
  loading,
}: {
  rows: T[];
  columns: Column<T>[];
  rowKey: (row: T, index: number) => string;
  empty?: ReactNode;
  caption?: ReactNode;
  className?: string;
  onRowClick?: (row: T) => void;
  initialSort?: { id: string; dir: "asc" | "desc" };
  loading?: boolean;
}) {
  const [sort, setSort] = useState(initialSort);

  const sortedRows = useMemo(() => {
    if (!sort) return rows;
    const column = columns.find((c) => c.id === sort.id);
    if (!column?.sortKey) return rows;
    const sortKey = column.sortKey;
    const dir = sort.dir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      const av = sortKey(a);
      const bv = sortKey(b);
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (av < bv) return -1 * dir;
      if (av > bv) return 1 * dir;
      return 0;
    });
  }, [rows, columns, sort]);

  return (
    <div className={cx("panel overflow-hidden", className)}>
      <div className="overflow-x-auto">
        <table className="data-grid">
          {caption && <caption className="text-2xs text-ink-muted px-3 py-2 text-left">{caption}</caption>}
          <thead>
            <tr>
              {columns.map((col) => {
                const sortable = !!col.sortKey;
                const active = sort?.id === col.id;
                const dir = active ? sort?.dir : undefined;
                return (
                  <th
                    key={col.id}
                    className={cx(col.thClassName, sortable && "cursor-pointer select-none")}
                    style={col.width ? { width: col.width } : undefined}
                    onClick={
                      sortable
                        ? () =>
                            setSort((prev) =>
                              prev?.id === col.id
                                ? { id: col.id, dir: prev.dir === "asc" ? "desc" : "asc" }
                                : { id: col.id, dir: "asc" },
                            )
                        : undefined
                    }
                  >
                    <span className="inline-flex items-center gap-1">
                      {col.header}
                      {sortable && (
                        <>
                          {!active && <ChevronsUpDown className="w-3 h-3 text-ink-dim" />}
                          {active && dir === "asc" && <ChevronUp className="w-3 h-3" />}
                          {active && dir === "desc" && <ChevronDown className="w-3 h-3" />}
                        </>
                      )}
                    </span>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={columns.length}>
                  <div className="space-y-2 py-2">
                    <div className="shimmer h-6 rounded" />
                    <div className="shimmer h-6 rounded" />
                    <div className="shimmer h-6 rounded" />
                  </div>
                </td>
              </tr>
            )}
            {!loading && sortedRows.length === 0 && (
              <tr>
                <td colSpan={columns.length}>
                  <div className="py-8 text-center text-ink-muted text-2xs">{empty ?? "没有数据"}</div>
                </td>
              </tr>
            )}
            {!loading &&
              sortedRows.map((row, i) => (
                <tr
                  key={rowKey(row, i)}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  className={onRowClick ? "cursor-pointer" : undefined}
                >
                  {columns.map((col) => (
                    <td key={col.id} className={col.className}>
                      {col.cell(row)}
                    </td>
                  ))}
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
