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

function normalize(values) {
  const nums = values.filter((v) => Number.isFinite(Number(v))).map(Number);
  if (!nums.length) return values.map(() => null);
  const mn = Math.min(...nums);
  const mx = Math.max(...nums);
  if (Math.abs(mx - mn) < 1e-12) return values.map((v) => (v == null ? null : 0.5));
  return values.map((v) => (v == null || !Number.isFinite(Number(v)) ? null : (Number(v) - mn) / (mx - mn)));
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
  const createdAt = String(tag?.created_at || "").trim();
  if (createdAt && isChartTag(tag)) return `chart_id|${createdAt}`;
  const label = String(tag?.label || "").trim();
  const start = String(tag?.start || "").trim();
  const end = String(tag?.end || "").trim();
  const source = String(tag?.source || "manual").trim() || "manual";
  return `${source}|${label}|${start}|${end}`;
}

function isChartTag(tag) {
  return isChartSource(tag?.source);
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
  const createdAt = String(tag.created_at || "").trim() || (chartTag ? stableTagIdFromParts(label, start, end, idx) : "");

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
    .map((tag, idx) => ({
      label: tag.label || `Dragged Tag ${idx + 1}`,
      start: tag.start,
      end: tag.end,
      source: "chart_drag",
      created_at: String(tag.created_at || ""),
    }));
}

function stableJson(value) {
  try {
    return JSON.stringify(value ?? null);
  } catch (err) {
    return "";
  }
}


function chartTagStorageKey(contextKey) {
  return `hoda_virtual_chart_tags_${String(contextKey || "default")}`;
}

function loadStoredChartTags(contextKey) {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(chartTagStorageKey(contextKey));
    const parsed = JSON.parse(raw || "[]");
    return dedupeTags(Array.isArray(parsed) ? parsed : []).filter(isChartTag);
  } catch (err) {
    return [];
  }
}

function saveStoredChartTags(contextKey, items) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      chartTagStorageKey(contextKey),
      JSON.stringify(chartTagsForServer(items || [])),
    );
  } catch (err) {
    // Browser storage failure should not break tag drawing.
  }
}

