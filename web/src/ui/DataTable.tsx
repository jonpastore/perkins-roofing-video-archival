/**
 * DataTable — generic sortable/filterable/paginated table for the Perkins admin console.
 *
 * Usage example:
 * ```tsx
 * import { DataTable } from "../ui/DataTable";
 *
 * type Customer = { id: number; name: string; email: string | null; created_at: string };
 *
 * <DataTable<Customer>
 *   columns={[
 *     { key: "name",       header: "Name",    sortable: true, render: (r) => <strong>{r.name}</strong> },
 *     { key: "email",      header: "Email",   sortable: true },
 *     { key: "created_at", header: "Created", sortable: true, align: "right",
 *       render: (r) => new Date(r.created_at).toLocaleDateString() },
 *   ]}
 *   rows={customers}
 *   rowKey={(r) => r.id}
 *   searchableKeys={["name", "email"]}
 *   loading={loading}
 *   error={error}
 * />
 *
 * // Server-side mode: pass onQueryChange and handle fetch yourself.
 * // The table will still render whatever rows you pass in.
 * <DataTable ... onQueryChange={({ search, sort, page, pageSize }) => refetch(...)} />
 * ```
 *
 * Props:
 *   columns        ColDef<R>[]       Column definitions (see ColDef below)
 *   rows           R[]               Data rows (client-side: all rows; server-side: current page)
 *   rowKey         (row: R) => React.Key   Unique key per row
 *   searchableKeys (keyof R)[]        Which keys to search across (client-side only)
 *   loading        boolean
 *   error          string | null | undefined
 *   onQueryChange  optional callback → switches to server-side mode (filter/sort/page left to caller)
 *   defaultPageSize  25 | 50 | 100   (default 50)
 *   totalRows      number            Required for server-side pagination display
 */

import { useState, useMemo, useRef, useEffect } from "react";
import type { ReactNode, CSSProperties } from "react";
import { BRAND, FONT, Card, Loading, ErrorMsg, Button, inputStyle } from "../ui";

// ── Types ──────────────────────────────────────────────────────────────────────

export interface ColDef<R> {
  key: keyof R & string;
  header: string;
  sortable?: boolean;
  render?: (row: R) => ReactNode;
  align?: "left" | "right" | "center";
}

export interface QueryState {
  search: string;
  sort: { key: string; dir: "asc" | "desc" } | null;
  page: number;
  pageSize: number;
}

export interface DataTableProps<R> {
  columns: ColDef<R>[];
  rows: R[];
  rowKey: (row: R) => React.Key;
  searchableKeys?: (keyof R & string)[];
  loading?: boolean;
  error?: string | null;
  onQueryChange?: (q: QueryState) => void;
  defaultPageSize?: 25 | 50 | 100;
  /** Server-side mode: pass the true total so pagination math is correct. */
  totalRows?: number;
}

type SortDir = "asc" | "desc" | "none";

// ── Styles (matching Knowify.tsx TH/TD pattern) ────────────────────────────────

const TH = (align: "left" | "right" | "center" = "left", sortable: boolean): CSSProperties => ({
  padding: "10px 14px",
  color: BRAND.sub,
  fontWeight: 600,
  textAlign: align,
  background: BRAND.bg,
  borderBottom: `2px solid ${BRAND.border}`,
  fontSize: 12,
  textTransform: "uppercase",
  letterSpacing: 0.3,
  whiteSpace: "nowrap",
  cursor: sortable ? "pointer" : "default",
  userSelect: "none",
});

const TD = (align: "left" | "right" | "center" = "left"): CSSProperties => ({
  padding: "10px 14px",
  fontSize: 13,
  borderBottom: `1px solid ${BRAND.border}`,
  verticalAlign: "middle",
  textAlign: align,
});

// ── Sort value extractor ───────────────────────────────────────────────────────

function sortValue(v: unknown): string | number {
  if (v == null) return "";
  if (typeof v === "number") return v;
  if (typeof v === "string") {
    // ISO date strings → numeric for stable date sort
    const d = Date.parse(v);
    if (!isNaN(d) && /^\d{4}-\d{2}-\d{2}/.test(v)) return d;
    return v.toLowerCase();
  }
  return String(v).toLowerCase();
}

