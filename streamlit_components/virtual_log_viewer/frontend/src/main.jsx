
import React, {useCallback, useEffect, useMemo, useRef, useState} from "react";
import {createRoot} from "react-dom/client";
import Plotly from "plotly.js-dist-min";
import {Streamlit, withStreamlitConnection} from "streamlit-component-lib";
import "./style.css";

const HOUR_MS = 3600 * 1000;
const MIN_VIEWPORT_SPAN_MS = 30 * 1000;


function toMs(value) {
  const d = new Date(value);
  const t = d.getTime();
  return Number.isFinite(t) ? t : null;
}

function fmtTime(ms) {
  const d = new Date(ms);
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mi = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd} ${hh}:${mi}:${ss}`;
}

function clamp(value, minValue, maxValue) {
  return Math.max(minValue, Math.min(maxValue, value));
}

function htmlEscape(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function safeDownloadName(value, fallback = "data agent") {
  const text = String(value || fallback)
    .replace(/[\\/:*?"<>|]+/g, "_")
    .replace(/\s+/g, " ")
    .trim();

  return text || fallback;
}

function normalize(values) {
  const nums = values.filter((v) => Number.isFinite(Number(v))).map(Number);
  if (!nums.length) return values.map(() => null);
  const mn = Math.min(...nums);
  const mx = Math.max(...nums);
  if (Math.abs(mx - mn) < 1e-12) return values.map((v) => (v == null ? null : 0.5));
  return values.map((v) => (v == null || !Number.isFinite(Number(v)) ? null : (Number(v) - mn) / (mx - mn)));
}

function formatLimitValue(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "";
  const abs = Math.abs(n);
  if ((abs >= 1000 || abs < 0.01) && abs !== 0) return n.toExponential(2);
  if (abs >= 100) return n.toFixed(0);
  if (abs >= 10) return n.toFixed(1);
  return n.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
}

function curveLimitsText(curve) {
  const label = String(curve?.label || curve?.raw_col || "Parameter").trim();
  const unit = String(curve?.unit || "").trim();
  const nums = (Array.isArray(curve?.x) ? curve.x : [])
    .map(Number)
    .filter((value) => Number.isFinite(value));

  if (!nums.length) {
    return unit ? `${label}: no valid data (${unit})` : `${label}: no valid data`;
  }

  const mn = Math.min(...nums);
  const mx = Math.max(...nums);
  const limits = `${formatLimitValue(mn)} – ${formatLimitValue(mx)}`;
  return unit ? `${label}: ${limits} ${unit}` : `${label}: ${limits}`;
}

function rowIdentity(row) {
  return [
    row.well || "",
    row.section || "",
    row.tag_label || "",
    row.tag_start || "",
    row.tag_end || "",
  ].join("|");
}

function mergeRows(a, b) {
  const out = [];
  const seen = new Set();
  [...(a || []), ...(b || [])].forEach((row) => {
    const id = rowIdentity(row || {});
    if (!id) return;
    const ix = out.findIndex((r) => rowIdentity(r) === id);
    if (ix >= 0) out[ix] = row;
    else if (!seen.has(id)) {
      seen.add(id);
      out.push(row);
    }
  });
  out.sort((r1, r2) => (toMs(r1.tag_start) || 0) - (toMs(r2.tag_start) || 0));
  return out;
}
function normalizeRowsForServer(rows) {
  const out = [];
  const seen = new Set();
  (Array.isArray(rows) ? rows : []).forEach((row) => {
    if (!row || typeof row !== "object") return;
    const start = row.tag_start ? fmtTime(toMs(row.tag_start)) : "";
    const end = row.tag_end ? fmtTime(toMs(row.tag_end)) : "";
    if (!start || !end || start === end) return;
    const key = [row.well || "", row.section || "", start, end].join("|");
    if (seen.has(key)) return;
    seen.add(key);
    out.push({...row, tag_start: start, tag_end: end});
  });
  out.sort((a, b) => (toMs(a.tag_start) || 0) - (toMs(b.tag_start) || 0));
  return out;
}



const CHART_TAG_SOURCES = ["chart_drag", "client_drag_tag", "visual", "visual_tag", "dragged", "server_tagger"];

function isChartSource(source) {
  return CHART_TAG_SOURCES.includes(String(source || "").trim());
}

function stableTagIdFromParts(label, start, end, idx = 0) {
  const text = `${label}|${start}|${end}|${idx}`;
  let h = 2166136261;
  for (let i = 0; i < text.length; i += 1) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return `tag_${(h >>> 0).toString(36)}`;
}

function tagKey(tag) {
  const source = isChartTag(tag) ? "chart_drag" : (String(tag?.source || "manual").trim() || "manual");
  const label = String(tag?.label || "").trim();
  const startMs = toMs(tag?.start);
  const endMs = toMs(tag?.end);
  const start = startMs == null ? String(tag?.start || "").trim() : fmtTime(startMs);
  const end = endMs == null ? String(tag?.end || "").trim() : fmtTime(endMs);

  // v7: chart-drawn tags are identical when their interval is identical.
  // Do not use created_at. Previous code produced two ids for the same hit
  // interval: a browser Date.now id and a stable tag_ id.
  if (source === "chart_drag") return `${source}|${start}|${end}`;

  return `${source}|${label}|${start}|${end}`;
}

function isChartTag(tag) {
  return isChartSource(tag?.source);
}

function isEditableTrackTag(tag) {
  const s = toMs(tag?.start);
  const e = toMs(tag?.end);
  return s != null && e != null && e > s;
}

function normalizeTag(tag, idx = 0) {
  if (!tag || typeof tag !== "object") return null;
  const startMs = toMs(tag.start);
  const endMs = toMs(tag.end);
  if (startMs == null || endMs == null || endMs <= startMs) return null;

  const source = String(tag.source || "manual").trim() || "manual";
  const chartTag = isChartSource(source);
  const start = fmtTime(startMs);
  const end = fmtTime(endMs);
  const label = String(tag.label || (chartTag ? `Dragged Tag ${idx + 1}` : `Tag ${idx + 1}`)).trim();
  const createdAt = chartTag ? stableTagIdFromParts(label, start, end, 0) : "";

  return {
    ...tag,
    label: label || (chartTag ? `Dragged Tag ${idx + 1}` : `Tag ${idx + 1}`),
    start,
    end,
    source,
    created_at: createdAt,
  };
}

function dedupeTags(items) {
  const out = [];
  const seen = new Set();
  (items || []).forEach((item, idx) => {
    const normalized = normalizeTag(item, idx);
    if (!normalized) return;
    const key = tagKey(normalized);
    if (seen.has(key)) return;
    seen.add(key);
    out.push(normalized);
  });
  return out;
}

function chartTagsForServer(items) {
  return dedupeTags(items)
    .filter(isChartTag)
    .map((tag, idx) => {
      const start = fmtTime(toMs(tag.start));
      const end = fmtTime(toMs(tag.end));
      const label = tag.label || `Dragged Tag ${idx + 1}`;
      return {
        label,
        start,
        end,
        source: "chart_drag",
        created_at: stableTagIdFromParts(label, start, end, 0),
      };
    });
}

function stableJson(value) {
  try {
    return JSON.stringify(value ?? null);
  } catch (err) {
    return "";
  }
}


function chartTagStorageKey(contextKey, sessionToken) {
  const safeContext = String(contextKey || "default");
  const safeSession = String(sessionToken || "fresh");
  return `hoda_virtual_chart_tags_${safeContext}_${safeSession}`;
}

function latestChartTagStorageKey(contextKey) {
  return `hoda_virtual_chart_tags_latest_${String(contextKey || "default")}`;
}

function legacyChartTagStorageKey(contextKey) {
  return `hoda_virtual_chart_tags_${String(contextKey || "default")}`;
}

function hitResultStorageKey(contextKey, sessionToken) {
  const safeContext = String(contextKey || "default");
  const safeSession = String(sessionToken || "fresh");
  return `hoda_hit_result_history_${safeContext}_${safeSession}`;
}

function latestHitResultStorageKey(contextKey) {
  return `hoda_virtual_hit_results_latest_${String(contextKey || "default")}`;
}

function allTagStorageKey(contextKey, sessionToken) {
  const safeContext = String(contextKey || "default");
  const safeSession = String(sessionToken || "fresh");
  return `hoda_virtual_all_tags_${safeContext}_${safeSession}`;
}

function latestAllTagStorageKey(contextKey) {
  return `hoda_virtual_all_tags_latest_${String(contextKey || "default")}`;
}

function saveStoredAllTags(contextKey, sessionToken, items) {
  if (typeof window === "undefined") return;
  const payload = dedupeTags(items || []);
  const text = JSON.stringify(payload);

  try {
    window.sessionStorage.setItem(allTagStorageKey(contextKey, sessionToken), text);
    window.sessionStorage.setItem(latestAllTagStorageKey(contextKey), text);
  } catch (err) {}

  try {
    window.localStorage.setItem(latestAllTagStorageKey(contextKey), text);
  } catch (err) {}
}

function loadStoredChartTags(contextKey, sessionToken, allowLegacy = false) {
  if (typeof window === "undefined") return [];
  try {
    let raw = window.sessionStorage.getItem(chartTagStorageKey(contextKey, sessionToken));
    if (!raw) raw = window.localStorage.getItem(chartTagStorageKey(contextKey, sessionToken));
    if (!raw && allowLegacy) {
      raw = window.sessionStorage.getItem(legacyChartTagStorageKey(contextKey));
    }
    const parsed = JSON.parse(raw || "[]");
    return dedupeTags(Array.isArray(parsed) ? parsed : []).filter(isChartTag);
  } catch (err) {
    return [];
  }
}

function saveStoredChartTags(contextKey, sessionToken, items) {
  if (typeof window === "undefined") return;
  const safeChartTags = chartTagsForServer(items || []);
  try {
    const payload = JSON.stringify(safeChartTags);
    const sessionKey = chartTagStorageKey(contextKey, sessionToken);
    const latestKey = latestChartTagStorageKey(contextKey);

    // v7: current-tab sessionStorage is the source of truth. The latest localStorage
    // key is overwritten with the cleaned list only for sidebar Save Dashboard Session.
    window.sessionStorage.setItem(sessionKey, payload);
    window.sessionStorage.setItem(latestKey, payload);
    window.localStorage.setItem(latestKey, payload);
  } catch (err) {
    // Browser storage failure should not break tag drawing.
  }
}

function saveStoredHitRows(contextKey, sessionToken, rows) {
  if (typeof window === "undefined") return;
  const safeRows = normalizeRowsForServer(rows);
  try {
    window.localStorage.setItem(
      hitResultStorageKey(contextKey, sessionToken),
      JSON.stringify(safeRows),
    );
    window.localStorage.setItem(
      latestHitResultStorageKey(contextKey),
      JSON.stringify(safeRows),
    );
  } catch (err) {
    // Browser storage failure should not break plotting.
  }
}

function clearStoredChartTags(contextKey, sessionToken) {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(chartTagStorageKey(contextKey, sessionToken));
    window.sessionStorage.setItem(latestChartTagStorageKey(contextKey), "[]");
    window.localStorage.removeItem(chartTagStorageKey(contextKey, sessionToken));
    window.localStorage.setItem(latestChartTagStorageKey(contextKey), "[]");
  } catch (err) {
    // Safe to ignore.
  }
}

function mergeManualAndChartTags(serverTags, localChartTags) {
  const manual = dedupeTags(serverTags || []).filter((tag) => !isChartTag(tag));
  const chart = dedupeTags([...(serverTags || []), ...(localChartTags || [])]).filter(isChartTag);
  return dedupeTags([...manual, ...chart]);
}

function makeTimeAxis(rangeStart, rangeEnd, showLabels = false, height = 950) {
  const majorTicks = Math.max(14, Math.min(36, Math.round(Number(height || 950) / 55)));
  return {
    domain: [0, 1],
    type: "date",
    range: [fmtTime(rangeEnd), fmtTime(rangeStart)],
    showgrid: true,
    gridcolor: "rgba(120,120,120,0.26)",
    gridwidth: 0.75,
    tickmode: "auto",
    nticks: majorTicks,
    tickformat: "%d-%b-%y<br>%H:%M:%S",
    tickfont: {size: 10, family: "Courier New, monospace"},
    ticklabelposition: "outside left",
    automargin: true,
    showticklabels: Boolean(showLabels),
    showspikes: false,
    zeroline: false,
    minor: {
      dtick: 15 * 60 * 1000,
      showgrid: true,
      gridcolor: "rgba(150,150,150,0.14)",
      gridwidth: 0.45,
    },
  };
}

function buildDomains() {
  const gridAxis = (domain, title) => ({
    domain,
    title,
    range: [0, 1],
    fixedrange: true,
    showgrid: true,
    gridcolor: "rgba(130,130,130,0.24)",
    gridwidth: 0.7,
    zeroline: false,
    showticklabels: false,
    tickmode: "array",
    tickvals: Array.from({length: 21}, (_, i) => i / 20),
    minor: {
      tick0: 0,
      dtick: 0.025,
      showgrid: true,
      gridcolor: "rgba(150,150,150,0.11)",
      gridwidth: 0.35,
    },
  });

  return {
    xaxis: gridAxis([0.00, 0.23], ""),
    xaxis2: gridAxis([0.255, 0.485], ""),
    xaxis3: gridAxis([0.51, 0.74], ""),
    xaxis4: gridAxis([0.775, 1.0], ""),
  };
}

function traceAxis(trackNo) {
  if (trackNo === 1) return {xaxis: "x", yaxis: "y"};
  return {xaxis: `x${trackNo}`, yaxis: `y${trackNo}`};
}

function buildCurveTraces(trackData) {
  const traces = [];
  const colors = ["#8e44ad", "#2f80ed", "#27ae60", "#d35400", "#7f8c8d"];
  (trackData?.tracks || []).forEach((track) => {
    const trackNo = Number(track.track || 1);
    const axis = traceAxis(trackNo);
    (track.curves || []).forEach((curve, curveIdx) => {
      const xNorm = normalize(curve.x || []);
      traces.push({
        type: "scatter",
        mode: "lines",
        x: xNorm,
        y: curve.y || [],
        xaxis: axis.xaxis,
        yaxis: axis.yaxis,
        line: {width: 1.5, color: colors[curveIdx % colors.length], simplify: false},
        connectgaps: false,
        name: `${curve.label}`,
        hoverinfo: "none",
        meta: {
          label: curve.label || curve.raw_col || "Value",
          unit: curve.unit || "",
          raw_values: curve.x || [],
        },
        customdata: (curve.x || []).map((v) => [v]),
        showlegend: false,
      });
    });
  });
  return traces;
}

function buildGridKeepaliveTraces(rangeStartMs, rangeEndMs) {
  const start = Number.isFinite(Number(rangeStartMs)) ? Number(rangeStartMs) : Date.now();
  const end = Number.isFinite(Number(rangeEndMs)) && Number(rangeEndMs) > start
    ? Number(rangeEndMs)
    : start + 12 * HOUR_MS;

  return [1, 2, 3, 4].map((trackNo) => {
    const axis = traceAxis(trackNo);
    return {
      type: "scatter",
      mode: "lines",
      x: [0, 1],
      y: [fmtTime(start), fmtTime(end)],
      xaxis: axis.xaxis,
      yaxis: axis.yaxis,
      line: {width: 0, color: "rgba(0,0,0,0)"},
      marker: {opacity: 0},
      hoverinfo: "skip",
      showlegend: false,
      meta: {source: "dense_grid_keepalive"},
      name: `Track ${trackNo} grid`,
    };
  });
}

function normalizeAgentIntervals(agentIntervals) {
  return (agentIntervals || [])
    .map((item, idx) => {
      const s = toMs(item.start);
      const e = toMs(item.end);
      if (s == null || e == null) return null;
      const startMs = Math.min(s, e);
      const endMs = Math.max(s, e);
      if (endMs <= startMs) return null;
      return {
        startMs,
        endMs,
        start: fmtTime(startMs),
        end: fmtTime(endMs),
        label: item.label || "Agent hit",
        severity: item.severity || "",
        idx,
      };
    })
    .filter(Boolean);
}

function App(props) {
  const args = props.args || {};
  const plotRef = useRef(null);
  const rootRef = useRef(null);
  const wrapRef = useRef(null);
  const hoverLineRef = useRef(null);
  const hoverBoxRef = useRef(null);
  const selectBoxRef = useRef(null);
  const captureRef = useRef(null);
  const plotInitializedRef = useRef(false);
  const requestLockRef = useRef(false);
  const lastSentViewportRef = useRef("");
  const dragRef = useRef({active: false, startY: null, currentY: null});
  const resizeRef = useRef({active: false, boundary: null});
  const zoomHistoryRef = useRef([]);
  const initialRangesRef = useRef(null);
  const lastRangesRef = useRef(null);
  const programmaticRelayoutRef = useRef(false);
  const zoomModeRef = useRef("y");
  const tagModeRef = useRef(false);
  const doubleClickLockRef = useRef(false);
  const suppressStateUpdateRef = useRef(true);
  const lastStatePayloadRef = useRef("");
  const pendingLocalChartTagsJsonRef = useRef("");

  // Stable virtual-scroll state. Wheel movement is accumulated in refs and
  // flushed with requestAnimationFrame. This avoids a React/Plotly rerender loop
  // while the user is scrolling or resizing a tag.
  const initialPlotRangeRef = useRef(null);
  const viewportStartRef = useRef(null);
  const wheelDeltaRef = useRef(0);
  const wheelRafRef = useRef(null);
  const arrowScrollRef = useRef({active: false, direction: 0, rafId: null, lastTs: 0});
  const viewportSpanRef = useRef(null);
  const suppressNextBufferRequestRef = useRef(false);

  const height = Number(args.height || 950);
  const visibleHours = Number(args.visible_hours || 12);
  const marginHours = Number(args.buffer_margin_hours || 4);
  const visibleMs = visibleHours * HOUR_MS;
  const browserSessionToken = String(args.browser_session_token || "fresh");
  const restoreSavedDashboard = Boolean(args.restore_saved_dashboard);
  const propViewportSpanMs = clamp(
    Number(args.viewport_span_seconds || 0) > 0 ? Number(args.viewport_span_seconds) * 1000 : visibleMs,
    MIN_VIEWPORT_SPAN_MS,
    visibleMs,
  );

  const sectionStartMs = toMs(args.section_start);
  const sectionEndMs = toMs(args.section_end);
  const bufferStartMs = toMs(args.buffer_start || args.track_data?.time_start);
  const bufferEndMs = toMs(args.buffer_end || args.track_data?.time_end);
  const initialViewportStartMs = toMs(args.viewport_start) || bufferStartMs || sectionStartMs;
  if (initialPlotRangeRef.current == null) initialPlotRangeRef.current = initialViewportStartMs;
  if (viewportStartRef.current == null) viewportStartRef.current = initialViewportStartMs;
  if (viewportSpanRef.current == null) viewportSpanRef.current = propViewportSpanMs;

  const [viewportStartMs, setViewportStartMs] = useState(initialViewportStartMs);
  const [viewportSpanMs, setViewportSpanMs] = useState(propViewportSpanMs);
  const [tagMode, setTagMode] = useState(Boolean(args.saved_tag_mode));
  const [zoomMode, setZoomModeState] = useState("y");
  const [zoomHistoryCount, setZoomHistoryCount] = useState(0);
  const [redoTags, setRedoTags] = useState([]);
  const [tags, setTags] = useState(() =>
    mergeManualAndChartTags(
      Array.isArray(args.saved_tags) ? args.saved_tags : [],
      loadStoredChartTags(args.context_key, browserSessionToken, restoreSavedDashboard),
    ),
  );
  const [selectedTagId, setSelectedTagId] = useState(null);
  const [hitRows, setHitRows] = useState(Array.isArray(args.saved_hit_results) ? args.saved_hit_results : []);

  useEffect(() => {
    // Give the component keyboard focus on first render so T/Z work without
    // needing the first mouse click on the Tagging button.
    try {
      rootRef.current?.focus?.({preventScroll: true});
    } catch (err) {
      // Safe to ignore in browsers that do not support focus options.
    }
  }, []);

  const clampViewport = useCallback(
    (ms, spanMs = null) => {
      if (sectionStartMs == null || sectionEndMs == null) return ms;
      const rawSpan = Number(spanMs ?? viewportSpanRef.current ?? visibleMs);
      const span = clamp(Number.isFinite(rawSpan) ? rawSpan : visibleMs, MIN_VIEWPORT_SPAN_MS, visibleMs);
      const latest = Math.max(sectionStartMs, sectionEndMs - span);
      return clamp(ms, sectionStartMs, latest);
    },
    [sectionStartMs, sectionEndMs, visibleMs],
  );

  useEffect(() => {
    tagModeRef.current = tagMode;
  }, [tagMode]);

  useEffect(() => {
    if (Boolean(args.saved_tag_mode) !== tagModeRef.current) {
      setTagMode(Boolean(args.saved_tag_mode));
      tagModeRef.current = Boolean(args.saved_tag_mode);
    }
  }, [args.saved_tag_mode]);

  // Important: do not resync viewport_start from Streamlit on every rerun.
  // While the Python side is reloading a buffer it can temporarily send the
  // previous viewport_start. Resyncing here is what made the plot jump back
  // after the mouse/trackpad was released.
  const contextKeyRef = useRef(args.context_key || "");
  const bufferKeyRef = useRef(`${bufferStartMs || ""}|${bufferEndMs || ""}`);
  useEffect(() => {
    const currentContextKey = args.context_key || "";
    const currentBufferKey = `${bufferStartMs || ""}|${bufferEndMs || ""}`;
    const contextChanged = contextKeyRef.current !== currentContextKey;
    const bufferChanged = bufferKeyRef.current !== currentBufferKey;

    if (contextChanged) {
      const newStart = toMs(args.viewport_start) || bufferStartMs || sectionStartMs;
      if (!restoreSavedDashboard) {
        clearStoredChartTags(currentContextKey, browserSessionToken);
      }
      contextKeyRef.current = currentContextKey;
      bufferKeyRef.current = currentBufferKey;
      initialPlotRangeRef.current = newStart;
      viewportStartRef.current = newStart;
      viewportSpanRef.current = propViewportSpanMs;
      setViewportSpanMs(propViewportSpanMs);
      zoomHistoryRef.current = [];
      lastStatePayloadRef.current = "";
      suppressStateUpdateRef.current = true;
      setZoomHistoryCount(0);
      setViewportStartMs(newStart);
      return;
    }

    if (bufferChanged) {
      bufferKeyRef.current = currentBufferKey;
      const current = viewportStartRef.current ?? toMs(args.viewport_start) ?? bufferStartMs ?? sectionStartMs;
      const clamped = clampViewport(current, viewportSpanRef.current);
      viewportStartRef.current = clamped;
      setViewportStartMs(clamped);
      requestLockRef.current = false;
    }
  }, [args.context_key, args.viewport_start, bufferStartMs, bufferEndMs, sectionStartMs, clampViewport, browserSessionToken, restoreSavedDashboard, propViewportSpanMs]);

  useEffect(() => {
    viewportStartRef.current = viewportStartMs;
  }, [viewportStartMs]);

  useEffect(() => {
    return () => {
      if (wheelRafRef.current != null) cancelAnimationFrame(wheelRafRef.current);
      if (arrowScrollRef.current.rafId != null) cancelAnimationFrame(arrowScrollRef.current.rafId);
    };
  }, []);

  useEffect(() => {
    const incomingServer = dedupeTags(Array.isArray(args.saved_tags) ? args.saved_tags : []);
    const storedChart = loadStoredChartTags(args.context_key, browserSessionToken, restoreSavedDashboard);
    const incoming = mergeManualAndChartTags(incomingServer, storedChart);

    setTags((old) => {
      const current = dedupeTags(old);
      const merged = mergeManualAndChartTags(
        incomingServer,
        restoreSavedDashboard
          ? [...storedChart, ...current.filter(isChartTag)]
          : [...storedChart, ...current.filter(isChartTag)],
      );

      if (stableJson(current) === stableJson(merged)) return old;
      suppressStateUpdateRef.current = true;
      return merged;
    });
    setSelectedTagId((oldId) => {
      if (!oldId) return null;
      return incoming.some((tag) => tagKey(tag) === oldId || String(tag.created_at || "") === oldId) ? oldId : null;
    });
  }, [JSON.stringify(args.saved_tags || []), args.context_key, browserSessionToken, restoreSavedDashboard]);

  const agents = useMemo(() => normalizeAgentIntervals(args.agent_intervals), [JSON.stringify(args.agent_intervals || [])]);
  const showAgentIntervals = args.show_agent_intervals !== false;

  const selectedDataAgentName = useMemo(() => {
    const direct = String(args.selected_agent_name || args.selected_agent || "").trim();
    if (direct) return direct;

    const firstAgent = agents.find((item) => String(item?.label || "").trim());
    if (firstAgent) return String(firstAgent.label).trim();

    return "data agent";
  }, [args.selected_agent_name, args.selected_agent, agents]);

  const hitResultsTitle = `${selectedDataAgentName} tags and hit results`;
  
  
  const trackFooters = useMemo(() => {
    const rows = [[], [], [], []];
    (args.track_data?.tracks || []).forEach((track) => {
      const trackNo = Math.max(1, Math.min(4, Number(track.track || 1)));
      rows[trackNo - 1] = (track.curves || []).map(curveLimitsText).filter(Boolean);
    });
    if (!rows[3].length) rows[3] = ["Tagger | Overlap | Agent"];
    return rows;
  }, [JSON.stringify(args.track_data?.tracks || [])]);

  const viewportEndMs = useMemo(() => {
    if (viewportStartMs == null) return null;
    const span = clamp(Number(viewportSpanMs || visibleMs), MIN_VIEWPORT_SPAN_MS, visibleMs);
    return Math.min(viewportStartMs + span, sectionEndMs || viewportStartMs + span);
  }, [viewportStartMs, viewportSpanMs, visibleMs, sectionEndMs]);


  function getActiveSpanMs() {
    const rawSpan = Number(viewportSpanRef.current ?? visibleMs);
    return clamp(Number.isFinite(rawSpan) ? rawSpan : visibleMs, MIN_VIEWPORT_SPAN_MS, visibleMs);
  }

  function syncViewportFromYRange(range0, range1) {
    const a = toMs(range0);
    const b = toMs(range1);
    if (a == null || b == null) return false;

    const rawStart = Math.min(a, b);
    const rawEnd = Math.max(a, b);
    let span = rawEnd - rawStart;
    if (!Number.isFinite(span) || span <= 0) return false;

    span = clamp(span, MIN_VIEWPORT_SPAN_MS, visibleMs);
    const start = clampViewport(rawStart, span);

    viewportSpanRef.current = span;
    viewportStartRef.current = start;
    suppressNextBufferRequestRef.current = true;
    setViewportSpanMs((old) => (Math.abs(old - span) < 500 ? old : span));
    setViewportStartMs((old) => (Math.abs((old ?? 0) - start) < 500 ? old : start));

    const wasCapped = Math.abs(span - (rawEnd - rawStart)) > 500 || Math.abs(start - rawStart) > 500;
    if (wasCapped) {
      setTimeout(() => setPlotViewport(start), 0);
    }

    return true;
  }

  function extractPrimaryYRangeFromRelayout(eventData) {
    if (!eventData || typeof eventData !== "object") return null;
    if (Array.isArray(eventData["yaxis.range"])) return eventData["yaxis.range"];
    if (eventData["yaxis.range[0]"] != null && eventData["yaxis.range[1]"] != null) {
      return [eventData["yaxis.range[0]"], eventData["yaxis.range[1]"]];
    }
    return null;
  }

  const setPlotViewport = useCallback(
    (startMs) => {
      const gd = plotRef.current;

      // Plotly.newPlot() is asynchronous. Do not call relayout until
      // gd._fullLayout exists, otherwise Plotly can crash internally.
      if (
        !gd ||
        startMs == null ||
        !plotInitializedRef.current ||
        !gd._fullLayout ||
        !gd._fullLayout.yaxis
      ) {
        return;
      }

      const span = getActiveSpanMs();
      const clampedStart = clampViewport(startMs, span);
      const endMs = Math.min(clampedStart + span, sectionEndMs || clampedStart + span);
      const yRange = [fmtTime(endMs), fmtTime(clampedStart)];
      const update = {
        "yaxis.range": yRange,
        "yaxis2.range": yRange,
        "yaxis3.range": yRange,
        "yaxis4.range": yRange,
      };

      try {
        programmaticRelayoutRef.current = true;
        Promise.resolve(Plotly.relayout(gd, update))
          .catch((err) => console.error("Virtual log viewer viewport relayout error:", err))
          .finally(() => {
            setTimeout(() => {
              lastRangesRef.current = getCurrentRanges();
              programmaticRelayoutRef.current = false;
            }, 50);
          });
      } catch (err) {
        programmaticRelayoutRef.current = false;
        console.error("Virtual log viewer viewport relayout synchronous error:", err);
      }
    },
    [visibleMs, sectionEndMs, clampViewport],
  );

  const maybeRequestBuffer = useCallback(
    (startMs) => {
      // Only explicit left-side arrow scrolling is allowed to request new backend data.
      // Tagging and zooming modes stay active while the arrow rail moves through time.
      if (requestLockRef.current || startMs == null) return;
      if (bufferStartMs == null || bufferEndMs == null) return;

      const activeVisibleMs = getActiveSpanMs();
      const endMs = startMs + activeVisibleMs;
      const sectionStart = sectionStartMs ?? startMs;
      const sectionEnd = sectionEndMs ?? endMs;

      const edgeMs = Math.max(30 * 60 * 1000, marginHours * HOUR_MS * 0.35);
      const nearTop = startMs - bufferStartMs < edgeMs && startMs > sectionStart;
      const nearBottom = bufferEndMs - endMs < edgeMs && endMs < sectionEnd;
      if (!nearTop && !nearBottom) return;

      // Do not keep requesting while the current buffer already covers the viewport
      // with a useful margin. This prevents the apparent "loading loop" near buffer edges.
      const usefulMarginMs = Math.max(20 * 60 * 1000, marginHours * HOUR_MS * 0.20);
      const hasUsefulTopMargin = startMs - bufferStartMs > usefulMarginMs || startMs <= sectionStart;
      const hasUsefulBottomMargin = bufferEndMs - endMs > usefulMarginMs || endMs >= sectionEnd;
      if (hasUsefulTopMargin && hasUsefulBottomMargin) return;

      const roundedStartMs = Math.round(startMs / 1000) * 1000;
      const roundedSpanSeconds = Math.max(30, Math.round(activeVisibleMs / 1000));
      const bufferKey = `${fmtTime(bufferStartMs)}|${fmtTime(bufferEndMs)}|${fmtTime(roundedStartMs)}|${roundedSpanSeconds}`;
      if (lastSentViewportRef.current === bufferKey) return;

      lastSentViewportRef.current = bufferKey;
      requestLockRef.current = true;

      Streamlit.setComponentValue({
        event: "viewport_request",
        source: "arrow_scroll",
        viewport_start: fmtTime(roundedStartMs),
        viewport_end: fmtTime(roundedStartMs + activeVisibleMs),
        viewport_span_seconds: roundedSpanSeconds,
      });

      setTimeout(() => {
        requestLockRef.current = false;
      }, 2500);
    },
    [bufferStartMs, bufferEndMs, visibleMs, marginHours, sectionStartMs, sectionEndMs],
  );

  const traces = useMemo(() => {
    const gridStart = viewportStartMs || bufferStartMs || sectionStartMs || Date.now();
    const gridEnd = viewportEndMs || Math.min(gridStart + visibleMs, sectionEndMs || gridStart + visibleMs);
    const base = buildGridKeepaliveTraces(gridStart, gridEnd);
    base.push(...buildCurveTraces(args.track_data));
    if (showAgentIntervals) {
      agents.forEach((a) => {
        base.push({
          type: "scatter",
          mode: "lines",
          x: Array(20).fill(0.76),
          y: Array.from({length: 20}, (_, i) => fmtTime(a.startMs + ((a.endMs - a.startMs) * i) / 19)),
          xaxis: "x4",
          yaxis: "y4",
          line: {color: "rgba(120,0,0,.98)", width: 9},
          showlegend: false,
          hoverinfo: "none",
          meta: {source: "agent", label: a.label},
          name: a.label,
        });
      });
    }

    tags.forEach((tag, idx) => {
      const s = toMs(tag.start);
      const e = toMs(tag.end);
      if (s == null || e == null || e <= s) return;
      const id = tagKey(tag);
      const selected = selectedTagId === id;
      base.push({
        type: "scatter",
        mode: "lines",
        x: Array(20).fill(0.24),
        y: Array.from({length: 20}, (_, i) => fmtTime(s + ((e - s) * i) / 19)),
        xaxis: "x4",
        yaxis: "y4",
        line: {color: selected ? "rgba(0,45,130,.98)" : "rgba(128,0,128,.95)", width: selected ? 11 : 7},
        showlegend: false,
        hoverinfo: "none",
        meta: {source: "tag", label: tag.label || "Dragged tag", id},
        name: tag.label || "Dragged tag",
      });
      bestOverlapsForTag(tag).forEach((ov) => {
        base.push({
          type: "scatter",
          mode: "lines",
          x: Array(20).fill(0.50),
          y: Array.from({length: 20}, (_, i) => fmtTime(ov.startMs + ((ov.endMs - ov.startMs) * i) / 19)),
          xaxis: "x4",
          yaxis: "y4",
          line: {color: "rgba(50,150,80,.95)", width: 8},
          showlegend: false,
          hoverinfo: "none",
          meta: {source: "overlap"},
          name: "Overlap",
        });
      });
    });
    return base;
  }, [
    args.track_data,
    agents,
    tags,
    selectedTagId,
    showAgentIntervals,
    viewportStartMs,
    viewportEndMs,
    bufferStartMs,
    sectionStartMs,
    sectionEndMs,
    visibleMs,
  ]);

  function bestOverlapsForTag(tag) {
    const s = toMs(tag.start);
    const e = toMs(tag.end);
    if (s == null || e == null || e <= s) return [];
    const out = [];
    agents.forEach((a) => {
      const os = Math.max(s, a.startMs);
      const oe = Math.min(e, a.endMs);
      if (oe > os) {
        const matchMs = Math.max(e - s, a.endMs - a.startMs, 1);
        out.push({
          startMs: os,
          endMs: oe,
          percent: ((oe - os) / matchMs) * 100,
          agent: a,
        });
      }
    });
    out.sort((a, b) => b.percent - a.percent);
    return out;
  }

  function buildHitRows(currentTags = tags) {
    const effectiveTags = dedupeTags(currentTags || []);
    const defaultSymptom = agents[0]?.label || "Agent hit";
    return effectiveTags.map((tag) => {
      const overlaps = bestOverlapsForTag(tag);
      const best = overlaps[0] || null;
      const percent = best ? best.percent : 0;
      return {
        symptom: best ? best.agent.label : defaultSymptom,
        data_agent: best ? best.agent.label : defaultSymptom,
        well: String(args.selected_well || String(args.context_key || "").split("__")[0] || ""),
        section: (args.selected_sections || []).join(" + "),
        date: tag.start ? String(tag.start).split(" ")[0] : "",
        tag_label: tag.label || "Dragged tag",
        tag_start: tag.start || "",
        tag_end: tag.end || "",
        agent_start: best ? best.agent.start : "",
        agent_end: best ? best.agent.end : "",
        result: best ? "Hit" : "Miss",
        percent_value: percent,
        percent: `${percent.toFixed(1)}% hit`,
      };
    });
  }

  useEffect(() => {
    const cleanTags = dedupeTags(tags);
    const cleanTagsJson = stableJson(cleanTags);

    if (cleanTagsJson !== stableJson(tags)) {
      suppressStateUpdateRef.current = true;
      setTags(cleanTags);
      return;
    }

    // Hit rows must be the current projection of the current tags only.
    // Merging old rows here keeps previous resize positions forever, which made
    // stretched/compressed tags look as if the dashboard had refused the edit.
    const rows = normalizeRowsForServer(buildHitRows(cleanTags));
    setHitRows((old) => (stableJson(normalizeRowsForServer(old)) === stableJson(rows) ? old : rows));
    // Let the sidebar Save Dashboard Session button capture exactly the rows
    // currently shown in the React Hit results table, including both manual
    // sidebar tags and browser-drawn tags.
    saveStoredHitRows(args.context_key, browserSessionToken, rows);

    // Critical change: drawing/editing a tag no longer calls Streamlit immediately.
    // Streamlit setComponentValue causes a rerun, which was remounting the plot and
    // starting the refresh loop. Keep chart tags local and persist them in browser
    // storage; sync them to Python only when the user presses "Save drawn tags".
    saveStoredChartTags(args.context_key, browserSessionToken, cleanTags.filter(isChartTag));
    saveStoredAllTags(args.context_key, browserSessionToken, cleanTags);
    suppressStateUpdateRef.current = false;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(tags), args.context_key, browserSessionToken]);



  function sendCurrentStateToStreamlit(reason = "manual_save") {
    const cleanTags = dedupeTags(tags);
    const outgoingChartTags = chartTagsForServer(cleanTags);
    const rows = normalizeRowsForServer(buildHitRows(cleanTags));
    const payload = {
      event: "state_update",
      reason,
      tag_mode: tagModeRef.current,
      tags: outgoingChartTags,
      hit_results: rows,
    };
    const payloadJson = stableJson(payload);
    if (lastStatePayloadRef.current === payloadJson) return;
    lastStatePayloadRef.current = payloadJson;
    pendingLocalChartTagsJsonRef.current = stableJson(outgoingChartTags);
    Streamlit.setComponentValue(payload);
  }

  function axisNames() {
    const gd = plotRef.current;
    const full = gd?._fullLayout || gd?.layout || {};
    return Object.keys(full).filter((key) => /^xaxis\d*$/.test(key) || /^yaxis\d*$/.test(key));
  }

  function getCurrentRanges() {
    const gd = plotRef.current;
    const full = gd?._fullLayout || gd?.layout || {};
    const ranges = {};
    axisNames().forEach((axisName) => {
      const axis = full[axisName];
      if (!axis) return;
      ranges[axisName] = {
        range: Array.isArray(axis.range) ? [axis.range[0], axis.range[1]] : null,
        autorange: axis.autorange === true,
      };
    });
    return ranges;
  }

  function makeRelayoutUpdate(ranges) {
    const update = {};
    Object.entries(ranges || {}).forEach(([axisName, axisState]) => {
      if (axisState?.range && axisState.range.length === 2) {
        update[`${axisName}.range[0]`] = axisState.range[0];
        update[`${axisName}.range[1]`] = axisState.range[1];
        update[`${axisName}.autorange`] = false;
      } else {
        update[`${axisName}.autorange`] = true;
      }
    });
    return update;
  }

  function updateZoomHistoryCount() {
    setZoomHistoryCount(zoomHistoryRef.current.length);
  }

  function captureInitialRangesOnce() {
    if (initialRangesRef.current) return;
    const ranges = getCurrentRanges();
    if (!ranges || Object.keys(ranges).length === 0) return;
    initialRangesRef.current = JSON.parse(JSON.stringify(ranges));
    lastRangesRef.current = JSON.parse(JSON.stringify(ranges));
    updateZoomHistoryCount();
  }

  function isRealAxisRangeChange(eventData) {
    return Object.keys(eventData || {}).some((key) =>
      key.includes(".range") || key.includes(".autorange") || key.includes("range[0]") || key.includes("range[1]"),
    );
  }

  function savePreviousZoomRange() {
    if (!lastRangesRef.current) return;
    zoomHistoryRef.current.push(JSON.parse(JSON.stringify(lastRangesRef.current)));
    if (zoomHistoryRef.current.length > 10) zoomHistoryRef.current.shift();
    updateZoomHistoryCount();
  }

  function updateCaptureLayer() {
    const gd = plotRef.current;
    const layer = captureRef.current;
    if (!gd?._fullLayout?._size || !layer) return;

    const size = gd._fullLayout._size;
    layer.style.left = `${size.l}px`;
    layer.style.top = `${size.t}px`;
    layer.style.width = `${size.w}px`;
    layer.style.height = `${size.h}px`;
  }

  function applyTagMode(active) {
    const gd = plotRef.current;
    tagModeRef.current = Boolean(active);
    updateCaptureLayer();

    if (!gd?._fullLayout) return;

    const update = {dragmode: active ? false : "zoom"};
    axisNames().forEach((axisName) => {
      // While tagging, freeze all Plotly draggers. The transparent capture layer
      // receives mouse events and converts the vertical drag into a Track 4 tag.
      if (active) {
        update[`${axisName}.fixedrange`] = true;
      } else {
        if (axisName.startsWith("xaxis")) update[`${axisName}.fixedrange`] = zoomModeRef.current === "y";
        if (axisName.startsWith("yaxis")) update[`${axisName}.fixedrange`] = zoomModeRef.current === "x";
      }
    });

    programmaticRelayoutRef.current = true;
    Promise.resolve(Plotly.relayout(gd, update))
      .catch((err) => console.error("Virtual log viewer tag-mode relayout error:", err))
      .finally(() => {
        setTimeout(() => {
          programmaticRelayoutRef.current = false;
          updateCaptureLayer();
        }, 80);
      });
  }

  function applyZoomMode(mode) {
    const gd = plotRef.current;
    if (!gd?._fullLayout) return;
    zoomModeRef.current = mode;

    if (tagModeRef.current) {
      applyTagMode(true);
      return;
    }

    const update = {dragmode: "zoom"};
    axisNames().forEach((axisName) => {
      if (axisName.startsWith("xaxis")) update[`${axisName}.fixedrange`] = mode === "y";
      if (axisName.startsWith("yaxis")) update[`${axisName}.fixedrange`] = mode === "x";
    });

    programmaticRelayoutRef.current = true;
    Promise.resolve(Plotly.relayout(gd, update))
      .catch((err) => console.error("Virtual log viewer zoom-mode relayout error:", err))
      .finally(() => {
        setTimeout(() => {
          programmaticRelayoutRef.current = false;
          updateCaptureLayer();
        }, 50);
      });
  }

  function chooseZoomMode(mode) {
    setTagMode(false);
    tagModeRef.current = false;
    setSelectedTagId(null);
    setZoomModeState(mode);
    applyZoomMode(mode);
  }

  function toggleTaggingMode() {
    setSelectedTagId(null);
    setTagMode((current) => {
      const next = !current;
      tagModeRef.current = next;
      return next;
    });
  }

  useEffect(() => {
    applyTagMode(tagMode);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tagMode]);

  useEffect(() => {
    function onKeyDown(event) {
      if (isEditableKeyboardTarget(event.target)) return;
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      if (event.repeat) return;

      const key = String(event.key || "").toLowerCase();
      if (key === "t") {
        event.preventDefault();
        event.stopPropagation?.();
        toggleTaggingMode();
        return;
      }

      if (key === "z") {
        event.preventDefault();
        event.stopPropagation?.();
        chooseZoomMode(zoomModeRef.current || "y");
        return;
      }

      if (key === "r") {
        event.preventDefault();
        event.stopPropagation?.();
        resetChartZoom();
      }
    }

    const targets = [];
    function addKeyTarget(target) {
      if (!target || targets.includes(target)) return;
      try {
        target.addEventListener("keydown", onKeyDown, true);
        targets.push(target);
      } catch (err) {
        // Cross-frame access can fail in some deployments. The iframe handler below still works.
      }
    }

    addKeyTarget(window);
    try { addKeyTarget(window.document); } catch (err) {}
    try { addKeyTarget(window.parent); } catch (err) {}
    try { addKeyTarget(window.parent?.document); } catch (err) {}
    try { addKeyTarget(window.top); } catch (err) {}
    try { addKeyTarget(window.top?.document); } catch (err) {}

    return () => {
      targets.forEach((target) => {
        try { target.removeEventListener("keydown", onKeyDown, true); } catch (err) {}
      });
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function undoLastZoom() {
    const gd = plotRef.current;
    if (!gd?._fullLayout || zoomHistoryRef.current.length === 0) {
      updateZoomHistoryCount();
      return;
    }

    const previous = zoomHistoryRef.current.pop();
    updateZoomHistoryCount();
    programmaticRelayoutRef.current = true;

    Promise.resolve(Plotly.relayout(gd, makeRelayoutUpdate(previous)))
      .then(() => Plotly.redraw(gd))
      .catch((err) => console.error("Virtual log viewer undo zoom error:", err))
      .finally(() => {
        setTimeout(() => {
          lastRangesRef.current = getCurrentRanges();
          const restoredY = lastRangesRef.current?.yaxis?.range;
          if (restoredY && restoredY.length === 2) {
            syncViewportFromYRange(restoredY[0], restoredY[1]);
          }
          programmaticRelayoutRef.current = false;
          updateZoomHistoryCount();
        }, 100);
      });
  }

  function resetChartZoom() {
    const gd = plotRef.current;
    if (!gd?._fullLayout) return;
    captureInitialRangesOnce();
    if (!initialRangesRef.current) return;

    zoomHistoryRef.current = [];
    viewportSpanRef.current = visibleMs;
    setViewportSpanMs(visibleMs);
    updateZoomHistoryCount();
    programmaticRelayoutRef.current = true;

    Promise.resolve(Plotly.relayout(gd, makeRelayoutUpdate(initialRangesRef.current)))
      .then(() => Plotly.redraw(gd))
      .catch((err) => console.error("Virtual log viewer reset zoom error:", err))
      .finally(() => {
        setTimeout(() => {
          lastRangesRef.current = JSON.parse(JSON.stringify(initialRangesRef.current));
          viewportStartRef.current = initialPlotRangeRef.current;
          setViewportStartMs(initialPlotRangeRef.current);
          programmaticRelayoutRef.current = false;
          updateZoomHistoryCount();
        }, 100);
      });
  }

  const layout = useMemo(() => {
    const rangeStart = initialPlotRangeRef.current || bufferStartMs || sectionStartMs;
    const rangeEnd = Math.min((rangeStart || 0) + visibleMs, sectionEndMs || (rangeStart || 0) + visibleMs);
    return {
      height,
      margin: {l: 86, r: 28, t: 45, b: 40},
      paper_bgcolor: "white",
      plot_bgcolor: "white",
      dragmode: "zoom",
      showlegend: false,
      hovermode: "closest",
      ...buildDomains(),
      yaxis: makeTimeAxis(rangeStart, rangeEnd, true, height),
      yaxis2: {...makeTimeAxis(rangeStart, rangeEnd, false, height), matches: "y"},
      yaxis3: {...makeTimeAxis(rangeStart, rangeEnd, false, height), matches: "y"},
      yaxis4: {...makeTimeAxis(rangeStart, rangeEnd, false, height), matches: "y"},
      annotations: [
        {xref: "paper", yref: "paper", x: 0.885, y: 1.04, text: "<b>Tagger</b>", showarrow: false, font: {color: "purple", size: 12}},
        {xref: "paper", yref: "paper", x: 0.915, y: 1.04, text: "<b>Overlap</b>", showarrow: false, font: {color: "green", size: 12}},
        {xref: "paper", yref: "paper", x: 0.955, y: 1.04, text: "<b>Agent</b>", showarrow: false, font: {color: "darkred", size: 12}},
      ],
    };
  }, [bufferStartMs, sectionStartMs, sectionEndMs, visibleMs, height]);

  useEffect(() => {
    const gd = plotRef.current;
    if (!gd) return;

    let cancelled = false;

    const config = {
      displaylogo: false,
      displayModeBar: true,
      scrollZoom: false,
      doubleClick: false,
      modeBarButtonsToRemove: ["lasso2d", "select2d", "zoom2d", "zoomIn2d", "zoomOut2d"],
    };

    const safeLayout = {
      ...layout,
      template: {data: {}, layout: {}},
      annotations: Array.isArray(layout.annotations) ? layout.annotations : [],
    };

    const safeTraces = (Array.isArray(traces) ? traces : [])
      .filter(Boolean)
      .map((trace) => ({
        ...trace,
        type: trace.type === "scattergl" ? "scatter" : trace.type,
        x: Array.isArray(trace.x) ? trace.x : [],
        y: Array.isArray(trace.y) ? trace.y : [],
      }));

    let drawPromise;
    try {
      drawPromise =
        plotInitializedRef.current && gd._fullLayout
          ? Plotly.react(gd, safeTraces, safeLayout, config)
          : Plotly.newPlot(gd, safeTraces, safeLayout, config);
      plotInitializedRef.current = true;
    } catch (err) {
      drawPromise = Promise.reject(err);
    }

    Promise.resolve(drawPromise)
      .then(() => {
        if (cancelled) return;

        Streamlit.setFrameHeight(height + 270);
        updateCaptureLayer();

        try {
          gd.removeAllListeners?.("plotly_hover");
          gd.removeAllListeners?.("plotly_unhover");
          gd.removeAllListeners?.("plotly_relayout");
          gd.removeAllListeners?.("plotly_doubleclick");
        } catch (err) {
          // Not all Plotly builds expose removeAllListeners. Safe to ignore.
        }

        captureInitialRangesOnce();
        if (tagModeRef.current) {
          applyTagMode(true);
        } else {
          applyZoomMode(zoomModeRef.current);
        }
        // Always restore the current virtual viewport after Plotly.react().
        // Tag edits and zoom-mode changes can redraw traces; without this restore,
        // Plotly falls back to the initial 12-hour layout and appears to reload/loop.
        setPlotViewport(viewportStartRef.current);
        updateCaptureLayer();

        gd.on?.("plotly_hover", (ev) => {
          const p = ev?.points?.[0];
          if (!p) return;

          const full = gd._fullLayout;
          if (full?.yaxis?._offset != null && full?.yaxis?.d2p) {
            const y = full.yaxis._offset + full.yaxis.d2p(p.y);
            if (hoverLineRef.current) {
              hoverLineRef.current.style.top = `${y}px`;
              hoverLineRef.current.style.display = "block";
            }
          }

          const box = hoverBoxRef.current;
          const wrap = wrapRef.current;

          if (box && wrap && ev.event) {
            const rect = wrap.getBoundingClientRect();
            const meta = p.data?.meta || {};
            const raw = p.customdata?.[0] ?? p.x;
            const rawNumber = Number(raw);
            const rawText = Number.isFinite(rawNumber) ? rawNumber.toFixed(1) : String(raw ?? "");
            // Use the real plotted timestamp carried in point.y. X values are
            // normalized for track display, but Y is the true time axis. Do not
            // derive the hover time from normalized X or truncate it to HH:MM:SS.
            const time = String(p.y || "");

            box.innerHTML =
              `<b>${htmlEscape(meta.label || p.data?.name || "Value")}</b><br>` +
              `${htmlEscape(rawText)} ${htmlEscape(meta.unit || "")}<br>` +
              `Time: ${htmlEscape(time)}`;

            box.style.left = `${Math.max(8, Math.min(ev.event.clientX - rect.left + 12, rect.width - 210))}px`;
            box.style.top = `${Math.max(8, ev.event.clientY - rect.top - 78)}px`;
            box.style.display = "block";
          }
        });

        gd.on?.("plotly_unhover", () => {
          if (hoverLineRef.current) hoverLineRef.current.style.display = "none";
          if (hoverBoxRef.current) hoverBoxRef.current.style.display = "none";
        });

        gd.on?.("plotly_relayout", (eventData) => {
          if (programmaticRelayoutRef.current) return;
          if (!isRealAxisRangeChange(eventData)) return;

          savePreviousZoomRange();

          const yRange = extractPrimaryYRangeFromRelayout(eventData);
          if (yRange) {
            syncViewportFromYRange(yRange[0], yRange[1]);
          }

          setTimeout(() => {
            lastRangesRef.current = getCurrentRanges();
            updateZoomHistoryCount();
          }, 100);
        });

        gd.on?.("plotly_doubleclick", () => {
          if (doubleClickLockRef.current) return false;
          doubleClickLockRef.current = true;
          undoLastZoom();
          setTimeout(() => {
            doubleClickLockRef.current = false;
          }, 350);
          return false;
        });
      })
      .catch((err) => {
        console.error("Virtual log viewer Plotly render error:", err);

        if (!cancelled) {
          gd.innerHTML = `
            <div style="padding:12px;border:1px solid #d33;background:#fff5f5;color:#7f1d1d;font-family:Arial,sans-serif;font-size:13px;">
              <b>Virtual log viewer Plotly render error</b><br/>
              ${htmlEscape(err?.message || String(err))}
            </div>
          `;
          Streamlit.setFrameHeight(260);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [traces, layout, height, setPlotViewport]);

  useEffect(() => {
    viewportStartRef.current = viewportStartMs;
    setPlotViewport(viewportStartMs);

    if (suppressNextBufferRequestRef.current) {
      suppressNextBufferRequestRef.current = false;
      return;
    }

    maybeRequestBuffer(viewportStartMs);
  }, [viewportStartMs, viewportSpanMs, setPlotViewport, maybeRequestBuffer]);

  function pixelToTime(clientY) {
    const gd = plotRef.current;
    if (!gd?._fullLayout?.yaxis) return null;
    const rect = gd.getBoundingClientRect();
    const size = gd._fullLayout._size;
    const plotY = clamp(clientY - rect.top - size.t, 0, size.h);
    let v = gd._fullLayout.yaxis.p2d(plotY);
    const ms = toMs(v);
    return ms == null ? null : ms;
  }

  function nearestTagId(clientY) {
    const ms = pixelToTime(clientY);
    if (ms == null) return null;
    let best = null;
    let bestDist = Infinity;
    tags.forEach((tag, idx) => {
      if (!isEditableTrackTag(tag)) return;
      const s = toMs(tag.start);
      const e = toMs(tag.end);
      if (s == null || e == null) return;
      const top = Math.min(s, e);
      const bottom = Math.max(s, e);
      const center = (top + bottom) / 2;
      const dist = ms >= top && ms <= bottom ? 0 : Math.abs(center - ms);
      if (dist < bestDist) {
        bestDist = dist;
        best = tagKey(tag);
      }
    });
    return bestDist <= 20 * 60 * 1000 ? best : null;
  }

  function isClientYInsideTagId(clientY, tagId, tolerancePx = 14) {
    const gd = plotRef.current;
    if (!gd?._fullLayout?.yaxis || !gd?._fullLayout?._size || !tagId) return false;

    const tag = tags.find((item) => tagKey(item) === tagId);
    if (!tag || !isEditableTrackTag(tag)) return false;

    try {
      const rect = gd.getBoundingClientRect();
      const plotY = clientY - rect.top - gd._fullLayout._size.t;
      const startPixel = gd._fullLayout.yaxis.d2p(tag.start);
      const endPixel = gd._fullLayout.yaxis.d2p(tag.end);
      if (!Number.isFinite(startPixel) || !Number.isFinite(endPixel)) return false;
      const top = Math.min(startPixel, endPixel) - tolerancePx;
      const bottom = Math.max(startPixel, endPixel) + tolerancePx;
      return plotY >= top && plotY <= bottom;
    } catch (err) {
      return false;
    }
  }

  function updateSelectBox(startY, curY) {
    const gd = plotRef.current;
    const box = selectBoxRef.current;
    if (!gd?._fullLayout?._size || !box) return;
    const rect = gd.getBoundingClientRect();
    const wrapRect = wrapRef.current.getBoundingClientRect();
    const y1 = startY - wrapRect.top;
    const y2 = curY - wrapRect.top;
    box.style.display = "block";
    box.style.left = `${gd._fullLayout._size.l}px`;
    box.style.width = `${gd._fullLayout._size.w}px`;
    box.style.top = `${Math.min(y1, y2)}px`;
    box.style.height = `${Math.max(4, Math.abs(y2 - y1))}px`;
  }

  function hideSelectBox() {
    if (selectBoxRef.current) selectBoxRef.current.style.display = "none";
  }

function trackAxisName(trackNo) {
  return trackNo === 1 ? "xaxis" : `xaxis${trackNo}`;
}

function getMouseTrackNo(e) {
  const gd = plotRef.current;
  const full = gd?._fullLayout;
  if (!gd || !full?._size) return null;

  const gdRect = gd.getBoundingClientRect();
  const size = full._size;
  const plotX = clamp(e.clientX - gdRect.left - size.l, 0, size.w);
  const fracX = size.w > 0 ? plotX / size.w : 0;

  for (let trackNo = 1; trackNo <= 3; trackNo += 1) {
    const axis = full[trackAxisName(trackNo)];
    const domain = axis?.domain || [];
    if (domain.length === 2 && fracX >= domain[0] && fracX <= domain[1]) {
      return trackNo;
    }
  }

  return null;
}

function getTaggingHoverCurvePoint(e, timeMs) {
  if (timeMs == null) return null;

  const gd = plotRef.current;
  const full = gd?._fullLayout;
  if (!gd || !full?._size) return null;

  const trackNo = getMouseTrackNo(e);
  if (!trackNo) return null;

  const track = (args.track_data?.tracks || []).find(
    (item) => Number(item.track || 1) === trackNo,
  );
  if (!track || !Array.isArray(track.curves) || !track.curves.length) return null;

  const gdRect = gd.getBoundingClientRect();
  const size = full._size;
  const plotX = clamp(e.clientX - gdRect.left - size.l, 0, size.w);
  const fracX = size.w > 0 ? plotX / size.w : 0;

  const xAxis = full[trackAxisName(trackNo)];
  const domain = xAxis?.domain || [0, 1];
  const localX = domain[1] > domain[0]
    ? clamp((fracX - domain[0]) / (domain[1] - domain[0]), 0, 1)
    : 0.5;

  let best = null;

  track.curves.forEach((curve) => {
    const ys = Array.isArray(curve.y) ? curve.y : [];
    const rawValues = Array.isArray(curve.x) ? curve.x : [];
    const normalizedValues = normalize(rawValues);

    ys.forEach((timeText, idx) => {
      const pointMs = toMs(timeText);
      if (pointMs == null) return;

      const rawValue = Number(rawValues[idx]);
      if (!Number.isFinite(rawValue)) return;

      const normX = Number(normalizedValues[idx]);
      const xPenalty = Number.isFinite(normX) ? Math.abs(normX - localX) * 5 * 60 * 1000 : 0;
      const timePenalty = Math.abs(pointMs - timeMs);
      const score = timePenalty + xPenalty;

      if (!best || score < best.score) {
        best = {
          score,
          label: String(curve.label || curve.raw_col || "Value"),
          unit: String(curve.unit || ""),
          value: rawValue,
          timeText: fmtTime(pointMs),
        };
      }
    });
  });

  return best;
}

function showTaggingHover(e) {
  const gd = plotRef.current;
  const wrap = wrapRef.current;
  if (!gd?._fullLayout?.yaxis || !gd?._fullLayout?._size || !wrap) return;

  try {
    const gdRect = gd.getBoundingClientRect();
    const wrapRect = wrap.getBoundingClientRect();
    const size = gd._fullLayout._size;
    const plotY = clamp(e.clientY - gdRect.top - size.t, 0, size.h);
    const top = gdRect.top - wrapRect.top + size.t + plotY;
    const ms = pixelToTime(e.clientY);
    const timeText = ms == null ? "" : fmtTime(ms);
    const curvePoint = getTaggingHoverCurvePoint(e, ms);

    if (hoverLineRef.current) {
      hoverLineRef.current.style.left = "0px";
      hoverLineRef.current.style.width = "100%";
      hoverLineRef.current.style.top = `${top}px`;
      hoverLineRef.current.style.display = "block";
    }

    if (hoverBoxRef.current) {
      if (curvePoint) {
        hoverBoxRef.current.innerHTML =
          `<b>${htmlEscape(curvePoint.label)}</b><br>` +
          `${htmlEscape(formatLimitValue(curvePoint.value))} ${htmlEscape(curvePoint.unit)}<br>` +
          `Time: ${htmlEscape(curvePoint.timeText)}`;
      } else {
        hoverBoxRef.current.innerHTML =
          `<b>Tagging mode</b><br>` +
          (timeText ? `Time: ${htmlEscape(timeText)}<br>` : "") +
          `Drag vertically to create/edit a Track 4 tag`;
      }

      hoverBoxRef.current.style.left =
        `${Math.max(8, Math.min(e.clientX - wrapRect.left + 12, wrapRect.width - 245))}px`;

      hoverBoxRef.current.style.display = "block";

      // 2 cm above the mouse cursor. 2 cm is about 76 CSS pixels.
      const noteGapPx = 76;
      const boxHeight = hoverBoxRef.current.offsetHeight || 72;
      const desiredTop = e.clientY - wrapRect.top - noteGapPx - boxHeight;
      hoverBoxRef.current.style.top =
        `${Math.max(8, Math.min(desiredTop, wrapRect.height - boxHeight - 8))}px`;
    }
  } catch (err) {
    // Hover overlay failure should not break tagging.
  }
}

  function updateResizePreview(startMs, endMs) {
    const gd = plotRef.current;
    const box = selectBoxRef.current;
    const wrap = wrapRef.current;
    if (!gd?._fullLayout?.yaxis || !box || !wrap) return;
    try {
      const y1 = gd._fullLayout.yaxis.d2p(fmtTime(startMs)) + gd._fullLayout._size.t;
      const y2 = gd._fullLayout.yaxis.d2p(fmtTime(endMs)) + gd._fullLayout._size.t;
      const size = gd._fullLayout._size;
      box.style.display = "block";
      box.style.left = `${size.l}px`;
      box.style.width = `${size.w}px`;
      box.style.top = `${Math.min(y1, y2)}px`;
      box.style.height = `${Math.max(4, Math.abs(y2 - y1))}px`;
    } catch (err) {
      // Preview failure should never break editing.
    }
  }

  function isWheelInsidePlotArea(e) {
    const gd = plotRef.current;
    if (!gd?._fullLayout?._size) return false;
    const rect = gd.getBoundingClientRect();
    const size = gd._fullLayout._size;
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    return x >= size.l && x <= size.l + size.w && y >= size.t && y <= size.t + size.h;
  }

  function scrollParentPageBy(deltaY, deltaX = 0) {
    const dy = Number(deltaY) || 0;
    const dx = Number(deltaX) || 0;
    if (!dy && !dx) return false;

    try {
      const parentWindow = window.parent || window.top;
      const parentDoc = parentWindow?.document;

      if (parentDoc) {
        const frameAncestors = [];
        try {
          let node = window.frameElement;
          while (node) {
            frameAncestors.push(node);
            node = node.parentElement;
          }
        } catch (err) {}

        const directCandidates = [
          ...frameAncestors,
          parentDoc.querySelector('[data-testid="stAppViewContainer"]'),
          parentDoc.querySelector('[data-testid="stMain"]'),
          parentDoc.querySelector('.stApp'),
          parentDoc.scrollingElement,
          parentDoc.documentElement,
          parentDoc.body,
        ].filter(Boolean);

        const allCandidates = [
          ...directCandidates,
          ...Array.from(parentDoc.querySelectorAll('main, section, div')).slice(0, 250),
        ];

        const scrollTarget = allCandidates.find((el) => {
          try {
            const style = parentWindow.getComputedStyle ? parentWindow.getComputedStyle(el) : null;
            const canScrollY = el.scrollHeight > el.clientHeight + 2;
            const overflowY = String(style?.overflowY || '').toLowerCase();
            return canScrollY && overflowY !== 'hidden';
          } catch (err) {
            return false;
          }
        });

        if (scrollTarget && typeof scrollTarget.scrollBy === 'function') {
          scrollTarget.scrollBy({top: dy, left: dx, behavior: 'auto'});
          return true;
        }
      }

      if (parentWindow && typeof parentWindow.scrollBy === 'function') {
        parentWindow.scrollBy({top: dy, left: dx, behavior: 'auto'});
        return true;
      }
    } catch (err) {
      // Cross-frame access can fail in some deployments. In that case, leave the
      // event untouched so the browser can use its default scroll behavior.
      return false;
    }

    return false;
  }

  function isEditableKeyboardTarget(target) {
    if (!target) return false;
    const tagName = String(target.tagName || '').toLowerCase();
    return (
      tagName === 'input' ||
      tagName === 'textarea' ||
      tagName === 'select' ||
      Boolean(target.isContentEditable)
    );
  }

  function flushWheelScroll() {
    wheelRafRef.current = null;

    const deltaY = wheelDeltaRef.current;
    wheelDeltaRef.current = 0;
    if (!deltaY) return;

    const base = viewportStartRef.current ?? viewportStartMs ?? sectionStartMs;
    if (base == null) return;

    // Map wheel pixels to time. This makes the chart feel like a continuous
    // vertical drilling-log scroll while keeping the loaded buffer small.
    const activeVisibleMs = getActiveSpanMs();
    const msPerWheelPixel = (activeVisibleMs / Math.max(height, 1)) * 0.9;
    const next = clampViewport(base + deltaY * msPerWheelPixel, activeVisibleMs);
    if (next === base) return;

    viewportStartRef.current = next;
    setViewportStartMs(next);
  }

  function onWheel(e) {
    // Mouse wheel/trackpad scroll should scroll the main Streamlit page, even
    // while the pointer is inside the plot iframe. It must never change the
    // virtual time viewport or ask Python to load a new raw buffer.
    if (e.ctrlKey || e.metaKey) return;

    const forwarded = scrollParentPageBy(e.deltaY, e.deltaX);
    if (forwarded) {
      e.preventDefault();
      e.stopPropagation();
    }
  }

  function stepArrowScroll(direction, dtMs = 120) {
    const base = viewportStartRef.current ?? viewportStartMs ?? sectionStartMs;
    if (base == null || !direction) return;

    const activeVisibleMs = getActiveSpanMs();
    const speedMsPerSecond = activeVisibleMs / 7.5;
    const stepMs = direction * speedMsPerSecond * (Math.max(16, Math.min(dtMs, 250)) / 1000);
    const next = clampViewport(base + stepMs, activeVisibleMs);
    if (Math.abs(next - base) < 1) return;

    suppressNextBufferRequestRef.current = false;
    viewportStartRef.current = next;
    setViewportStartMs(next);
    setPlotViewport(next);
    maybeRequestBuffer(next);
  }

  function arrowScrollFrame(ts) {
    const state = arrowScrollRef.current;
    if (!state.active) return;
    const last = state.lastTs || ts;
    state.lastTs = ts;
    stepArrowScroll(state.direction, ts - last);
    state.rafId = requestAnimationFrame(arrowScrollFrame);
  }

  function startArrowScroll(direction, event) {
    event?.preventDefault?.();
    event?.stopPropagation?.();
    if (!direction) return;
    try { rootRef.current?.focus?.({preventScroll: true}); } catch (err) {}
    suppressNextBufferRequestRef.current = false;
    if (arrowScrollRef.current.rafId != null) cancelAnimationFrame(arrowScrollRef.current.rafId);
    arrowScrollRef.current = {active: true, direction, rafId: null, lastTs: 0};
    stepArrowScroll(direction, 180);
    arrowScrollRef.current.rafId = requestAnimationFrame(arrowScrollFrame);
  }

  function jumpArrowScroll(direction, event) {
    event?.preventDefault?.();
    event?.stopPropagation?.();
    if (!direction) return;

    const state = arrowScrollRef.current;
    if (state.rafId != null) cancelAnimationFrame(state.rafId);
    arrowScrollRef.current = {active: false, direction: 0, rafId: null, lastTs: 0};

    const base = viewportStartRef.current ?? viewportStartMs ?? sectionStartMs;
    if (base == null) return;

    const activeVisibleMs = getActiveSpanMs();
    const next = clampViewport(base + direction * 2 * HOUR_MS, activeVisibleMs);
    if (Math.abs(next - base) < 1) return;

    suppressNextBufferRequestRef.current = false;
    viewportStartRef.current = next;
    setViewportStartMs(next);
    setPlotViewport(next);
    maybeRequestBuffer(next);
  }

  function stopArrowScroll(event) {
    event?.preventDefault?.();
    event?.stopPropagation?.();
    const state = arrowScrollRef.current;
    if (state.rafId != null) cancelAnimationFrame(state.rafId);
    arrowScrollRef.current = {active: false, direction: 0, rafId: null, lastTs: 0};
  }

  function onMouseDown(e) {
    if (!tagModeRef.current) return;
    e.preventDefault();
    e.stopPropagation();
    showTaggingHover(e);

    if (selectedTagId) {
      if (!isClientYInsideTagId(e.clientY, selectedTagId, 18)) {
        setSelectedTagId(null);
        hideSelectBox();
        dragRef.current = {active: false, startY: null, currentY: null};
        resizeRef.current = {active: false, boundary: null, tagId: null, startMs: null, endMs: null, previewStartMs: null, previewEndMs: null};
        return;
      }

      const selectedTag = tags.find((tag) => tagKey(tag) === selectedTagId);
      const startMs = toMs(selectedTag?.start);
      const endMs = toMs(selectedTag?.end);
      if (startMs == null || endMs == null) return;

      resizeRef.current = {
        active: true,
        boundary: null,
        tagId: selectedTagId,
        startMs,
        endMs,
        previewStartMs: startMs,
        previewEndMs: endMs,
      };
      updateResizePreview(startMs, endMs);
      return;
    }

    dragRef.current = {active: true, startY: e.clientY, currentY: e.clientY};
    updateSelectBox(e.clientY, e.clientY);
  }

  function onMouseMove(e) {
    if (!tagModeRef.current) return;
    e.preventDefault();
    e.stopPropagation();
    showTaggingHover(e);

    if (resizeRef.current.active && selectedTagId) {
      const ms = pixelToTime(e.clientY);
      if (ms == null) return;

      const resize = resizeRef.current;
      let boundary = resize.boundary;
      if (!boundary) {
        boundary = Math.abs(ms - resize.startMs) < Math.abs(ms - resize.endMs) ? "start" : "end";
        resize.boundary = boundary;
      }

      let ns = boundary === "start" ? ms : resize.startMs;
      let ne = boundary === "end" ? ms : resize.endMs;
      if (ns > ne) [ns, ne] = [ne, ns];

      // Preview only. The real tag state is updated once on mouseup.
      // This prevents Plotly.react and Streamlit state updates on every mousemove.
      resize.previewStartMs = ns;
      resize.previewEndMs = ne;
      updateResizePreview(ns, ne);
      return;
    }

    if (dragRef.current.active) {
      dragRef.current.currentY = e.clientY;
      updateSelectBox(dragRef.current.startY, e.clientY);
    }
  }

  function commitActiveResize() {
    if (!resizeRef.current.active) return false;
    const resize = resizeRef.current;
    const ns = resize.previewStartMs ?? resize.startMs;
    const ne = resize.previewEndMs ?? resize.endMs;

    if (resize.tagId && ns != null && ne != null) {
      setTags((old) =>
        dedupeTags(
          old.map((tag) => {
            const id = tagKey(tag);
            if (id !== resize.tagId) return tag;
          const newStart = fmtTime(Math.min(ns, ne));
          const newEnd = fmtTime(Math.max(ns, ne));
          const oldSource = String(tag.source || "manual").trim() || "manual";
          const newLabel = tag.label || (isChartSource(oldSource) ? "Dragged tag" : "Manual tag");

          return {
            ...tag,
            label: newLabel,
            start: newStart,
            end: newEnd,
            source: isChartSource(oldSource) ? "chart_drag" : oldSource,
            created_at: isChartSource(oldSource)
              ? stableTagIdFromParts(newLabel, newStart, newEnd, 0)
              : (tag.created_at || ""),
          };  
          }),
        ),
      );
    }

    resizeRef.current = {active: false, boundary: null, tagId: null, startMs: null, endMs: null, previewStartMs: null, previewEndMs: null};
    hideSelectBox();
    return true;
  }

  function onMouseUp(e) {
    if (!tagModeRef.current && !resizeRef.current.active && !dragRef.current.active) return;
    e.preventDefault();
    e.stopPropagation();

    if (commitActiveResize()) return;

    if (!dragRef.current.active) return;
    const startY = dragRef.current.startY;
    const endY = e.clientY;
    dragRef.current = {active: false, startY: null, currentY: null};
    hideSelectBox();

    if (Math.abs(endY - startY) < 6) return;

    const t1 = pixelToTime(startY);
    const t2 = pixelToTime(endY);
    if (t1 == null || t2 == null) return;
    const s = Math.min(t1, t2);
    const en = Math.max(t1, t2);
    const label = `Dragged Tag ${chartTagsForServer(tags).length + 1}`;
    const startText = fmtTime(s);
    const endText = fmtTime(en);
    const item = {
      label,
      start: startText,
      end: endText,
      created_at: stableTagIdFromParts(label, startText, endText, 0),
      source: "chart_drag",
    };
    setRedoTags([]);
    setTags((old) => {
      const next = dedupeTags([...old, item]);
      const rows = normalizeRowsForServer(buildHitRows(next));
      saveStoredChartTags(args.context_key, browserSessionToken, chartTagsForServer(next));
      saveStoredHitRows(args.context_key, browserSessionToken, rows);
      return next;
    });
  }

  function onDoubleClick(e) {
    if (!tagModeRef.current) {
      e.preventDefault();
      e.stopPropagation();
      if (!doubleClickLockRef.current) {
        doubleClickLockRef.current = true;
        undoLastZoom();
        setTimeout(() => {
          doubleClickLockRef.current = false;
        }, 350);
      }
      return;
    }
    e.preventDefault();
    e.stopPropagation();

    const id = nearestTagId(e.clientY);
    if (!id) {
      setSelectedTagId(null);
      return;
    }

    if (selectedTagId === id) {
      setTags((old) => old.filter((tag) => tagKey(tag) !== id));
      setSelectedTagId(null);
    } else {
      setSelectedTagId(id);
    }
  }

  function undoLastClientTag() {
    const drawn = [...dedupeTags(tags)].filter(isChartTag);
    if (!drawn.length) return;
    const last = drawn[drawn.length - 1];
    const lastId = tagKey(last);
    setTags((old) => old.filter((tag) => tagKey(tag) !== lastId));
    setRedoTags((old) => [...old.slice(-9), last]);
    if (selectedTagId === lastId) setSelectedTagId(null);
  }

  function redoLastClientTag() {
    if (!redoTags.length) return;
    const restored = redoTags[redoTags.length - 1];
    setRedoTags((old) => old.slice(0, -1));
    setTags((old) => dedupeTags([...old, restored]));
  }

  function deleteSelected() {
    if (!selectedTagId) return;
    setTags((old) => old.filter((tag) => tagKey(tag) !== selectedTagId));
    setSelectedTagId(null);
  }

  function downloadHitResults() {
    const rows = buildHitRows(dedupeTags(tags));
    if (!rows.length) {
      alert("No dragged-tag hit results to download yet.");
      return;
    }
    let table = "<table><thead><tr>";
    ["Symptom", "Well", "Section", "Date", "Tag Start", "Tag End", "Agent Start", "Agent End", "Result", "Percent"].forEach((c) => {
      table += `<th>${htmlEscape(c)}</th>`;
    });
    table += "</tr></thead><tbody>";
    rows.forEach((r) => {
      table += "<tr>";
      [r.symptom, r.well, r.section, r.date, r.tag_start, r.tag_end, r.agent_start, r.agent_end, r.result, r.percent].forEach((v) => {
        table += `<td>${htmlEscape(v)}</td>`;
      });
      table += "</tr>";
    });
    table += "</tbody></table>";
    const html =
      `<html><head><meta charset="utf-8"></head><body>` +
      `<h3>${htmlEscape(hitResultsTitle)}</h3>` +
      table +
      `</body></html>`;

    const blob = new Blob([html], {type: "application/vnd.ms-excel;charset=utf-8"});
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${safeDownloadName(hitResultsTitle, "data agent tags and hit results")}.xls`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  const visibleRows = buildHitRows(dedupeTags(tags));
  const hitCount = visibleRows.filter((r) => r.result === "Hit").length;
  const missCount = visibleRows.filter((r) => r.result === "Miss").length;

  return (
    <div className="vlv-root" ref={rootRef} tabIndex={0}>
      <div className="vlv-toolbar">
        <button disabled={zoomHistoryCount === 0} onClick={undoLastZoom}>Undo chart zoom</button>
        <button onClick={resetChartZoom}>Reset chart zoom</button>

        <button
          className={tagMode ? "active" : ""}
          onClick={toggleTaggingMode}
        >
          🏷 Tagging
        </button>
        <button disabled={!tags.some((tag) => String(tag.source || "") === "chart_drag")} onClick={undoLastClientTag}>Undo drag tag</button>
        <button disabled={!selectedTagId} onClick={deleteSelected}>🗑 Delete selected tag</button>
        <button disabled={!redoTags.length} onClick={redoLastClientTag}>Redo drag tag</button>
        <button onClick={() => {
          clearStoredChartTags(args.context_key, browserSessionToken);
          setTags((old) => {
            const remaining = old.filter((tag) => !isChartTag(tag));
            const rows = buildHitRows(remaining);
            setHitRows(rows);
            saveStoredHitRows(args.context_key, browserSessionToken, rows);
            return remaining;
          });
          setSelectedTagId(null);
          setRedoTags([]);
        }}>Clear drag tags</button>
        <button onClick={() => sendCurrentStateToStreamlit("manual_save")}>Save drawn tags</button>
        <button onClick={downloadHitResults}>Download hit results Excel</button>

        <span className="vlv-spacer" />
        <span style={{fontSize: 12, color: "#555"}}>Zoom mode:</span>
        <button className={zoomMode === "x" && !tagMode ? "active-blue" : ""} onClick={() => chooseZoomMode("x")}>🔍 X</button>
        <button className={zoomMode === "y" && !tagMode ? "active-blue" : ""} onClick={() => chooseZoomMode("y")}>🔍 Y</button>
        <button className={zoomMode === "xy" && !tagMode ? "active-blue" : ""} onClick={() => chooseZoomMode("xy")}>🔍 XY</button>

        <span style={{fontSize: 12, color: "#555"}}>Chart zoom undo history: {zoomHistoryCount} / 10</span>
      </div>

      <div className="vlv-caption">
        {tagMode
          ? "Tagging is active. Press Z for zoom mode or R to reset zoom. Hold the left arrow rail to move through time; double-click an arrow to jump 2 hours. Press Save drawn tags when you want Python/session state updated."
          : zoomHistoryCount > 0
            ? "Chart is zoomed. Press R to reset zoom. Press T for tagging or Z for zooming. Hold the left arrow rail to move through time; double-click an arrow to jump 2 hours."
            : "Press T for tagging, Z for zooming, and R to reset zoom. Mouse-wheel/page scroll will not load new plot parts; hold the left arrow rail to move through time or double-click an arrow to jump 2 hours."}
      </div>

      <details className="vlv-hit" open>
        <summary style={{cursor: "pointer", fontWeight: 700}}>
          {hitResultsTitle}
          <span style={{color: "#666", marginLeft: 8, fontWeight: 400}}>
            {visibleRows.length ? `Tags: ${visibleRows.length} | Hits: ${hitCount} | Misses: ${missCount}` : "No dragged tags yet."}
          </span>
        </summary>
        <div style={{overflowX: "auto", marginTop: 6}}>
          {visibleRows.length ? (
            <table>
              <thead>
                <tr>
                  {["Symptom", "Well", "Section", "Date", "Tag Start", "Tag End", "Agent Start", "Agent End", "Result", "Percent"].map((c) => <th key={c}>{c}</th>)}
                </tr>
              </thead>
              <tbody>
                {visibleRows.map((r, i) => (
                  <tr key={i}>
                    {[r.symptom, r.well, r.section, r.date, r.tag_start, r.tag_end, r.agent_start, r.agent_end, r.result, r.percent].map((v, j) => <td key={j}>{v}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <span style={{color: "#777"}}>Draw a tag on the chart to create the first hit-result row.</span>
          )}
        </div>
      </details>

      <div
        ref={wrapRef}
        className="vlv-wrap"
        style={{height}}
        onWheel={onWheel}
        onMouseLeave={() => {
          if (hoverLineRef.current) hoverLineRef.current.style.display = "none";
          if (hoverBoxRef.current) hoverBoxRef.current.style.display = "none";
          commitActiveResize();
          hideSelectBox();
          dragRef.current = {active: false, startY: null, currentY: null};
        }}
      >
        <div ref={plotRef} className="vlv-plot" />
        <div className="vlv-scroll-rail" aria-label="Track time scroll controls">
          <button
            className="vlv-scroll-arrow vlv-scroll-arrow-up"
            title="Hold to scroll to earlier time; double-click to jump 2 hours earlier"
            onDoubleClick={(e) => jumpArrowScroll(-1, e)}
            onMouseDown={(e) => startArrowScroll(-1, e)}
            onMouseUp={stopArrowScroll}
            onMouseLeave={stopArrowScroll}
            onTouchStart={(e) => startArrowScroll(-1, e)}
            onTouchEnd={stopArrowScroll}
          >
            ▲
          </button>
          <div className="vlv-scroll-line" />
          <button
            className="vlv-scroll-arrow vlv-scroll-arrow-down"
            title="Hold to scroll to later time; double-click to jump 2 hours later"
            onDoubleClick={(e) => jumpArrowScroll(1, e)}
            onMouseDown={(e) => startArrowScroll(1, e)}
            onMouseUp={stopArrowScroll}
            onMouseLeave={stopArrowScroll}
            onTouchStart={(e) => startArrowScroll(1, e)}
            onTouchEnd={stopArrowScroll}
          >
            ▼
          </button>
        </div>
        <div
          ref={captureRef}
          className={`vlv-capture ${tagMode ? "active" : ""}`}
          onMouseDown={onMouseDown}
          onMouseMove={onMouseMove}
          onMouseUp={onMouseUp}
          onDoubleClick={onDoubleClick}
        />
        <div ref={selectBoxRef} className="vlv-selection" />
        <div ref={hoverLineRef} className="vlv-hover-line" />
        <div ref={hoverBoxRef} className="vlv-hover-box" />
      </div>

      <div className="vlv-track-footers" aria-label="Track plotted parameter names and limits">
        {trackFooters.map((items, trackIdx) => (
          <div key={trackIdx} className="vlv-track-footer">
            {items.length ? items.map((item, itemIdx) => (
              <div key={itemIdx} className="vlv-track-footer-item">{item}</div>
            )) : (
              <div className="vlv-track-footer-empty">No parameter selected</div>
            )}
          </div>
        ))}
      </div>    
    </div>
  );
}

const ConnectedApp = withStreamlitConnection(App);
createRoot(document.getElementById("root")).render(<ConnectedApp />);
