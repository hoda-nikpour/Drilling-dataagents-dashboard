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


def render_chart(fig, chart_key: str):
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

        <div style="font-size: 12px; color: #555; margin-bottom: 6px;">
            Choose a zoom mode, then drag a rectangle inside the chart.
            Double-click inside the chart = Undo chart zoom.
        </div>

        <div id="{wrapper_id}" style="position: relative;">
            {plot_html}

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
    const historyText_{div_id} = document.getElementById("zoom_history_text_{div_id}");

    const zoomXBtn_{div_id} = document.getElementById("zoom_x_btn_{div_id}");
    const zoomYBtn_{div_id} = document.getElementById("zoom_y_btn_{div_id}");
    const zoomXYBtn_{div_id} = document.getElementById("zoom_xy_btn_{div_id}");

    let zoomHistory_{div_id} = [];
    let lastRanges_{div_id} = null;
    let initialRanges_{div_id} = null;

    const maxHistory_{div_id} = 10;

    let programmaticRelayout_{div_id} = false;
    let doubleClickLock_{div_id} = false;

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

    function setZoomMode_{div_id}(mode) {{
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

    gd_{div_id}.on("plotly_afterplot", function() {{
        setTimeout(function() {{
            captureInitialRangesOnce_{div_id}();
        }}, 250);
    }});

    setTimeout(function() {{
        captureInitialRangesOnce_{div_id}();

        // Default mode: vertical/time zoom.
        setZoomMode_{div_id}("y");
        setZoomButtonStyle_{div_id}(zoomYBtn_{div_id});
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

    updateHistoryText_{div_id}();
    </script>
    """

    components.html(
        html,
        height=chart_height + 140,
        scrolling=True,
    )