function stableSort<R>(arr: R[], key: keyof R, dir: "asc" | "desc"): R[] {
  // attach original index for stability
  return arr
    .map((row, i) => ({ row, i }))
    .sort((a, b) => {
      const av = sortValue(a.row[key]);
      const bv = sortValue(b.row[key]);
      if (av < bv) return dir === "asc" ? -1 : 1;
      if (av > bv) return dir === "asc" ? 1 : -1;
      return a.i - b.i; // stable fallback
    })
    .map(({ row }) => row);
}

// ── Debounce hook ──────────────────────────────────────────────────────────────

function useDebounced(value: string, ms = 220): string {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return debounced;
}

// ── Sort indicator ─────────────────────────────────────────────────────────────

function SortIcon({ dir }: { dir: SortDir }) {
  if (dir === "asc")  return <span style={{ marginLeft: 5, fontSize: 10 }}>▲</span>;
  if (dir === "desc") return <span style={{ marginLeft: 5, fontSize: 10 }}>▼</span>;
  return <span style={{ marginLeft: 5, fontSize: 10, color: BRAND.border }}>⇅</span>;
}

// ── Component ─────────────────────────────────────────────────────────────────

const PAGE_SIZE_OPTIONS = [25, 50, 100] as const;

export function DataTable<R extends object>({
  columns,
  rows,
  rowKey,
  searchableKeys = [],
  loading = false,
  error,
  onQueryChange,
  defaultPageSize = 50,
  totalRows,
}: DataTableProps<R>) {
  const serverMode = Boolean(onQueryChange);

  const [searchInput, setSearchInput] = useState("");
  const search = useDebounced(searchInput);

  const [sortKey, setSortKey] = useState<(keyof R & string) | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>("none");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState<25 | 50 | 100>(defaultPageSize);

  // Reset to page 1 when search/sort/size changes
  const prevSearch = useRef(search);
  const prevSortKey = useRef(sortKey);
  const prevSortDir = useRef(sortDir);
  const prevPageSize = useRef(pageSize);
  useEffect(() => {
    if (
      search !== prevSearch.current ||
      sortKey !== prevSortKey.current ||
      sortDir !== prevSortDir.current ||
      pageSize !== prevPageSize.current
    ) {
      setPage(1);
      prevSearch.current = search;
      prevSortKey.current = sortKey;
      prevSortDir.current = sortDir;
      prevPageSize.current = pageSize;
    }
  }, [search, sortKey, sortDir, pageSize]);

  // Notify parent in server-side mode
  useEffect(() => {
    if (!serverMode) return;
    onQueryChange!({
      search,
      sort: sortKey && sortDir !== "none" ? { key: sortKey, dir: sortDir } : null,
      page,
      pageSize,
    });
  }, [search, sortKey, sortDir, page, pageSize, serverMode]); // eslint-disable-line react-hooks/exhaustive-deps

  // Client-side filter + sort + paginate
  const processed = useMemo<R[]>(() => {
    if (serverMode) return rows;

    // filter
    let out = rows;
    const q = search.trim().toLowerCase();
    if (q && searchableKeys.length > 0) {
      out = out.filter((row) =>
        searchableKeys.some((k) => {
          const v = row[k];
          if (v == null) return false;
          return String(v).toLowerCase().includes(q);
        })
      );
    }

    // sort
    if (sortKey && sortDir !== "none") {
      out = stableSort(out, sortKey, sortDir);
    }

    return out;
  }, [rows, search, searchableKeys, sortKey, sortDir, serverMode]);

  const total = serverMode ? (totalRows ?? rows.length) : processed.length;
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const safePage = Math.min(page, pageCount);

  const visible = useMemo<R[]>(() => {
    if (serverMode) return rows;
    const start = (safePage - 1) * pageSize;
    return processed.slice(start, start + pageSize);
  }, [processed, safePage, pageSize, serverMode, rows]);

  const rangeStart = total === 0 ? 0 : (safePage - 1) * pageSize + 1;
  const rangeEnd = Math.min(safePage * pageSize, total);

  function handleHeaderClick(col: ColDef<R>) {
    if (!col.sortable) return;
    if (sortKey !== col.key) {
      setSortKey(col.key);
      setSortDir("asc");
    } else {
      // tri-state: asc → desc → none
      setSortDir((d) => (d === "asc" ? "desc" : d === "desc" ? "none" : "asc"));
      if (sortDir === "none") setSortKey(col.key);
    }
  }

  function handlePageSize(e: React.ChangeEvent<HTMLSelectElement>) {
    setPageSize(Number(e.target.value) as 25 | 50 | 100);
  }

  return (
    <Card style={{ padding: 0, overflow: "hidden" }}>
      {/* Toolbar */}
      <div style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "12px 16px",
        borderBottom: `1px solid ${BRAND.border}`,
        flexWrap: "wrap",
        background: "#fff",
      }}>
        <input
          type="search"
          placeholder="Search…"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          style={{ ...inputStyle, width: 220, fontSize: 13, padding: "7px 12px" }}
        />
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 12, color: BRAND.sub, whiteSpace: "nowrap" }}>
            {total === 0 ? "No rows" : `${rangeStart}–${rangeEnd} of ${total.toLocaleString()}`}
          </span>
          <select
            value={pageSize}
            onChange={handlePageSize}
            style={{
              padding: "6px 8px",
              border: `1px solid ${BRAND.border}`,
              borderRadius: 8,
              fontSize: 12,
              fontFamily: FONT,
              cursor: "pointer",
            }}
          >
            {PAGE_SIZE_OPTIONS.map((n) => (
              <option key={n} value={n}>{n} / page</option>
            ))}
          </select>
        </div>
      </div>

      {/* Table body */}
      {loading ? (
        <div style={{ padding: 24 }}><Loading /></div>
      ) : error ? (
        <div style={{ padding: 24 }}><ErrorMsg>{error}</ErrorMsg></div>
      ) : visible.length === 0 ? (
        <div style={{ padding: 32, textAlign: "center", color: BRAND.sub, fontSize: 14 }}>
          {search.trim() ? "No rows match your search." : "No data to display."}
        </div>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, fontFamily: FONT }}>
            <thead>
              <tr>
                {columns.map((col) => {
                  const dir: SortDir = sortKey === col.key ? sortDir : "none";
                  return (
                    <th
                      key={col.key}
                      style={TH(col.align ?? "left", Boolean(col.sortable))}
                      onClick={() => handleHeaderClick(col)}
                    >
                      {col.header}
                      {col.sortable && <SortIcon dir={dir} />}
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {visible.map((row) => (
                <tr key={rowKey(row)}>
                  {columns.map((col) => (
                    <td key={col.key} style={TD(col.align ?? "left")}>
                      {col.render ? col.render(row) : (row[col.key] as ReactNode) ?? "—"}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination footer */}
      {!loading && !error && total > 0 && (
        <div style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "flex-end",
          gap: 6,
          padding: "10px 16px",
          borderTop: `1px solid ${BRAND.border}`,
          background: "#fff",
        }}>
          <Button variant="ghost" disabled={safePage <= 1} onClick={() => setPage(1)} style={{ fontSize: 12, padding: "6px 12px" }}>
            «
          </Button>
          <Button variant="ghost" disabled={safePage <= 1} onClick={() => setPage((p) => p - 1)} style={{ fontSize: 12, padding: "6px 12px" }}>
            Prev
          </Button>
          <span style={{ fontSize: 12, color: BRAND.sub, minWidth: 70, textAlign: "center" }}>
            {safePage} / {pageCount}
          </span>
          <Button variant="ghost" disabled={safePage >= pageCount} onClick={() => setPage((p) => p + 1)} style={{ fontSize: 12, padding: "6px 12px" }}>
            Next
          </Button>
          <Button variant="ghost" disabled={safePage >= pageCount} onClick={() => setPage(pageCount)} style={{ fontSize: 12, padding: "6px 12px" }}>
            »
          </Button>
        </div>
      )}
    </Card>
  );
}
