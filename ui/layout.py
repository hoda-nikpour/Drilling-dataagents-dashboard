 
 
import json
import re
import uuid

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components


def render_dashboard_header(
    selected_well: str,
    selected_sections: tuple[str, ...],
    review_mode: str,
):
    sections_label = "  ·  ".join(f'{s}"' for s in selected_sections)

    st.markdown(
        f'<div class="well-header">Well {selected_well}</div>'
        f'<div class="well-subheader">Mud Logging Dashboard &nbsp;|&nbsp; '
        f'Sections: {sections_label} &nbsp;|&nbsp; Review mode: {review_mode}</div>',
        unsafe_allow_html=True,
    )


def render_review_caption(summary: dict):
    accepted_text = "Accepted" if summary.get("accepted", False) else "Not accepted yet"

    st.caption(
        f"Review summary — Tags: {summary.get('tag_count', 0)} | "
        f"Hits: {summary.get('agent_count', 0)} | "
        f"Overlap: {summary.get('overlap_count', 0)} / {summary.get('tag_count', 0)} | "
        f"Score: {summary.get('score_percent', 0.0):.1f}% | "
        f"Status: {accepted_text}"
    )


def render_result_tables(
    activity_cfg: dict,
    symptom_cfg: dict,
    activity_validation_df: pd.DataFrame,
    review_df: pd.DataFrame,
):
    if not activity_cfg["summary_df"].empty:
        with st.expander("Activity summary", expanded=False):
            st.dataframe(activity_cfg["summary_df"], width="stretch")

    if symptom_cfg["intervals"]:
        symptom_rows = pd.DataFrame(symptom_cfg["intervals"])
        with st.expander("Symptom intervals", expanded=False):
            st.dataframe(symptom_rows, width="stretch")

    if not activity_validation_df.empty:
        with st.expander("Activity validation against manual tags", expanded=False):
            st.dataframe(activity_validation_df, width="stretch")

    # Manual hit review table intentionally hidden from UI.
    # The underlying review_df logic is still preserved in app.py.



def _safe_trace_values(values) -> list:
    """Return a normal Python list from Plotly trace x/y values."""
    if values is None:
        return []
    try:
        return list(values)
    except Exception:
        return []


