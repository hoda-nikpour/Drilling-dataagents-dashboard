import React, {useEffect, useMemo, useRef, useState} from "react";
import {Streamlit} from "streamlit-component-lib";
import {nextInteractionOrder} from "./interactionOrder.mjs";
import {downloadText} from "./download.mjs";

const PAGE_SIZE = 50;
const HIDDEN_COLUMNS = new Set(["window", "window_start", "window_end"]);
const text = (value) => value == null ? "" : String(value);

export default function AgentIntervalTable({args = {}}) {
  const rootRef = useRef(null);
  const clickOrderRef = useRef(0);
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [sort, setSort] = useState({column: "start", descending: false});
  const [opened, setOpened] = useState(null);
  const [expanded, setExpanded] = useState(false);
  const allColumns = args.columns || [];
  const columns = useMemo(() => allColumns.filter((column) => !HIDDEN_COLUMNS.has(column)), [allColumns]);
  const rows = args.rows || [];

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    let frame = null;
    const resize = () => {
      if (frame !== null) cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        frame = null;
        Streamlit.setFrameHeight(Math.ceil(root.getBoundingClientRect().height));
      });
    };
    const observer = new ResizeObserver(resize);
    observer.observe(root);
    resize();
    return () => {
      observer.disconnect();
      if (frame !== null) cancelAnimationFrame(frame);
    };
  }, []);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase().replace(/^(\d{2})\.(\d{2})\.(\d{4})/, "$3-$2-$1");
    const selected = rows.map((row, index) => ({row, index})).filter(({row}) =>
      !needle || columns.some((column) => text(row[column]).toLowerCase().includes(needle)),
    );
    return selected.sort((a, b) => {
      const av = a.row[sort.column], bv = b.row[sort.column];
      let result;
      if (typeof av === "number" && typeof bv === "number") result = av - bv;
      else result = text(av).localeCompare(text(bv));
      return (sort.descending ? -result : result) || a.index - b.index;
    });
  }, [rows, columns, query, sort]);

  const lastPage = Math.max(0, Math.ceil(filtered.length / PAGE_SIZE) - 1);
  const activePage = Math.min(page, lastPage);
  const visible = filtered.slice(activePage * PAGE_SIZE, (activePage + 1) * PAGE_SIZE);

  function openInterval(index) {
    setOpened(index);
    const order = nextInteractionOrder(Math.max(clickOrderRef.current,Number(args.latest_click_order || 0)));
    clickOrderRef.current = order;
    Streamlit.setComponentValue({
      event: "agent_interval_click",
      request_id: window.crypto?.randomUUID?.() || `interval-${Date.now()}-${Math.random().toString(36).slice(2)}`,
      request_order: order,
      row_index: index,
      context_key: args.context_key,
      table_revision: args.table_revision,
      browser_session_token: args.browser_session_token,
    });
  }

  function downloadExcel() {
    if (!args.excel_base64) return;
    const bytes=Uint8Array.from(atob(args.excel_base64),character=>character.charCodeAt(0));
    downloadText(bytes,"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      args.excel_filename || "agent_intervals.xlsx");
  }

  return (
    <div ref={rootRef} className="ait-root">
      <div className="ait-toolbar">
        <input aria-label="Search agent intervals" placeholder="Search intervals or date…" value={query}
          onChange={(event) => {setQuery(event.target.value); setPage(0);}} />
        <button type="button" onClick={downloadExcel} disabled={!args.excel_base64}
          title="Download all intervals for the selected data agent as an editable Excel workbook.">Download Excel</button>
        <button type="button" onClick={() => setExpanded((value) => !value)}>{expanded ? "Compact table" : "Expand table"}</button>
      </div>
      <div className="ait-scroll" style={{maxHeight: expanded ? 720 : 360}}>
        <table>
          <thead><tr>{columns.map((column) => (
            <th key={column} aria-sort={sort.column === column ? (sort.descending ? "descending" : "ascending") : "none"}>
              <button type="button" data-sort-column={column} onClick={() => {
                setSort((old) => ({column, descending: old.column === column ? !old.descending : false}));
                setPage(0);
              }}>
                {column === "start" ? "Start · go to chart" : column}
                {sort.column === column ? (sort.descending ? " ↓" : " ↑") : ""}
              </button>
            </th>
          ))}</tr></thead>
          <tbody>{visible.map(({row, index}) => (
            <tr key={index} className={opened === index ? "ait-opened" : ""}>
              {columns.map((column) => <td key={column} data-column={column}>{column === "start"
                ? <button type="button" className="ait-start" data-interval-start={text(row.start)}
                    aria-label={`Show interval starting ${text(row.start)}`} onClick={() => openInterval(index)}>{text(row.start)}</button>
                : text(row[column])}</td>)}
            </tr>
          ))}</tbody>
        </table>
      </div>
      <div className="ait-pager">
        <button type="button" disabled={activePage === 0} onClick={() => setPage(activePage - 1)}>Previous</button>
        <span>{filtered.length ? `${activePage * PAGE_SIZE + 1}–${Math.min((activePage + 1) * PAGE_SIZE, filtered.length)}` : "0"} of {filtered.length} intervals</span>
        <button type="button" disabled={activePage === lastPage} onClick={() => setPage(activePage + 1)}>Next</button>
      </div>
    </div>
  );
}