function clearStoredChartTags(contextKey) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(chartTagStorageKey(contextKey));
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
    xaxis: gridAxis([0.00, 0.23], "Track 1"),
    xaxis2: gridAxis([0.255, 0.485], "Track 2"),
    xaxis3: gridAxis([0.51, 0.74], "Track 3"),
    xaxis4: gridAxis([0.775, 1.0], "Track 4"),
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
        line: {width: 1.5, color: colors[curveIdx % colors.length]},
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

  const sectionStartMs = toMs(args.section_start);
  const sectionEndMs = toMs(args.section_end);
  const bufferStartMs = toMs(args.buffer_start || args.track_data?.time_start);
  const bufferEndMs = toMs(args.buffer_end || args.track_data?.time_end);
  const initialViewportStartMs = toMs(args.viewport_start) || bufferStartMs || sectionStartMs;
  if (initialPlotRangeRef.current == null) initialPlotRangeRef.current = initialViewportStartMs;
  if (viewportStartRef.current == null) viewportStartRef.current = initialViewportStartMs;
  if (viewportSpanRef.current == null) viewportSpanRef.current = visibleMs;

  const [viewportStartMs, setViewportStartMs] = useState(initialViewportStartMs);
  const [viewportSpanMs, setViewportSpanMs] = useState(visibleMs);
  const [tagMode, setTagMode] = useState(Boolean(args.saved_tag_mode));
  const [zoomMode, setZoomModeState] = useState("y");
  const [zoomHistoryCount, setZoomHistoryCount] = useState(0);
  const [redoTags, setRedoTags] = useState([]);
  const [tags, setTags] = useState(() =>
    mergeManualAndChartTags(
      Array.isArray(args.saved_tags) ? args.saved_tags : [],
      loadStoredChartTags(args.context_key),
    ),
  );
  const [selectedTagId, setSelectedTagId] = useState(null);
  const [hitRows, setHitRows] = useState(Array.isArray(args.saved_hit_results) ? args.saved_hit_results : []);

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
      contextKeyRef.current = currentContextKey;
      bufferKeyRef.current = currentBufferKey;
      initialPlotRangeRef.current = newStart;
      viewportStartRef.current = newStart;
      viewportSpanRef.current = visibleMs;
      setViewportSpanMs(visibleMs);
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
  }, [args.context_key, args.viewport_start, bufferStartMs, bufferEndMs, sectionStartMs, clampViewport]);

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
    const storedChart = loadStoredChartTags(args.context_key);
    const incoming = mergeManualAndChartTags(incomingServer, storedChart);

    setTags((old) => {
      const current = dedupeTags(old);
      const merged = mergeManualAndChartTags(incomingServer, [...storedChart, ...current.filter(isChartTag)]);

      if (stableJson(current) === stableJson(merged)) return old;
      suppressStateUpdateRef.current = true;
      return merged;
    });
    setSelectedTagId((oldId) => {
      if (!oldId) return null;
      return incoming.some((tag) => tagKey(tag) === oldId || String(tag.created_at || "") === oldId) ? oldId : null;
    });
  }, [JSON.stringify(args.saved_tags || []), args.context_key]);

  const agents = useMemo(() => normalizeAgentIntervals(args.agent_intervals), [JSON.stringify(args.agent_intervals || [])]);

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
      // Only the normal virtual-scroll mode is allowed to request new backend data.
      // If the user is zooming or drawing tags, do not ask Python for new buffers.
      if (requestLockRef.current || startMs == null) return;
      if (tagModeRef.current) return;
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
      const bufferKey = `${fmtTime(bufferStartMs)}|${fmtTime(bufferEndMs)}|${fmtTime(roundedStartMs)}`;
      if (lastSentViewportRef.current === bufferKey) return;

      lastSentViewportRef.current = bufferKey;
      requestLockRef.current = true;

      Streamlit.setComponentValue({
        event: "viewport_request",
        source: "arrow_scroll",
        viewport_start: fmtTime(roundedStartMs),
      });

      setTimeout(() => {
        requestLockRef.current = false;
      }, 2500);
    },
    [bufferStartMs, bufferEndMs, visibleMs, marginHours, sectionStartMs, sectionEndMs],
  );

  const traces = useMemo(() => {
    const base = buildCurveTraces(args.track_data);
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
  }, [args.track_data, agents, tags, selectedTagId]);

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
    const defaultSymptom = agents[0]?.label || "Agent hit";
    return (currentTags || []).map((tag) => {
      const overlaps = bestOverlapsForTag(tag);
      const best = overlaps[0] || null;
      const percent = best ? best.percent : 0;
      return {
        symptom: best ? best.agent.label : defaultSymptom,
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
    const rows = buildHitRows(cleanTags);
    setHitRows((old) => (stableJson(old) === stableJson(rows) ? old : rows));

    // Critical change: drawing/editing a tag no longer calls Streamlit immediately.
    // Streamlit setComponentValue causes a rerun, which was remounting the plot and
    // starting the refresh loop. Keep chart tags local and persist them in browser
    // storage; sync them to Python only when the user presses "Save drawn tags".
    saveStoredChartTags(args.context_key, cleanTags.filter(isChartTag));
    suppressStateUpdateRef.current = false;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(tags), args.context_key]);



  function sendCurrentStateToStreamlit(reason = "manual_save") {
    const cleanTags = dedupeTags(tags);
    const outgoingChartTags = chartTagsForServer(cleanTags);
    const rows = buildHitRows(cleanTags);
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

  useEffect(() => {
    applyTagMode(tagMode);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tagMode]);

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
            const time = String(p.y || "").split(" ")[1] || String(p.y || "");

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
      if (!isChartTag(tag)) return;
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
    // The virtual log must never load new plot parts from mouse-wheel/page scroll.
    // Only the explicit left-side arrow rail is allowed to move the time viewport.
    return;
  }

  function stepArrowScroll(direction, dtMs = 120) {
    const base = viewportStartRef.current ?? viewportStartMs ?? sectionStartMs;
    if (base == null || !direction) return;

    const activeVisibleMs = getActiveSpanMs();
    const speedMsPerSecond = activeVisibleMs / 7.5;
    const stepMs = direction * speedMsPerSecond * (Math.max(16, Math.min(dtMs, 250)) / 1000);
    const next = clampViewport(base + stepMs, activeVisibleMs);
    if (Math.abs(next - base) < 1) return;

    viewportStartRef.current = next;
    setViewportStartMs(next);
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
    if (arrowScrollRef.current.rafId != null) cancelAnimationFrame(arrowScrollRef.current.rafId);
    arrowScrollRef.current = {active: true, direction, rafId: null, lastTs: 0};
    stepArrowScroll(direction, 180);
    arrowScrollRef.current.rafId = requestAnimationFrame(arrowScrollFrame);
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

    if (selectedTagId) {
      const id = nearestTagId(e.clientY);
      if (id !== selectedTagId) {
        setSelectedTagId(null);
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
            return {...tag, start: fmtTime(Math.min(ns, ne)), end: fmtTime(Math.max(ns, ne)), source: "chart_drag"};
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
    const item = {
      label: `Dragged Tag ${chartTagsForServer(tags).length + 1}`,
      start: fmtTime(s),
      end: fmtTime(en),
      created_at: String(Date.now()),
      source: "chart_drag",
    };
    setRedoTags([]);
    setTags((old) => dedupeTags([...old, item]));
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
    const blob = new Blob([`<html><body>${table}</body></html>`], {type: "application/vnd.ms-excel;charset=utf-8"});
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "dragged_tag_hit_results.xls";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  const visibleRows = buildHitRows(dedupeTags(tags));
  const hitCount = visibleRows.filter((r) => r.result === "Hit").length;
  const missCount = visibleRows.filter((r) => r.result === "Miss").length;

  return (
    <div className="vlv-root">
      <div className="vlv-toolbar">
        <button disabled={zoomHistoryCount === 0} onClick={undoLastZoom}>Undo chart zoom</button>
        <button onClick={resetChartZoom}>Reset chart zoom</button>

        <button
          className={tagMode ? "active" : ""}
          onClick={() => {
            setSelectedTagId(null);
            setTagMode((v) => {
              const next = !v;
              tagModeRef.current = next;
              return next;
            });
          }}
        >
          🏷 Tagging
        </button>
        <button disabled={!tags.some((tag) => String(tag.source || "") === "chart_drag")} onClick={undoLastClientTag}>Undo drag tag</button>
        <button disabled={!selectedTagId} onClick={deleteSelected}>🗑 Delete selected tag</button>
        <button disabled={!redoTags.length} onClick={redoLastClientTag}>Redo drag tag</button>
        <button onClick={() => { clearStoredChartTags(args.context_key); setTags((old) => old.filter((tag) => !isChartTag(tag))); setSelectedTagId(null); setHitRows([]); setRedoTags([]); }}>Clear drag tags</button>
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
          ? "Tagging is active. Drag vertically to draw a Track 4 tag. Tags stay local and the plot will not rerun while drawing. Press Save drawn tags when you want Python/session state updated."
          : zoomHistoryCount > 0
            ? "Chart is zoomed. Double-click or press Undo chart zoom to go back. Use the left arrow rail to scroll through time."
            : "Choose X, Y, or XY zoom mode, then drag a rectangle inside the plot. Use only the left arrow rail to scroll through time; mouse-wheel/page scroll will not load plot parts."}
      </div>

      <details className="vlv-hit" open>
        <summary style={{cursor: "pointer", fontWeight: 700}}>
          Hit results
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
            title="Hold to scroll to earlier time"
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
            title="Hold to scroll to later time"
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
    </div>
  );
}

const ConnectedApp = withStreamlitConnection(App);
createRoot(document.getElementById("root")).render(<ConnectedApp />);