def _extract_agent_label(trace) -> str:
    """Extract the displayed agent/symptom label from a Track 4 trace."""
    hovertemplate = str(getattr(trace, "hovertemplate", "") or "")
    for pattern in [r"Symptom<br>([^<]+)", r"Activity<br>([^<]+)", r"Agent hit<br>([^<]+)"]:
        match = re.search(pattern, hovertemplate, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    name = str(getattr(trace, "name", "") or "").strip()
    if name:
        return re.sub(r"^.* - ", "", name)
    return "Agent hit"


def _extract_agent_severity(trace) -> str:
    hovertemplate = str(getattr(trace, "hovertemplate", "") or "")
    match = re.search(r"Severity:\s*([^<]+)", hovertemplate, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


def _extract_track4_agent_intervals_from_fig(fig) -> list[dict]:
    """
    Build a reliable payload of Track 4 Agent-lane intervals from the Python
    Plotly figure before it is converted to HTML.
    """
    intervals: list[dict] = []
    for idx, trace in enumerate(getattr(fig, "data", []) or []):
        meta = getattr(trace, "meta", None) or {}
        if isinstance(meta, dict) and str(meta.get("source", "")).startswith("client_drag"):
            continue
        x_values = _safe_trace_values(getattr(trace, "x", None))
        y_values = _safe_trace_values(getattr(trace, "y", None))
        if not x_values or not y_values:
            continue
        numeric_x = []
        for value in x_values:
            try:
                numeric_x.append(float(value))
            except Exception:
                pass
        if not numeric_x:
            continue
        avg_x = sum(numeric_x) / len(numeric_x)
        # Track 4 lane positions: Tagger=0.24, Overlap=0.50, Agent=0.76.
        if avg_x < 0.66 or avg_x > 0.88:
            continue
        parsed_times = []
        for value in y_values:
            ts = pd.to_datetime(value, errors="coerce")
            if pd.notna(ts):
                parsed_times.append(pd.Timestamp(ts))
        if not parsed_times:
            continue
        start = min(parsed_times)
        end = max(parsed_times)
        intervals.append(
            {
                "start": start.strftime("%Y-%m-%d %H:%M:%S"),
                "end": end.strftime("%Y-%m-%d %H:%M:%S"),
                "label": _extract_agent_label(trace),
                "severity": _extract_agent_severity(trace),
                "trace_index": idx,
            }
        )
    return intervals

def render_chart(fig, chart_key: str, visual_tag_context_key: str | None = None):
    """
    Render Plotly chart with controlled zoom tools and one custom cross-track
    horizontal hover line.

    Important:
    - The Plotly chart is rendered exactly once.
    - The horizontal hover line is a single HTML overlay, not one Plotly spike
      line per subplot/track.
    """

    div_id = f"plotly_chart_{uuid.uuid4().hex}"
    wrapper_id = f"plot_wrapper_{div_id}"
    hover_line_id = f"single_hover_line_{div_id}"

    # Backward-compatible fallback:
    # app.py usually creates chart_key as "multi_track_chart_<context_key>".
    # If app.py has not yet been updated to pass visual_tag_context_key directly,
    # this extracts the normal dashboard context key so visual dragging can still
    # create Track 4 tags through query parameters.
    if visual_tag_context_key is None and chart_key.startswith("multi_track_chart_"):
        visual_tag_context_key = chart_key.replace("multi_track_chart_", "", 1)

    config = {
        "displaylogo": False,
        "displayModeBar": True,
        "scrollZoom": False,

        # Disable Plotly default double-click reset.
        # We handle double-click ourselves as Undo chart zoom.
        "doubleClick": False,

        "modeBarButtonsToRemove": [
            "zoom2d",
            "zoomIn2d",
            "zoomOut2d",
            "lasso2d",
            "select2d",
        ],
    }

    plot_html = fig.to_html(
        full_html=False,
        include_plotlyjs="cdn",
        config=config,
        div_id=div_id,
    )

    chart_height = int(fig.layout.height or 950)
    server_agent_intervals = _extract_track4_agent_intervals_from_fig(fig)
    server_agent_intervals_json = json.dumps(server_agent_intervals, ensure_ascii=False)

    # This token is created once per Streamlit session. It prevents browser-stored
    # dragged tags from a previous dashboard session from appearing when the
    # dashboard is opened from scratch. Tags still persist across reruns/zoom
    # changes inside the same active session.
    browser_tag_session_token_key = "_drag_tag_browser_session_token"
    if browser_tag_session_token_key not in st.session_state:
        st.session_state[browser_tag_session_token_key] = uuid.uuid4().hex
    browser_tag_session_token = st.session_state[browser_tag_session_token_key]

    html = f"""
    <div style="font-family: Arial, sans-serif;">
        <style>
            #{div_id} .hoverlayer {{
                display: none !important;
            }}
        </style>

        <div style="
            display: flex;
            justify-content: space-between;
            gap: 8px;
            align-items: center;
            margin-bottom: 8px;
            background: #f7f7f7;
            border: 1px solid #d0d0d0;
            padding: 6px 8px;
        ">
            <div style="
                display: flex;
                gap: 8px;
                align-items: center;
            ">
                <button id="undo_zoom_btn_{div_id}" style="
                    padding: 6px 10px;
                    border: 1px solid #999;
                    background: white;
                    cursor: pointer;
                    font-size: 13px;
                ">
                    Undo chart zoom
                </button>

                <button id="reset_zoom_btn_{div_id}" style="
                    padding: 6px 10px;
                    border: 1px solid #999;
                    background: white;
                    cursor: pointer;
                    font-size: 13px;
                ">
                    Reset chart zoom
                </button>

                <button id="tagging_btn_{div_id}" style="
                    padding: 6px 10px;
                    border: 1px solid #999;
                    background: white;
                    cursor: pointer;
                    font-size: 13px;
                " title="Drag vertically over the chart to create a Track 4 tag interval">
                    🏷 Tagging
                </button>

                <button id="undo_client_tag_btn_{div_id}" style="
                    padding: 6px 10px;
                    border: 1px solid #999;
                    background: white;
                    cursor: pointer;
                    font-size: 13px;
                " title="Remove the most recently drawn Track 4 drag tag. Keeps up to 10 removed tags for redraw.">
                    Undo drag tag
                </button>

                <button id="redo_client_tag_btn_{div_id}" style="
                    padding: 6px 10px;
                    border: 1px solid #999;
                    background: white;
                    cursor: pointer;
                    font-size: 13px;
                " title="Redraw the most recently undone drag tag.">
                    Redo drag tag
                </button>

                <button id="clear_client_tags_btn_{div_id}" style="
                    padding: 6px 10px;
                    border: 1px solid #999;
                    background: white;
                    cursor: pointer;
                    font-size: 13px;
                " title="Clear all dragged visual tags stored in this browser">
                    Clear drag tags
                </button>

                <span id="zoom_history_text_{div_id}" style="
                    font-size: 12px;
                    color: #555;
                ">
                    Chart zoom undo history: 0 / 10
                </span>
            </div>

            <div style="
                display: flex;
                gap: 6px;
                align-items: center;
            ">
                <span style="font-size: 12px; color: #555;">
                    Zoom mode:
                </span>

                <button id="zoom_x_btn_{div_id}" style="
                    padding: 6px 9px;
                    border: 1px solid #999;
                    background: white;
                    cursor: pointer;
                    font-size: 13px;
                " title="Zoom only in X axis">
                    🔍 X
                </button>

                <button id="zoom_y_btn_{div_id}" style="
                    padding: 6px 9px;
                    border: 1px solid #999;
                    background: white;
                    cursor: pointer;
                    font-size: 13px;
                " title="Zoom only in Y/time axis">
                    🔍 Y
                </button>

                <button id="zoom_xy_btn_{div_id}" style="
                    padding: 6px 9px;
                    border: 1px solid #999;
                    background: white;
                    cursor: pointer;
                    font-size: 13px;
                " title="Zoom in both X and Y axes">
                    🔍 XY
                </button>
            </div>
        </div>

        <div id="chart_instruction_text_{div_id}" style="font-size: 12px; color: #555; margin-bottom: 6px;">
            Choose a zoom mode, then drag a rectangle inside the chart.
            Double-click inside the chart = Undo chart zoom.
            Click Tagging, then drag vertically over an abnormal interval to create a Track 4 tag.
        </div>

        <details id="hit_results_panel_{div_id}" style="
            margin: 8px 0 10px 0;
            padding: 8px 10px;
            border: 1px solid #d9d9d9;
            background: #fbfbfb;
            font-size: 12px;
            color: #333;
        ">
            <summary style="cursor:pointer; font-weight:700; list-style-position:outside;">
                Hit results
                <span id="hit_results_summary_{div_id}" style="color:#666; margin-left: 8px; font-weight:400;">No dragged tags yet.</span>
            </summary>
            <div style="display: flex; justify-content: flex-end; gap: 8px; align-items: center; margin: 8px 0 6px 0;">
                <button id="download_hit_results_btn_{div_id}" style="
                    padding: 5px 9px;
                    border: 1px solid #999;
                    background: white;
                    cursor: pointer;
                    font-size: 12px;
                " title="Download the dragged-tag hit result table as an Excel-readable .xls file">
                    Download hit results Excel
                </button>
            </div>
            <div id="hit_results_table_{div_id}" style="overflow-x:auto; margin-top: 6px;"></div>
        </details>

        <div id="{wrapper_id}" style="position: relative;">
            {plot_html}

            <div id="tag_selection_box_{div_id}" style="
                position: absolute;
                display: none;
                left: 0;
                width: 100%;
                background: rgba(128, 0, 128, 0.16);
                border-top: 2px solid rgba(128, 0, 128, 0.85);
                border-bottom: 2px solid rgba(128, 0, 128, 0.85);
                pointer-events: none;
                z-index: 9998;
            "></div>

            <div id="tag_capture_layer_{div_id}" style="
                position: absolute;
                display: none;
                left: 0;
                top: 0;
                width: 100%;
                height: 100%;
                background: rgba(128, 0, 128, 0.015);
                cursor: crosshair;
                pointer-events: auto;
                z-index: 9997;
            "></div>

            <div id="{hover_line_id}" style="
                position: absolute;
                display: none;
                height: 2px;
                background: rgba(40, 40, 40, 0.75);
                pointer-events: none;
                z-index: 9999;
                left: 0;
                top: 0;
                width: 100%;
            "></div>

            <div id="custom_hover_box_{div_id}" style="
                position: absolute;
                display: none;
                pointer-events: none;
                z-index: 10000;
                background: rgba(255, 255, 255, 0.96);
                border: 1px solid rgba(80, 80, 80, 0.35);
                box-shadow: 0 2px 8px rgba(0,0,0,0.18);
                padding: 6px 8px;
                font-size: 12px;
                line-height: 1.25;
                color: #222;
                max-width: 190px;
                white-space: nowrap;
            "></div>
        </div>
    </div>

    <script>
    const gd_{div_id} = document.getElementById("{div_id}");
    const wrapper_{div_id} = document.getElementById("{wrapper_id}");
    const singleHoverLine_{div_id} = document.getElementById("{hover_line_id}");
    const customHoverBox_{div_id} = document.getElementById("custom_hover_box_{div_id}");
    
    const undoBtn_{div_id} = document.getElementById("undo_zoom_btn_{div_id}");
    const resetBtn_{div_id} = document.getElementById("reset_zoom_btn_{div_id}");
    const taggingBtn_{div_id} = document.getElementById("tagging_btn_{div_id}");
    const undoClientTagBtn_{div_id} = document.getElementById("undo_client_tag_btn_{div_id}");
    const redoClientTagBtn_{div_id} = document.getElementById("redo_client_tag_btn_{div_id}");
    const clearClientTagsBtn_{div_id} = document.getElementById("clear_client_tags_btn_{div_id}");
    const historyText_{div_id} = document.getElementById("zoom_history_text_{div_id}");
    const instructionText_{div_id} = document.getElementById("chart_instruction_text_{div_id}");
    const hitResultsSummary_{div_id} = document.getElementById("hit_results_summary_{div_id}");
    const hitResultsTable_{div_id} = document.getElementById("hit_results_table_{div_id}");
    const downloadHitResultsBtn_{div_id} = document.getElementById("download_hit_results_btn_{div_id}");
    const tagSelectionBox_{div_id} = document.getElementById("tag_selection_box_{div_id}");
    const tagCaptureLayer_{div_id} = document.getElementById("tag_capture_layer_{div_id}");

    const zoomXBtn_{div_id} = document.getElementById("zoom_x_btn_{div_id}");
    const zoomYBtn_{div_id} = document.getElementById("zoom_y_btn_{div_id}");
    const zoomXYBtn_{div_id} = document.getElementById("zoom_xy_btn_{div_id}");

    let zoomHistory_{div_id} = [];
    let lastRanges_{div_id} = null;
    let initialRanges_{div_id} = null;

    const maxHistory_{div_id} = 10;

    let programmaticRelayout_{div_id} = false;
    let doubleClickLock_{div_id} = false;

    let taggingMode_{div_id} = false;
    let tagDragActive_{div_id} = false;
    let tagDragStartY_{div_id} = null;
    let tagDragCurrentY_{div_id} = null;
    let clientTagsRestored_{div_id} = false;

    const visualTagContextKey_{div_id} = "{visual_tag_context_key or ''}";
    const browserTagSessionToken_{div_id} = "{browser_tag_session_token}";
    const serverAgentIntervals_{div_id} = {server_agent_intervals_json};

    function deepCopy_{div_id}(obj) {{
        return JSON.parse(JSON.stringify(obj));
    }}

    function updateHistoryText_{div_id}() {{
        historyText_{div_id}.innerText =
            "Chart zoom undo history: " + zoomHistory_{div_id}.length + " / " + maxHistory_{div_id};

        undoBtn_{div_id}.disabled = zoomHistory_{div_id}.length === 0;
        undoBtn_{div_id}.style.opacity = zoomHistory_{div_id}.length === 0 ? "0.5" : "1.0";
        undoBtn_{div_id}.style.cursor = zoomHistory_{div_id}.length === 0 ? "not-allowed" : "pointer";
    }}

    function axisNames_{div_id}() {{
        const names = [];
        const fullLayout = gd_{div_id}._fullLayout || gd_{div_id}.layout || {{}};

        Object.keys(fullLayout).forEach(function(key) {{
            if (/^xaxis\\d*$/.test(key) || /^yaxis\\d*$/.test(key)) {{
                names.push(key);
            }}
        }});

        return names;
    }}

    function getCurrentRanges_{div_id}() {{
        const ranges = {{}};
        const fullLayout = gd_{div_id}._fullLayout || gd_{div_id}.layout || {{}};

        axisNames_{div_id}().forEach(function(axisName) {{
            const axis = fullLayout[axisName];

            if (!axis) {{
                return;
            }}

            ranges[axisName] = {{
                range: axis.range ? [axis.range[0], axis.range[1]] : null,
                autorange: axis.autorange === true
            }};
        }});

        return ranges;
    }}

    function makeRelayoutUpdate_{div_id}(ranges) {{
        const update = {{}};

        Object.keys(ranges || {{}}).forEach(function(axisName) {{
            const axisState = ranges[axisName];

            if (axisState.range && axisState.range.length === 2) {{
                update[axisName + ".range[0]"] = axisState.range[0];
                update[axisName + ".range[1]"] = axisState.range[1];
                update[axisName + ".autorange"] = false;
            }} else {{
                update[axisName + ".autorange"] = true;
            }}
        }});

        return update;
    }}

    function isRealAxisRangeChange_{div_id}(eventData) {{
        const keys = Object.keys(eventData || {{}});

        return keys.some(function(key) {{
            return (
                key.includes(".range") ||
                key.includes(".autorange") ||
                key.includes("range[0]") ||
                key.includes("range[1]")
            );
        }});
    }}

    function captureInitialRangesOnce_{div_id}() {{
        if (initialRanges_{div_id} !== null) {{
            return;
        }}

        const captured = getCurrentRanges_{div_id}();

        if (Object.keys(captured).length === 0) {{
            return;
        }}

        initialRanges_{div_id} = deepCopy_{div_id}(captured);
        lastRanges_{div_id} = deepCopy_{div_id}(captured);
        updateHistoryText_{div_id}();
    }}

    function savePreviousRange_{div_id}() {{
        if (lastRanges_{div_id} === null) {{
            return;
        }}

        zoomHistory_{div_id}.push(deepCopy_{div_id}(lastRanges_{div_id}));

        if (zoomHistory_{div_id}.length > maxHistory_{div_id}) {{
            zoomHistory_{div_id}.shift();
        }}

        updateHistoryText_{div_id}();
    }}

    function undoLastZoom_{div_id}() {{
        if (zoomHistory_{div_id}.length === 0) {{
            updateHistoryText_{div_id}();
            return;
        }}

        const previousRanges = zoomHistory_{div_id}.pop();
        updateHistoryText_{div_id}();

        programmaticRelayout_{div_id} = true;

        Plotly.relayout(gd_{div_id}, makeRelayoutUpdate_{div_id}(previousRanges))
            .then(function() {{
                return Plotly.redraw(gd_{div_id});
            }})
            .then(function() {{
                setTimeout(function() {{
                    lastRanges_{div_id} = getCurrentRanges_{div_id}();
                    programmaticRelayout_{div_id} = false;
                    updateHistoryText_{div_id}();
                }}, 100);
            }});
    }}

    function resetChartZoom_{div_id}() {{
        if (initialRanges_{div_id} === null) {{
            captureInitialRangesOnce_{div_id}();
        }}

        if (initialRanges_{div_id} === null) {{
            return;
        }}

        zoomHistory_{div_id} = [];
        updateHistoryText_{div_id}();

        programmaticRelayout_{div_id} = true;

        Plotly.relayout(gd_{div_id}, makeRelayoutUpdate_{div_id}(initialRanges_{div_id}))
            .then(function() {{
                return Plotly.redraw(gd_{div_id});
            }})
            .then(function() {{
                setTimeout(function() {{
                    lastRanges_{div_id} = deepCopy_{div_id}(initialRanges_{div_id});
                    zoomHistory_{div_id} = [];
                    programmaticRelayout_{div_id} = false;
                    updateHistoryText_{div_id}();
                }}, 100);
            }});
    }}

    function setZoomButtonStyle_{div_id}(activeButton) {{
        const buttons = [zoomXBtn_{div_id}, zoomYBtn_{div_id}, zoomXYBtn_{div_id}];

        buttons.forEach(function(btn) {{
            btn.style.background = "white";
            btn.style.border = "1px solid #999";
            btn.style.fontWeight = "400";
        }});

        activeButton.style.background = "#e8f0fe";
        activeButton.style.border = "1px solid #4a76d1";
        activeButton.style.fontWeight = "700";
    }}


    function setTaggingButtonStyle_{div_id}() {{
        if (taggingMode_{div_id}) {{
            taggingBtn_{div_id}.style.background = "#f3e8ff";
            taggingBtn_{div_id}.style.border = "1px solid #7e22ce";
            taggingBtn_{div_id}.style.fontWeight = "700";
            instructionText_{div_id}.innerText =
                "Tagging mode is active. Drag vertically over the chart to create a Track 4 tag interval.";
        }} else {{
            taggingBtn_{div_id}.style.background = "white";
            taggingBtn_{div_id}.style.border = "1px solid #999";
            taggingBtn_{div_id}.style.fontWeight = "400";
            instructionText_{div_id}.innerText =
                "Choose a zoom mode, then drag a rectangle inside the chart. Double-click inside the chart = Undo chart zoom. Click Tagging, then drag vertically over an abnormal interval to create a Track 4 tag.";
        }}
    }}

    function clamp_{div_id}(value, minValue, maxValue) {{
        return Math.max(minValue, Math.min(maxValue, value));
    }}

    function getPlotMouseY_{div_id}(event) {{
        const gdRect = gd_{div_id}.getBoundingClientRect();
        const fullLayout = gd_{div_id}._fullLayout;

        if (!fullLayout || !fullLayout._size) {{
            return null;
        }}

        const size = fullLayout._size;
        const rawY = event.clientY - gdRect.top - size.t;
        return clamp_{div_id}(rawY, 0, size.h);
    }}

    function dateFromPlotY_{div_id}(plotY) {{
        const fullLayout = gd_{div_id}._fullLayout;

        if (!fullLayout || !fullLayout.yaxis) {{
            return null;
        }}

        let value = null;

        try {{
            value = fullLayout.yaxis.p2d(plotY);
        }} catch (e) {{
            return null;
        }}

        let d = new Date(value);

        if (isNaN(d.getTime())) {{
            d = new Date(String(value));
        }}

        if (isNaN(d.getTime())) {{
            return null;
        }}

        return d;
    }}

    function formatDateForStreamlit_{div_id}(dateValue) {{
        const yyyy = dateValue.getFullYear();
        const mm = String(dateValue.getMonth() + 1).padStart(2, "0");
        const dd = String(dateValue.getDate()).padStart(2, "0");
        const hh = String(dateValue.getHours()).padStart(2, "0");
        const mi = String(dateValue.getMinutes()).padStart(2, "0");
        const ss = String(dateValue.getSeconds()).padStart(2, "0");

        return yyyy + "-" + mm + "-" + dd + " " + hh + ":" + mi + ":" + ss;
    }}

    const clientVisualTagStorageKey_{div_id} =
        "hoda_client_visual_tags_" + visualTagContextKey_{div_id} + "_" + browserTagSessionToken_{div_id};
    const clientVisualTagRedoStorageKey_{div_id} =
        "hoda_client_visual_tags_redo_" + visualTagContextKey_{div_id} + "_" + browserTagSessionToken_{div_id};

    function isoForPlotly_{div_id}(dateValue) {{
        // Plotly accepts local datetime strings on datetime axes.
        return formatDateForStreamlit_{div_id}(dateValue);
    }}

    function buildDateLine_{div_id}(startDate, endDate, points) {{
        const out = [];
        const startMs = startDate.getTime();
        const endMs = endDate.getTime();
        const n = Math.max(2, Number(points) || 20);

        for (let i = 0; i < n; i++) {{
            const frac = i / (n - 1);
            out.push(isoForPlotly_{div_id}(new Date(startMs + frac * (endMs - startMs))));
        }}

        return out;
    }}

    function loadClientVisualTags_{div_id}() {{
        if (!visualTagContextKey_{div_id}) {{
            return [];
        }}

        try {{
            const raw = window.localStorage.getItem(clientVisualTagStorageKey_{div_id});
            const parsed = JSON.parse(raw || "[]");
            return Array.isArray(parsed) ? parsed : [];
        }} catch (e) {{
            return [];
        }}
    }}

    function saveClientVisualTags_{div_id}(items) {{
        if (!visualTagContextKey_{div_id}) {{
            return;
        }}

        try {{
            window.localStorage.setItem(
                clientVisualTagStorageKey_{div_id},
                JSON.stringify(Array.isArray(items) ? items : [])
            );
        }} catch (e) {{}}
    }}

    function loadClientVisualTagRedoStack_{div_id}() {{
        if (!visualTagContextKey_{div_id}) {{
            return [];
        }}

        try {{
            const raw = window.localStorage.getItem(clientVisualTagRedoStorageKey_{div_id});
            const parsed = JSON.parse(raw || "[]");
            return Array.isArray(parsed) ? parsed : [];
        }} catch (e) {{
            return [];
        }}
    }}

    function saveClientVisualTagRedoStack_{div_id}(items) {{
        if (!visualTagContextKey_{div_id}) {{
            return;
        }}

        const stack = Array.isArray(items) ? items.slice(-10) : [];
        try {{
            window.localStorage.setItem(
                clientVisualTagRedoStorageKey_{div_id},
                JSON.stringify(stack)
            );
        }} catch (e) {{}}
    }}

    function _setButtonEnabled_{div_id}(btn, enabled) {{
        if (!btn) return;
        btn.disabled = !enabled;
        btn.style.opacity = enabled ? "1.0" : "0.5";
        btn.style.cursor = enabled ? "pointer" : "not-allowed";
    }}

    function updateClientTagUndoRedoControls_{div_id}() {{
        const activeTags = loadClientVisualTags_{div_id}();
        const redoTags = loadClientVisualTagRedoStack_{div_id}();
        _setButtonEnabled_{div_id}(undoClientTagBtn_{div_id}, activeTags.length > 0);
        _setButtonEnabled_{div_id}(redoClientTagBtn_{div_id}, redoTags.length > 0);
        _setButtonEnabled_{div_id}(clearClientTagsBtn_{div_id}, activeTags.length > 0 || redoTags.length > 0);
    }}

    function _dateMs_{div_id}(value) {{
        const d = new Date(value);
        return isNaN(d.getTime()) ? null : d.getTime();
    }}

    function _arrayLikeToArray_{div_id}(value) {{
        if (value === undefined || value === null) return [];
        if (Array.isArray(value)) return value;
        try {{
            if (typeof value.length === "number") return Array.from(value);
        }} catch (e) {{}}
        return [value];
    }}

    function _traceMinMaxTime_{div_id}(trace) {{
        const yValues = _arrayLikeToArray_{div_id}(trace ? trace.y : null);
        if (!yValues.length) return null;

        const values = [];
        for (let i = 0; i < yValues.length; i++) {{
            const ms = _dateMs_{div_id}(yValues[i]);
            if (ms !== null) values.push(ms);
        }}

        if (!values.length) return null;

        return {{
            startMs: Math.min.apply(null, values),
            endMs: Math.max.apply(null, values)
        }};
    }}

    function _traceAverageX_{div_id}(trace) {{
        const xValues = _arrayLikeToArray_{div_id}(trace ? trace.x : null);
        if (!xValues.length) return null;

        const nums = xValues.map(Number).filter(Number.isFinite);
        if (!nums.length) return null;
        return nums.reduce((a, b) => a + b, 0) / nums.length;
    }}

    function _traceLabelFromHover_{div_id}(trace) {{
        const ht = String((trace && trace.hovertemplate) || "");
        const m1 = ht.match(/Symptom<br>([^<]+)/i);
        if (m1 && m1[1]) return m1[1].trim();
        const m2 = ht.match(/Activity<br>([^<]+)/i);
        if (m2 && m2[1]) return m2[1].trim();
        const nm = String((trace && trace.name) || "");
        if (nm && nm !== "undefined") return nm.replace(/^.* - /, "");
        return "Agent hit";
    }}

    function _isTrack4AgentTrace_{div_id}(trace) {{
        if (!trace) return false;

        const metaSource = trace.meta && trace.meta.source ? String(trace.meta.source) : "";
        if (metaSource === "client_drag_tag" || metaSource === "client_drag_overlap") return false;

        const avgX = _traceAverageX_{div_id}(trace);
        if (avgX === null) return false;

        // Track 4 lanes are: Tagger x=0.24, Overlap x=0.50, Agent x=0.76.
        // Be deliberately broad here because Plotly may not preserve xaxis/yaxis
        // strings in gd.data exactly the same way they were created in Python.
        if (avgX < 0.66 || avgX > 0.88) return false;

        const timeRange = _traceMinMaxTime_{div_id}(trace);
        return !!timeRange;
    }}

    function _normalizeServerAgentInterval_{div_id}(item) {{
        const startMs = _dateMs_{div_id}(item.start);
        const endMs = _dateMs_{div_id}(item.end);
        if (startMs === null || endMs === null) return null;
        const minMs = Math.min(startMs, endMs);
        const maxMs = Math.max(startMs, endMs);
        return {{
            startMs: minMs,
            endMs: maxMs,
            start: formatDateForStreamlit_{div_id}(new Date(minMs)),
            end: formatDateForStreamlit_{div_id}(new Date(maxMs)),
            label: item.label || "Agent hit",
            trace_index: item.trace_index ?? null
        }};
    }}

    function _visibleAgentIntervalsFromServer_{div_id}() {{
        const agents = [];
        (serverAgentIntervals_{div_id} || []).forEach(function(item) {{
            const normalized = _normalizeServerAgentInterval_{div_id}(item || {{}});
            if (normalized) agents.push(normalized);
        }});
        return agents;
    }}

    function _visibleAgentIntervalsFromPlotTraces_{div_id}() {{
        const agents = [];
        (gd_{div_id}.data || []).forEach(function(trace, idx) {{
            if (!_isTrack4AgentTrace_{div_id}(trace)) return;
            const agentRange = _traceMinMaxTime_{div_id}(trace);
            if (!agentRange) return;
            agents.push({{
                startMs: agentRange.startMs,
                endMs: agentRange.endMs,
                start: formatDateForStreamlit_{div_id}(new Date(agentRange.startMs)),
                end: formatDateForStreamlit_{div_id}(new Date(agentRange.endMs)),
                label: _traceLabelFromHover_{div_id}(trace),
                trace_index: idx
            }});
        }});
        return agents;
    }}

    function _visibleAgentIntervals_{div_id}() {{
        const serverAgents = _visibleAgentIntervalsFromServer_{div_id}();
        if (serverAgents.length) return serverAgents;
        return _visibleAgentIntervalsFromPlotTraces_{div_id}();
    }}

    function _mergeOverlapSegments_{div_id}(segments) {{
        if (!segments.length) return [];
        const sorted = segments.slice().sort(function(a, b) {{ return a.startMs - b.startMs; }});
        const merged = [];
        sorted.forEach(function(seg) {{
            if (!merged.length || seg.startMs > merged[merged.length - 1].endMs) {{
                merged.push({{startMs: seg.startMs, endMs: seg.endMs}});
            }} else {{
                merged[merged.length - 1].endMs = Math.max(merged[merged.length - 1].endMs, seg.endMs);
            }}
        }});
        return merged;
    }}

    function _clientOverlapIntervalsForTag_{div_id}(tagItem) {{
        const tagStartMs = _dateMs_{div_id}(tagItem.start);
        const tagEndMs = _dateMs_{div_id}(tagItem.end);
        if (tagStartMs === null || tagEndMs === null) return [];

        let tagMin = Math.min(tagStartMs, tagEndMs);
        let tagMax = Math.max(tagStartMs, tagEndMs);

        // If a user draws an extremely short tag, still allow a small tolerance
        // for matching short agent hits.
        const matchToleranceMs = 1000;
        const tagDurationMs = Math.max(1, tagMax - tagMin);
        const matchMin = tagMin - matchToleranceMs;
        const matchMax = tagMax + matchToleranceMs;
        const rawOverlaps = [];

        _visibleAgentIntervals_{div_id}().forEach(function(agent) {{
            const ovStart = Math.max(tagMin, agent.startMs);
            const ovEnd = Math.min(tagMax, agent.endMs);

            if (ovEnd > ovStart) {{
                const agentDurationMs = Math.max(1, agent.endMs - agent.startMs);
                const matchDurationMs = Math.max(tagDurationMs, agentDurationMs);
                rawOverlaps.push({{
                    start: formatDateForStreamlit_{div_id}(new Date(ovStart)),
                    end: formatDateForStreamlit_{div_id}(new Date(ovEnd)),
                    startMs: ovStart,
                    endMs: ovEnd,
                    overlapMs: ovEnd - ovStart,
                    // Match percent is symmetric: 100% only when the user tag
                    // and the agent interval cover the same time span.
                    // If either interval is shorter/longer, the percent drops.
                    percent: ((ovEnd - ovStart) / matchDurationMs) * 100.0,
                    agent_name: agent.label || "Agent hit",
                    agent_start: agent.start,
                    agent_end: agent.end,
                    agent_index: agent.trace_index
                }});
                return;
            }}

            // Tolerant match for one-sample / visually widened agent hits.
            if (agent.endMs >= matchMin && agent.startMs <= matchMax) {{
                rawOverlaps.push({{
                    start: formatDateForStreamlit_{div_id}(new Date(Math.max(tagMin, agent.startMs))),
                    end: formatDateForStreamlit_{div_id}(new Date(Math.min(tagMax, agent.endMs))),
                    startMs: Math.max(tagMin, agent.startMs),
                    endMs: Math.min(tagMax, agent.endMs),
                    overlapMs: 0,
                    percent: 0.0,
                    agent_name: agent.label || "Agent hit",
                    agent_start: agent.start,
                    agent_end: agent.end,
                    agent_index: agent.trace_index,
                    tolerant_match: true
                }});
            }}
        }});

        rawOverlaps.forEach(function(item) {{
            item.total_overlap_ms = item.overlapMs || 0;
            item.total_percent = item.percent || 0.0;
        }});

        rawOverlaps.sort(function(a, b) {{
            const pa = a.percent || 0;
            const pb = b.percent || 0;
            if (pb !== pa) return pb - pa;
            return (b.overlapMs || 0) - (a.overlapMs || 0);
        }});
        return rawOverlaps;
    }}

    function addClientOverlapTrace_{div_id}(tagItem, overlapItem, redrawNow) {{
        if (!overlapItem || !overlapItem.start || !overlapItem.end) return;

        const startDate = new Date(overlapItem.start);
        const endDate = new Date(overlapItem.end);
        if (isNaN(startDate.getTime()) || isNaN(endDate.getTime())) return;

        const label = tagItem.label || "Dragged tag";
        const overlapTrace = {{
            x: Array(24).fill(0.50),
            y: buildDateLine_{div_id}(startDate, endDate, 24),
            mode: "lines",
            type: "scatter",
            xaxis: "x4",
            yaxis: "y4",
            line: {{
                color: "rgba(60, 160, 90, 0.95)",
                width: 8
            }},
            showlegend: false,
            hovertemplate:
                "Overlap<br>Tag: " + label +
                "<br>Agent: " + (overlapItem.agent_name || "Agent hit") +
                "<br>Start: " + overlapItem.start +
                "<br>End: " + overlapItem.end +
                "<extra></extra>",
            name: "Overlap - " + label,
            meta: {{
                source: "client_drag_overlap",
                tag_created_at: tagItem.created_at || "",
                start: overlapItem.start,
                end: overlapItem.end
            }}
        }};

        Plotly.addTraces(gd_{div_id}, [overlapTrace]).then(function() {{
            if (redrawNow) Plotly.redraw(gd_{div_id});
        }});
    }}

    function drawClientOverlapsForTag_{div_id}(tagItem, redrawNow) {{
        const overlaps = _clientOverlapIntervalsForTag_{div_id}(tagItem);
        if (!overlaps.length) return 0;

        overlaps.forEach(function(overlapItem) {{
            addClientOverlapTrace_{div_id}(tagItem, overlapItem, false);
        }});

        if (redrawNow) {{
            setTimeout(function() {{ Plotly.redraw(gd_{div_id}); }}, 50);
        }}

        return overlaps.length;
    }}

    function addClientVisualTagTrace_{div_id}(tagItem, redrawNow) {{
        if (!tagItem || !tagItem.start || !tagItem.end) {{
            return;
        }}

        const startDate = new Date(tagItem.start);
        const endDate = new Date(tagItem.end);

        if (isNaN(startDate.getTime()) || isNaN(endDate.getTime())) {{
            return;
        }}

        const startText = formatDateForStreamlit_{div_id}(startDate);
        const endText = formatDateForStreamlit_{div_id}(endDate);
        const label = tagItem.label || "Dragged tag";

        const trace = {{
            x: Array(24).fill(0.24),
            y: buildDateLine_{div_id}(startDate, endDate, 24),
            mode: "lines",
            type: "scatter",
            xaxis: "x4",
            yaxis: "y4",
            line: {{
                color: "rgba(128, 0, 128, 0.95)",
                width: 7
            }},
            showlegend: false,
            hovertemplate:
                "Tagger<br>" + label +
                "<br>Start: " + startText +
                "<br>End: " + endText +
                "<extra></extra>",
            name: label,
            meta: {{
                source: "client_drag_tag",
                start: startText,
                end: endText,
                created_at: tagItem.created_at || ""
            }}
        }};

        Plotly.addTraces(gd_{div_id}, [trace]).then(function() {{
            drawClientOverlapsForTag_{div_id}(tagItem, redrawNow);
            rebuildHitResultsTable_{div_id}();
            if (redrawNow) {{
                Plotly.redraw(gd_{div_id});
            }}
        }});
    }}

    function removeClientVisualTagTraces_{div_id}(callback) {{
        const indices = [];
        (gd_{div_id}.data || []).forEach(function(trace, idx) {{
            if (trace && trace.meta && (trace.meta.source === "client_drag_tag" || trace.meta.source === "client_drag_overlap")) {{
                indices.push(idx);
            }}
        }});

        if (indices.length) {{
            // Delete from the end so trace indices remain valid.
            indices.sort(function(a, b) {{ return b - a; }});
            Plotly.deleteTraces(gd_{div_id}, indices).then(function() {{
                if (callback) callback();
            }});
        }} else if (callback) {{
            callback();
        }}
    }}

    function redrawClientVisualTagsFromStorage_{div_id}() {{
        const items = loadClientVisualTags_{div_id}();
        if (!items.length) {{
            rebuildHitResultsTable_{div_id}();
            updateClientTagUndoRedoControls_{div_id}();
            Plotly.redraw(gd_{div_id});
            return;
        }}

        items.forEach(function(item) {{
            addClientVisualTagTrace_{div_id}(item, false);
        }});

        setTimeout(function() {{
            rebuildHitResultsTable_{div_id}();
            updateClientTagUndoRedoControls_{div_id}();
            Plotly.redraw(gd_{div_id});
        }}, 80);
    }}

    function restoreClientVisualTags_{div_id}() {{
        const items = loadClientVisualTags_{div_id}();
        if (!items.length) {{
            rebuildHitResultsTable_{div_id}();
            updateClientTagUndoRedoControls_{div_id}();
            return;
        }}

        items.forEach(function(item) {{
            addClientVisualTagTrace_{div_id}(item, false);
        }});
        updateClientTagUndoRedoControls_{div_id}();
    }}

    function addClientVisualTag_{div_id}(startDate, endDate) {{
        const items = loadClientVisualTags_{div_id}();
        const label = "Dragged Tag " + String(items.length + 1);
        const item = {{
            label: label,
            start: formatDateForStreamlit_{div_id}(startDate),
            end: formatDateForStreamlit_{div_id}(endDate),
            created_at: String(Date.now())
        }};

        items.push(item);
        saveClientVisualTags_{div_id}(items);

        // A new drawn tag starts a new forward history, like normal undo/redo.
        saveClientVisualTagRedoStack_{div_id}([]);

        addClientVisualTagTrace_{div_id}(item, true);

        const overlapCount = _clientOverlapIntervalsForTag_{div_id}(item).length;
        instructionText_{div_id}.innerText =
            "Created " + label + " in Track 4 Tagger lane: " + item.start + " → " + item.end +
            ". Client-side overlap count with visible Agent lane: " + overlapCount +
            ". This visual tag is kept only for this active dashboard session.";
        rebuildHitResultsTable_{div_id}();
        updateClientTagUndoRedoControls_{div_id}();
    }}

    function undoLastClientVisualTag_{div_id}() {{
        const items = loadClientVisualTags_{div_id}();
        if (!items.length) {{
            updateClientTagUndoRedoControls_{div_id}();
            return;
        }}

        const removed = items.pop();
        saveClientVisualTags_{div_id}(items);

        const redoStack = loadClientVisualTagRedoStack_{div_id}();
        redoStack.push(removed);
        saveClientVisualTagRedoStack_{div_id}(redoStack.slice(-10));

        removeClientVisualTagTraces_{div_id}(function() {{
            redrawClientVisualTagsFromStorage_{div_id}();
            instructionText_{div_id}.innerText =
                "Removed latest dragged tag: " + (removed.label || "Dragged tag") +
                ". Click Redo drag tag to redraw it.";
        }});
    }}

    function redoLastClientVisualTag_{div_id}() {{
        const redoStack = loadClientVisualTagRedoStack_{div_id}();
        if (!redoStack.length) {{
            updateClientTagUndoRedoControls_{div_id}();
            return;
        }}

        const restored = redoStack.pop();
        saveClientVisualTagRedoStack_{div_id}(redoStack);

        const items = loadClientVisualTags_{div_id}();
        items.push(restored);
        saveClientVisualTags_{div_id}(items);

        addClientVisualTagTrace_{div_id}(restored, true);
        instructionText_{div_id}.innerText =
            "Redrew dragged tag: " + (restored.label || "Dragged tag") + ".";
        rebuildHitResultsTable_{div_id}();
        updateClientTagUndoRedoControls_{div_id}();
    }}

    function clearClientVisualTags_{div_id}() {{
        saveClientVisualTags_{div_id}([]);
        saveClientVisualTagRedoStack_{div_id}([]);

        removeClientVisualTagTraces_{div_id}(function() {{
            rebuildHitResultsTable_{div_id}();
            updateClientTagUndoRedoControls_{div_id}();
            Plotly.redraw(gd_{div_id});
        }});
    }}

    function _selectedAgentNameForRows_{div_id}() {{
        const agents = _visibleAgentIntervals_{div_id}();
        if (agents.length && agents[0].label) return agents[0].label;
        return "Agent hit";
    }}

    function _tagResultRows_{div_id}() {{
        const tags = loadClientVisualTags_{div_id}();
        const rows = [];
        const defaultSymptom = _selectedAgentNameForRows_{div_id}();

        tags.forEach(function(tagItem) {{
            const overlaps = _clientOverlapIntervalsForTag_{div_id}(tagItem);
            const best = overlaps.length ? overlaps[0] : null;
            const percentValue = best ? (best.total_percent ?? best.percent ?? 0.0) : 0.0;
            rows.push({{
                symptom: best ? (best.agent_name || defaultSymptom) : defaultSymptom,
                well: visualTagContextKey_{div_id}.split("__")[0] || "",
                section: (visualTagContextKey_{div_id}.split("__")[1] || "").replaceAll("_", " + "),
                date: tagItem.start ? tagItem.start.split(" ")[0] : "",
                tag_label: tagItem.label || "Dragged tag",
                tag_start: tagItem.start || "",
                tag_end: tagItem.end || "",
                agent_start: best ? best.agent_start : "",
                agent_end: best ? best.agent_end : "",
                result: best ? "Hit" : "Miss",
                percent_value: percentValue,
                percent: (percentValue.toFixed(1) + "% hit")
            }});
        }});

        return rows;
    }}

    function _htmlEscape_{div_id}(value) {{
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }}

    function rebuildHitResultsTable_{div_id}() {{
        const rows = _tagResultRows_{div_id}();
        const hitCount = rows.filter(function(r) {{ return r.result === "Hit"; }}).length;
        const missCount = rows.filter(function(r) {{ return r.result === "Miss"; }}).length;

        hitResultsSummary_{div_id}.innerText = rows.length
            ? ("Tags: " + rows.length + " | Hits: " + hitCount + " | Misses: " + missCount)
            : "No dragged tags yet.";

        if (!rows.length) {{
            hitResultsTable_{div_id}.innerHTML = "<span style='color:#777'>Draw a tag on the chart to create the first hit-result row.</span>";
            return;
        }}

        let html = "<table style='border-collapse:collapse;width:100%;font-size:12px;background:white'>";
        html += "<thead><tr>";
        ["Symptom", "Well", "Section", "Date", "Tag Start", "Tag End", "Agent Start", "Agent End", "Result", "Percent"].forEach(function(col) {{
            html += "<th style='border:1px solid #ddd;padding:4px 6px;text-align:left;background:#f2f2f2'>" + col + "</th>";
        }});
        html += "</tr></thead><tbody>";

        rows.forEach(function(r) {{
            html += "<tr>";
            [r.symptom, r.well, r.section, r.date, r.tag_start, r.tag_end, r.agent_start, r.agent_end, r.result, r.percent].forEach(function(value) {{
                html += "<td style='border:1px solid #ddd;padding:4px 6px'>" + _htmlEscape_{div_id}(value) + "</td>";
            }});
            html += "</tr>";
        }});

        html += "</tbody></table>";
        hitResultsTable_{div_id}.innerHTML = html;
    }}

    function downloadHitResultsExcel_{div_id}() {{
        const rows = _tagResultRows_{div_id}();
        if (!rows.length) {{
            alert("No dragged-tag hit results to download yet.");
            return;
        }}

        let table = "<table><thead><tr>";
        ["Symptom", "Well", "Section", "Date", "Tag Start", "Tag End", "Agent Start", "Agent End", "Result", "Percent"].forEach(function(col) {{
            table += "<th>" + _htmlEscape_{div_id}(col) + "</th>";
        }});
        table += "</tr></thead><tbody>";
        rows.forEach(function(r) {{
            table += "<tr>";
            [r.symptom, r.well, r.section, r.date, r.tag_start, r.tag_end, r.agent_start, r.agent_end, r.result, r.percent].forEach(function(value) {{
                table += "<td>" + _htmlEscape_{div_id}(value) + "</td>";
            }});
            table += "</tr>";
        }});
        table += "</tbody></table>";

        const html = "<html><head><meta charset='utf-8'></head><body>" +
            "<h3>Presentation 1 — Agent hit results from dragged tags</h3>" +
            table + "</body></html>";

        const blob = new Blob([html], {{type: "application/vnd.ms-excel;charset=utf-8"}});
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "dragged_tag_hit_results.xls";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }}

    function showTagSelectionBox_{div_id}(startPlotY, currentPlotY) {{
        const fullLayout = gd_{div_id}._fullLayout;

        if (!fullLayout || !fullLayout._size) {{
            return;
        }}

        const size = fullLayout._size;
        const topPlotY = Math.min(startPlotY, currentPlotY);
        const bottomPlotY = Math.max(startPlotY, currentPlotY);

        tagSelectionBox_{div_id}.style.left = size.l + "px";
        tagSelectionBox_{div_id}.style.width = size.w + "px";
        tagSelectionBox_{div_id}.style.top = (size.t + topPlotY) + "px";
        tagSelectionBox_{div_id}.style.height = Math.max(4, bottomPlotY - topPlotY) + "px";
        tagSelectionBox_{div_id}.style.display = "block";
    }}

    function hideTagSelectionBox_{div_id}() {{
        tagSelectionBox_{div_id}.style.display = "none";
    }}

    function updateTagCaptureLayer_{div_id}() {{
        const fullLayout = gd_{div_id}._fullLayout;

        if (!fullLayout || !fullLayout._size) {{
            tagCaptureLayer_{div_id}.style.display = "none";
            return;
        }}

        const size = fullLayout._size;
        tagCaptureLayer_{div_id}.style.left = size.l + "px";
        tagCaptureLayer_{div_id}.style.top = size.t + "px";
        tagCaptureLayer_{div_id}.style.width = size.w + "px";
        tagCaptureLayer_{div_id}.style.height = size.h + "px";
        tagCaptureLayer_{div_id}.style.display = taggingMode_{div_id} ? "block" : "none";
    }}

    function setPlotlyPointerLockForTagging_{div_id}() {{
        const fullLayout = gd_{div_id}._fullLayout;

        // When the overlay is visible it receives all mouse events.
        // These two lines are extra protection against Plotly zoom handlers
        // still reacting during tagging mode.
        if (fullLayout && fullLayout._draggers) {{
            try {{ fullLayout._draggers.style("pointer-events", taggingMode_{div_id} ? "none" : "all"); }} catch (e) {{}}
        }}

        const dragLayer = gd_{div_id}.querySelector(".draglayer");
        if (dragLayer) {{
            dragLayer.style.pointerEvents = taggingMode_{div_id} ? "none" : "auto";
        }}
    }}

    function submitVisualTag_{div_id}(startPlotY, endPlotY) {{
        if (!visualTagContextKey_{div_id}) {{
            alert("Visual tagging needs visual_tag_context_key from Streamlit.");
            return;
        }}

        const d1 = dateFromPlotY_{div_id}(startPlotY);
        const d2 = dateFromPlotY_{div_id}(endPlotY);

        if (!d1 || !d2) {{
            alert("Could not convert the dragged region into a time interval.");
            return;
        }}

        const startDate = d1 < d2 ? d1 : d2;
        const endDate = d1 < d2 ? d2 : d1;

        // Browser/Streamlit iframe navigation is unreliable in components.html.
        // Instead, use the same Plotly-side drawing approach as the cross-track
        // hover/reference line: draw the dragged interval directly into Track 4.
        // This bypasses iframe-to-Python communication and proves the visual
        // tagging workflow immediately.
        addClientVisualTag_{div_id}(startDate, endDate);
    }}

    function setZoomMode_{div_id}(mode) {{
        taggingMode_{div_id} = false;
        tagDragActive_{div_id} = false;
        hideTagSelectionBox_{div_id}();
        updateTagCaptureLayer_{div_id}();
        setPlotlyPointerLockForTagging_{div_id}();
        setTaggingButtonStyle_{div_id}();

        const update = {{
            "dragmode": "zoom"
        }};

        axisNames_{div_id}().forEach(function(axisName) {{
            if (axisName.startsWith("xaxis")) {{
                update[axisName + ".fixedrange"] = mode === "y";
            }}

            if (axisName.startsWith("yaxis")) {{
                update[axisName + ".fixedrange"] = mode === "x";
            }}
        }});

        Plotly.relayout(gd_{div_id}, update);
    }}

    zoomXBtn_{div_id}.onclick = function() {{
        setZoomMode_{div_id}("x");
        setZoomButtonStyle_{div_id}(zoomXBtn_{div_id});
    }};

    zoomYBtn_{div_id}.onclick = function() {{
        setZoomMode_{div_id}("y");
        setZoomButtonStyle_{div_id}(zoomYBtn_{div_id});
    }};

    zoomXYBtn_{div_id}.onclick = function() {{
        setZoomMode_{div_id}("xy");
        setZoomButtonStyle_{div_id}(zoomXYBtn_{div_id});
    }};

    taggingBtn_{div_id}.onclick = function() {{
        taggingMode_{div_id} = !taggingMode_{div_id};
        setTaggingButtonStyle_{div_id}();

        if (taggingMode_{div_id}) {{
            const update = {{"dragmode": false}};

            // Freeze Plotly axes while tagging. This prevents the normal
            // Y-zoom drag from competing with the tag drag.
            axisNames_{div_id}().forEach(function(axisName) {{
                update[axisName + ".fixedrange"] = true;
            }});

            Plotly.relayout(gd_{div_id}, update).then(function() {{
                updateTagCaptureLayer_{div_id}();
                setPlotlyPointerLockForTagging_{div_id}();
            }});
        }} else {{
            setZoomMode_{div_id}("y");
            setZoomButtonStyle_{div_id}(zoomYBtn_{div_id});
        }}
    }};

    if (undoClientTagBtn_{div_id}) {{
        undoClientTagBtn_{div_id}.onclick = function() {{
            undoLastClientVisualTag_{div_id}();
        }};
    }};

    if (redoClientTagBtn_{div_id}) {{
        redoClientTagBtn_{div_id}.onclick = function() {{
            redoLastClientVisualTag_{div_id}();
        }};
    }};

    if (clearClientTagsBtn_{div_id}) {{
        clearClientTagsBtn_{div_id}.onclick = function() {{
            clearClientVisualTags_{div_id}();
            instructionText_{div_id}.innerText = "Cleared all browser-stored dragged tags from Track 4.";
        }};
    }};

    if (downloadHitResultsBtn_{div_id}) {{
        downloadHitResultsBtn_{div_id}.onclick = function() {{
            downloadHitResultsExcel_{div_id}();
        }};
    }};

    gd_{div_id}.on("plotly_afterplot", function() {{
        setTimeout(function() {{
            captureInitialRangesOnce_{div_id}();
            updateTagCaptureLayer_{div_id}();
            if (!clientTagsRestored_{div_id}) {{
                clientTagsRestored_{div_id} = true;
                restoreClientVisualTags_{div_id}();
            }}
            rebuildHitResultsTable_{div_id}();
        }}, 250);
    }});

    setTimeout(function() {{
        captureInitialRangesOnce_{div_id}();

        // Default mode: vertical/time zoom.
        setZoomMode_{div_id}("y");
        setZoomButtonStyle_{div_id}(zoomYBtn_{div_id});
        restoreClientVisualTags_{div_id}();
    }}, 500);

    gd_{div_id}.on("plotly_relayout", function(eventData) {{
        if (programmaticRelayout_{div_id}) {{
            return;
        }}

        if (!isRealAxisRangeChange_{div_id}(eventData)) {{
            return;
        }}

        savePreviousRange_{div_id}();

        setTimeout(function() {{
            lastRanges_{div_id} = getCurrentRanges_{div_id}();
            updateHistoryText_{div_id}();
        }}, 100);
    }});

    undoBtn_{div_id}.onclick = function() {{
        undoLastZoom_{div_id}();
    }};

    resetBtn_{div_id}.onclick = function() {{
        resetChartZoom_{div_id}();
    }};

    gd_{div_id}.on("plotly_doubleclick", function() {{
        if (doubleClickLock_{div_id}) {{
            return false;
        }}

        doubleClickLock_{div_id} = true;
        undoLastZoom_{div_id}();

        setTimeout(function() {{
            doubleClickLock_{div_id} = false;
        }}, 500);

        return false;
    }});

    function escapeHtml_{div_id}(value) {{
        return String(value)
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }}

    function formatTimeOnly_{div_id}(value) {{
        const d = new Date(value);

        if (isNaN(d.getTime())) {{
            return String(value);
        }}

        const hh = String(d.getHours()).padStart(2, "0");
        const mm = String(d.getMinutes()).padStart(2, "0");
        const ss = String(d.getSeconds()).padStart(2, "0");

        return hh + ":" + mm + ":" + ss;
    }}

    function formatValue_{div_id}(value) {{
        const num = Number(value);

        if (!Number.isFinite(num)) {{
            return String(value ?? "");
        }}

        return num.toFixed(1);
    }}

    function showCustomHoverBox_{div_id}(eventData) {{
        if (!eventData || !eventData.points || eventData.points.length === 0) {{
            return;
        }}

        const point = eventData.points[0];
        const mouseEvent = eventData.event;

        if (!mouseEvent) {{
            return;
        }}

        const meta = point.data && point.data.meta ? point.data.meta : {{}};

        let parameterName = meta.label || "";

        if (!parameterName && point.data && point.data.name) {{
            parameterName = String(point.data.name).replace(/^Track \\d+ - /, "");
        }}

        if (!parameterName) {{
            parameterName = "Value";
        }}

        let value = "";

        if (point.customdata && point.customdata.length > 0) {{
            value = formatValue_{div_id}(point.customdata[0]);
        }} else if (point.x !== undefined && point.x !== null) {{
            value = formatValue_{div_id}(point.x);
        }}

        const unit = meta.unit ? " " + meta.unit : "";
        const timeText = formatTimeOnly_{div_id}(point.y);

        customHoverBox_{div_id}.innerHTML =
            "<b>" + escapeHtml_{div_id}(parameterName) + "</b><br>" +
            escapeHtml_{div_id}(value + unit) + "<br>" +
            "Time: " + escapeHtml_{div_id}(timeText);

        const wrapperRect = wrapper_{div_id}.getBoundingClientRect();

        // Put the hover box about 2 cm above the cursor.
        // 2 cm is roughly 75 px on normal screens.
        let left = mouseEvent.clientX - wrapperRect.left + 12;
        let top = mouseEvent.clientY - wrapperRect.top - 78;

        customHoverBox_{div_id}.style.display = "block";

        const boxRect = customHoverBox_{div_id}.getBoundingClientRect();
        const maxLeft = wrapperRect.width - boxRect.width - 8;

        if (left > maxLeft) {{
            left = maxLeft;
        }}

        if (left < 8) {{
            left = 8;
        }}

        if (top < 8) {{
            top = mouseEvent.clientY - wrapperRect.top + 18;
        }}

        customHoverBox_{div_id}.style.left = left + "px";
        customHoverBox_{div_id}.style.top = top + "px";
    }}

    function hideCustomHoverBox_{div_id}() {{
        customHoverBox_{div_id}.style.display = "none";
    }}
    
    
    function showSingleHoverLine_{div_id}(yValue) {{
        const fullLayout = gd_{div_id}._fullLayout;

        if (!fullLayout || !fullLayout.yaxis || !fullLayout._size) {{
            return;
        }}

        const yAxis = fullLayout.yaxis;
        const size = fullLayout._size;

        let yPixel = null;

        try {{
            yPixel = yAxis.d2p(yValue);
        }} catch (e) {{
            try {{
                yPixel = yAxis.d2p(new Date(yValue));
            }} catch (e2) {{
                yPixel = null;
            }}
        }}

        if (yPixel === null || isNaN(yPixel)) {{
            return;
        }}

        const top = size.t + yPixel;

        singleHoverLine_{div_id}.style.left = size.l + "px";
        singleHoverLine_{div_id}.style.width = size.w + "px";
        singleHoverLine_{div_id}.style.top = top + "px";
        singleHoverLine_{div_id}.style.display = "block";
    }}

    function hideSingleHoverLine_{div_id}() {{
        singleHoverLine_{div_id}.style.display = "none";
    }}

    gd_{div_id}.on("plotly_hover", function(eventData) {{
        if (!eventData || !eventData.points || eventData.points.length === 0) {{
            return;
        }}

        const point = eventData.points[0];

        if (point && point.y !== undefined && point.y !== null) {{
            showSingleHoverLine_{div_id}(point.y);
        }}

        showCustomHoverBox_{div_id}(eventData);
    }});

    gd_{div_id}.on("plotly_unhover", function() {{
        hideSingleHoverLine_{div_id}();
        hideCustomHoverBox_{div_id}();
    }});

    gd_{div_id}.addEventListener("mouseleave", function() {{
        hideSingleHoverLine_{div_id}();
        hideCustomHoverBox_{div_id}();
    }});

    wrapper_{div_id}.addEventListener("mouseleave", function() {{
        hideSingleHoverLine_{div_id}();
        hideCustomHoverBox_{div_id}();
    }});

    tagCaptureLayer_{div_id}.addEventListener("mousedown", function(event) {{
        if (!taggingMode_{div_id}) {{
            return;
        }}

        const plotY = getPlotMouseY_{div_id}(event);

        if (plotY === null) {{
            return;
        }}

        tagDragActive_{div_id} = true;
        tagDragStartY_{div_id} = plotY;
        tagDragCurrentY_{div_id} = plotY;

        showTagSelectionBox_{div_id}(tagDragStartY_{div_id}, tagDragCurrentY_{div_id});

        event.preventDefault();
        event.stopPropagation();
    }}, true);

    tagCaptureLayer_{div_id}.addEventListener("mousemove", function(event) {{
        if (!taggingMode_{div_id} || !tagDragActive_{div_id}) {{
            return;
        }}

        const plotY = getPlotMouseY_{div_id}(event);

        if (plotY === null) {{
            return;
        }}

        tagDragCurrentY_{div_id} = plotY;
        showTagSelectionBox_{div_id}(tagDragStartY_{div_id}, tagDragCurrentY_{div_id});

        event.preventDefault();
        event.stopPropagation();
    }}, true);

    tagCaptureLayer_{div_id}.addEventListener("mouseup", function(event) {{
        if (!taggingMode_{div_id} || !tagDragActive_{div_id}) {{
            return;
        }}

        const plotY = getPlotMouseY_{div_id}(event);

        tagDragActive_{div_id} = false;
        hideTagSelectionBox_{div_id}();

        if (plotY === null || tagDragStartY_{div_id} === null) {{
            return;
        }}

        const dragDistance = Math.abs(plotY - tagDragStartY_{div_id});

        if (dragDistance < 6) {{
            return;
        }}

        submitVisualTag_{div_id}(tagDragStartY_{div_id}, plotY);

        event.preventDefault();
        event.stopPropagation();
    }}, true);

    updateHistoryText_{div_id}();
    setTaggingButtonStyle_{div_id}();
    updateClientTagUndoRedoControls_{div_id}();
    </script>
    """

    components.html(
        html,
        height=chart_height + 260,
        scrolling=True,
    )