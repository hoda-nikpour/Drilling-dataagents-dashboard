
import gc
import hashlib
import uuid

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from agents.activity_agents import REQUIRED_ACTIVITY_INPUTS
from agents.symptom_agents import REQUIRED_SYMPTOM_INPUTS
from services.data_quality import build_time_cadence_df

from config import (
    CLEANING_RULES,
    DEFAULT_MARKER_DISPLAY,
    GLOBAL_PARAMETER_ALIASES,
    PARAMETER_CATALOG,
    SECTION_CLEANING_RULES,
    SECTION_PARAMETER_ALIASES,
    TRACK_COLOR_PALETTE,
    WELL_CLEANING_RULES,
    WELL_PARAMETER_ALIASES,
)

from services.data_cleaning import (
    apply_cleaning_layer,
    build_context_cleaning_rules,
)

from data_access.data_loader import (
    get_available_numeric_columns,
    load_catalog,
    load_sections_for_columns,
    load_section_time_index,
)

from services.virtual_window_service import dataframe_to_track_payload

try:
    from streamlit_components.virtual_log_viewer import render_virtual_log_viewer
    VIRTUAL_LOG_VIEWER_IMPORT_ERROR = None
except Exception as e:
    render_virtual_log_viewer = None
    VIRTUAL_LOG_VIEWER_IMPORT_ERROR = e

from services.dashboard_service import (
    build_context_parameter_aliases,
    build_label_to_column_map,
    build_mapping_diagnostic_df,
    build_parameter_catalog_df,
    build_requested_columns,
    build_sections_by_well,
    flatten_selected_params,
    make_context_key,
    run_activity_agent,
    run_symptom_agent,
)

from ui.layout import (
    render_chart,
    render_dashboard_header,
    render_result_tables,
    render_review_caption,
)

from ui.sidebar import (
    apply_loaded_dashboard_state_early,
    build_activity_validation_df,
    build_agent_cfg_from_controls,
    build_boss_symptom_presentation_df,
    build_boss_symptom_presentation_excel,
    build_manual_review_df,
    build_professional_symptom_review_df,
    build_trq_spike_evaluation_df,
    render_agent_picker_gate,
    render_data_agent_lane_and_settings,
    render_track4_manual_tag_controls,
    render_agent_review_outputs,
    render_parameter_range_controls,
    render_review_loader_before_well_selector,
    render_window_pager,
    render_track_parameter_selector,
    render_well_section_selector,
    apply_visual_tag_from_query_params,
)

from ui.styles import apply_global_styles
from utils.helpers import compute_section_ranges
from visualization.chart_builder import create_multi_track_chart

from services.undo_service import (
    begin_undo_tracking,
    commit_undo_tracking,
    render_undo_controls,
)


st.set_page_config(layout="wide", initial_sidebar_state="expanded")
apply_global_styles()


def _build_fixed_time_windows_from_index(time_index, window_hours: int = 12) -> list[dict]:
    """
    Build the same fixed backend windows used by the sidebar pager.
    Only timestamps are used here; no curve data is loaded.
    """
    if time_index is None or len(time_index) == 0:
        return []

    t_min = pd.Timestamp(time_index.min())
    t_max = pd.Timestamp(time_index.max())

    if pd.isna(t_min) or pd.isna(t_max) or t_max <= t_min:
        return []

    window_delta = pd.Timedelta(hours=int(window_hours))
    total_sec = max((t_max - t_min).total_seconds(), 1.0)
    n_windows = max(1, int(total_sec // window_delta.total_seconds()))
    if t_min + n_windows * window_delta < t_max:
        n_windows += 1

    windows = []
    for idx in range(n_windows):
        start = t_min + idx * window_delta
        end = min(start + window_delta, t_max)
        if end > start:
            windows.append({"index": idx, "start": start, "end": end})

    return windows


@st.cache_data(show_spinner="Computing section-wide agent intervals …", max_entries=4)
def build_section_wide_symptom_intervals(
    well: str,
    sections: tuple[str, ...],
    windows: tuple[tuple[str, str], ...],
    requested_columns: tuple[str, ...],
    label_to_column: dict,
    cleaning_rules: dict,
    required_activity_labels: tuple[str, ...],
    required_symptom_labels: tuple[str, ...],
    activity_enabled: bool,
    selected_activity: str,
    activity_config,
    symptom_enabled: bool,
    selected_symptom: str,
    symptom_config,
) -> list[dict]:
    """
    Compute the selected data-agent intervals for the whole section without
    keeping the full section dataframe in memory.

    Activity agents:
    - loop through 12-hour windows
    - load one temporary window
    - run the selected activity classifier
    - keep only interval rows for the selected activity
    - delete the temporary dataframe

    Symptom agents:
    - loop through 12-hour windows
    - run activity features in the background
    - run the selected symptom agent
    - keep only symptom interval rows
    - delete the temporary dataframe

    No raw section-wide dataframe is kept after each window is processed.
    """
    if not activity_enabled or not windows:
        return []

    all_intervals: list[dict] = []

    activity_ui = {
        "enabled": bool(activity_enabled),
        "selected_activity": selected_activity,
        "config": activity_config,
    }
    symptom_ui = {
        "enabled": bool(symptom_enabled),
        "selected_symptom": selected_symptom,
        "config": symptom_config,
    }

    for win_idx, (start_text, end_text) in enumerate(windows, start=1):
        df_part = load_sections_for_columns(
            well=well,
            sections=sections,
            requested_columns=requested_columns,
            time_start=start_text,
            time_end=end_text,
        )

        if df_part.empty:
            continue

        df_part, clean_label_to_column_part, _ = apply_cleaning_layer(
            df=df_part,
            label_to_column=label_to_column,
            cleaning_rules=cleaning_rules,
            required_activity_labels=list(required_activity_labels),
            required_symptom_labels=list(required_symptom_labels),
        )

        activity_cfg_part = run_activity_agent(
            df=df_part,
            label_to_column=clean_label_to_column_part,
            activity_ui=activity_ui,
        )

        if symptom_enabled:
            symptom_cfg_part = run_symptom_agent(
                df=df_part,
                label_to_column=clean_label_to_column_part,
                symptom_ui=symptom_ui,
                activity_ui=activity_ui,
                activity_cfg=activity_cfg_part,
            )
            interval_source = symptom_cfg_part.get("intervals", []) or []
        else:
            interval_source = activity_cfg_part.get("intervals", []) or []
            if selected_activity and selected_activity != "All activities":
                interval_source = [
                    item for item in interval_source
                    if str(item.get("label", "")) == str(selected_activity)
                ]

        for item in interval_source:
            row = dict(item)
            row["window"] = win_idx
            row["window_start"] = start_text
            row["window_end"] = end_text
            all_intervals.append(row)

        # Release the temporary loaded raw window before reading the next one.
        if symptom_enabled:
            try:
                del symptom_cfg_part
            except UnboundLocalError:
                pass
        del df_part, activity_cfg_part, interval_source
        gc.collect()

    all_intervals.sort(key=lambda x: pd.Timestamp(x.get("start")))
    return all_intervals



def _normalize_track_selection_payload(value) -> list[list[str]]:
    """Return exactly three track-selection lists from saved/session data."""
    out: list[list[str]] = []

    if isinstance(value, dict):
        value = [
            value.get("track1", []),
            value.get("track2", []),
            value.get("track3", []),
        ]

    if not isinstance(value, list):
        value = []

    for i in range(3):
        item = value[i] if i < len(value) else []
        if isinstance(item, (list, tuple)):
            out.append([str(x) for x in item if str(x).strip()])
        elif isinstance(item, str) and item.strip():
            out.append([item.strip()])
        else:
            out.append([])

    return out


def _infer_track_params_from_loaded_payload(context_key: str, label_to_column: dict[str, str]) -> list[list[str]]:
    """
    Recover plot selections from an uploaded dashboard session.

    New saved sessions contain saved_track_param_labels_<context>. Older sessions
    may only contain track_params_* widget keys. The user's uploaded example has
    empty track_params but still has max_override_TRQ/RPMB keys, so we also use
    those raw mnemonics as a last-resort compatibility hint.
    """
    payload = st.session_state.get(f"_pending_loaded_review_payload_{context_key}")
    if not isinstance(payload, dict):
        return [[], [], []]

    widget_state = (payload.get("dashboard_state", {}) or {}).get("widget_state", {}) or {}

    candidates = [
        payload.get("plot_track_param_labels"),
        (payload.get("dashboard_state", {}) or {}).get("plot_track_param_labels"),
        widget_state.get(f"saved_track_param_labels_{context_key}"),
        widget_state.get(f"plot_track_param_labels_{context_key}"),
    ]

    for candidate in candidates:
        restored = _normalize_track_selection_payload(candidate)
        if any(restored):
            return restored

    restored = _normalize_track_selection_payload([
        widget_state.get(f"track_params_1_{context_key}", []),
        widget_state.get(f"track_params_2_{context_key}", []),
        widget_state.get(f"track_params_3_{context_key}", []),
    ])
    if any(restored):
        return restored

    # Last-resort compatibility for older saved sessions where the track widgets
    # were saved empty but parameter scale controls reveal what was plotted.
    raw_to_label = {str(raw): label for label, raw in (label_to_column or {}).items()}
    inferred_labels: list[str] = []
    suffix = f"_{context_key}"
    for key in widget_state:
        key = str(key)
        if not key.startswith("max_override_") or not key.endswith(suffix):
            continue
        raw_col = key[len("max_override_") : -len(suffix)]
        label = raw_to_label.get(raw_col)
        if label and label not in inferred_labels:
            inferred_labels.append(label)

    if inferred_labels:
        tracks = [[], [], []]
        for idx, label in enumerate(inferred_labels[:9]):
            tracks[min(idx, 2)].append(label)
        return tracks

    return [[], [], []]


def _remember_track_params_for_save(context_key: str, track_param_labels: list[list[str]]):
    """Store current plot selections under non-widget keys so JSON save/load is reliable."""
    safe_tracks = _normalize_track_selection_payload(track_param_labels)
    if any(safe_tracks):
        # These keys intentionally do not start with '_' so _build_full_dashboard_state()
        # saves them into the dashboard session JSON.
        st.session_state[f"saved_track_param_labels_{context_key}"] = safe_tracks
        st.session_state[f"plot_track_param_labels_{context_key}"] = safe_tracks


def _restore_track_params_after_window_change(
    track_param_labels,
    context_key: str,
    label_to_column: dict[str, str] | None = None,
):
    """
    Keep selected plot parameters when browsing 12-hour windows and after loading
    a saved dashboard session.

    Streamlit does not allow assigning to a widget key after that widget has
    already been instantiated in the same run. Therefore this helper returns the
    restored selections to the plotting pipeline and saves them under separate
    non-widget keys for future JSON export.
    """
    memory_key = f"_last_nonempty_track_params_{context_key}"
    changed_key = f"_window_changed_{context_key}"

    safe_tracks = _normalize_track_selection_payload(track_param_labels)
    has_selection = any(bool(track) for track in safe_tracks)

    if has_selection:
        st.session_state[memory_key] = [list(track) for track in safe_tracks]
        _remember_track_params_for_save(context_key, safe_tracks)
        st.session_state[changed_key] = False
        return safe_tracks

    remembered = st.session_state.get(memory_key)
    remembered_tracks = _normalize_track_selection_payload(remembered)
    if any(remembered_tracks):
        _remember_track_params_for_save(context_key, remembered_tracks)
        st.session_state[changed_key] = False
        return remembered_tracks

    loaded_tracks = _infer_track_params_from_loaded_payload(
        context_key=context_key,
        label_to_column=label_to_column or {},
    )
    if any(loaded_tracks):
        st.session_state[memory_key] = [list(track) for track in loaded_tracks]
        _remember_track_params_for_save(context_key, loaded_tracks)
        st.session_state[changed_key] = False
        return loaded_tracks

    st.session_state[changed_key] = False
    return safe_tracks



def _safe_html_id(value: str) -> str:
    """Return a browser-safe id fragment."""
    return "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in str(value))


def _render_scroll_to_chart_top_once(context_key: str):
    """
    After a 12-hour window navigation click, scroll the browser back to the
    top of the newly loaded plot.

    The scroll flag is set by the bottom Previous/Next buttons and consumed
    once here after the new Streamlit run has rendered the chart anchor.
    """
    flag_key = f"_scroll_to_chart_top_{context_key}"
    if not st.session_state.pop(flag_key, False):
        return

    anchor_id = f"chart_top_anchor_{_safe_html_id(context_key)}"
    components.html(
        f"""
        <script>
        (function() {{
            function scrollToChartTop() {{
                try {{
                    const parentDoc = window.parent.document;
                    const anchor = parentDoc.getElementById({anchor_id!r});
                    if (anchor) {{
                        anchor.scrollIntoView({{behavior: "smooth", block: "start"}});
                        return;
                    }}

                    const appView = parentDoc.querySelector('[data-testid="stAppViewContainer"]');
                    if (appView && appView.scrollTo) {{
                        appView.scrollTo({{top: 0, behavior: "smooth"}});
                        return;
                    }}
                }} catch (e) {{}}

                try {{
                    window.parent.scrollTo({{top: 0, behavior: "smooth"}});
                }} catch (e2) {{}}
            }}

            setTimeout(scrollToChartTop, 250);
            setTimeout(scrollToChartTop, 900);
        }})();
        </script>
        """,
        height=0,
    )



def _virtual_json_safe(obj):
    """Convert Python/Pandas objects into Streamlit-component JSON-safe values."""
    if obj is None:
        return None
    try:
        if pd.isna(obj):
            return None
    except Exception:
        pass
    if isinstance(obj, pd.Timestamp):
        return obj.strftime("%Y-%m-%d %H:%M:%S")
    if hasattr(obj, "strftime") and not isinstance(obj, str):
        try:
            return pd.Timestamp(obj).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
    if isinstance(obj, dict):
        return {str(k): _virtual_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_virtual_json_safe(v) for v in obj]
    return obj


def _virtual_dt_text(value) -> str:
    ts = pd.Timestamp(value)
    return ts.strftime("%Y-%m-%d %H:%M:%S")


def _virtual_visible_delta(visible_hours: float = 12, visible_seconds=None) -> pd.Timedelta:
    """Return the active virtual viewport duration.

    The normal unzoomed viewport is 12 hours. After the user zooms in on the
    time/Y axis, React sends the smaller visible span in seconds. Python then
    loads only that zoomed span plus the configured margin, instead of snapping
    the backend back to a 12-hour viewport.
    """
    if visible_seconds is not None:
        try:
            seconds = float(visible_seconds)
        except Exception:
            seconds = float(visible_hours) * 3600.0
    else:
        seconds = float(visible_hours) * 3600.0

    max_seconds = max(float(visible_hours) * 3600.0, 30.0)
    seconds = max(30.0, min(seconds, max_seconds))
    return pd.Timedelta(seconds=seconds)


def _clamp_virtual_viewport_start(
    start,
    section_start,
    section_end,
    visible_hours: float = 12,
    visible_seconds=None,
) -> pd.Timestamp:
    section_start = pd.Timestamp(section_start)
    section_end = pd.Timestamp(section_end)
    visible_delta = _virtual_visible_delta(
        visible_hours=visible_hours,
        visible_seconds=visible_seconds,
    )

    if pd.isna(section_start) or pd.isna(section_end) or section_end <= section_start:
        return section_start

    latest_start = max(section_start, section_end - visible_delta)

    try:
        start = pd.Timestamp(start)
    except Exception:
        start = section_start

    if pd.isna(start):
        start = section_start
    if start < section_start:
        return section_start
    if start > latest_start:
        return latest_start
    return start



_CHART_DRAWN_TAG_SOURCES = {
    "chart_drag",
    "client_drag_tag",
    "visual",
    "visual_tag",
    "dragged",
    "server_tagger",
}


def _stable_virtual_tag_id(label: str, start_text: str, end_text: str, idx: int = 1) -> str:
    """Create a deterministic id for older chart tags that do not yet have one."""
    raw = f"{label}|{start_text}|{end_text}|{idx}".encode("utf-8", errors="ignore")
    return "tag_" + hashlib.sha1(raw).hexdigest()[:16]


def _is_virtual_chart_tag(item: dict) -> bool:
    return str(item.get("source") or "").strip() in _CHART_DRAWN_TAG_SOURCES


def _normalize_virtual_component_tag(item, idx: int = 1, *, chart_only: bool = False) -> dict | None:
    """Normalize a tag sent to/from the React virtual viewer."""
    if not isinstance(item, dict):
        return None

    try:
        start = pd.Timestamp(item.get("start"))
        end = pd.Timestamp(item.get("end"))
    except Exception:
        return None

    if pd.isna(start) or pd.isna(end) or end <= start:
        return None

    source = str(item.get("source") or "manual").strip() or "manual"
    is_chart_tag = source in _CHART_DRAWN_TAG_SOURCES
    if chart_only and not is_chart_tag:
        return None

    label = str(item.get("label") or (f"Dragged Tag {idx}" if is_chart_tag else f"Tag {idx}"))
    start_text = _virtual_dt_text(start)
    end_text = _virtual_dt_text(end)
    created_at = str(item.get("created_at") or "").strip()
    if is_chart_tag and not created_at:
        created_at = _stable_virtual_tag_id(label, start_text, end_text, idx)

    return {
        "label": label,
        "start": start_text,
        "end": end_text,
        "source": "chart_drag" if is_chart_tag else source,
        "created_at": created_at,
    }


def _virtual_component_tag_identity(item: dict) -> tuple[str, str, str, str]:
    created_at = str(item.get("created_at") or "").strip()
    if created_at and _is_virtual_chart_tag(item):
        return ("chart_id", created_at, "", "")
    return (
        str(item.get("source") or ""),
        str(item.get("label") or ""),
        str(item.get("start") or ""),
        str(item.get("end") or ""),
    )


def _deduplicate_virtual_component_tags(items, *, chart_only: bool = False) -> list[dict]:
    """Remove duplicate tag rows before they are saved or sent back to React."""
    out: list[dict] = []
    seen: set[tuple[str, str, str, str]] = set()

    for idx, item in enumerate(items or [], start=1):
        normalized = _normalize_virtual_component_tag(item, idx, chart_only=chart_only)
        if normalized is None:
            continue
        ident = _virtual_component_tag_identity(normalized)
        if ident in seen:
            continue
        seen.add(ident)
        out.append(normalized)

    return out


def _deduplicate_virtual_hit_results(rows, current_tags: list[dict] | None = None) -> list[dict]:
    """Keep only one hit row per current tag interval and drop stale resize rows."""
    safe_rows = _virtual_json_safe(rows or [])
    if not isinstance(safe_rows, list):
        return []

    allowed = None
    if current_tags is not None:
        allowed = {
            (
                str(tag.get("label") or ""),
                str(tag.get("start") or ""),
                str(tag.get("end") or ""),
            )
            for tag in current_tags
        }

    out: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for row in safe_rows:
        if not isinstance(row, dict):
            continue
        key = (
            str(row.get("tag_label") or ""),
            str(row.get("tag_start") or ""),
            str(row.get("tag_end") or ""),
        )
        if allowed is not None and key not in allowed:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _same_virtual_json_value(left, right) -> bool:
    return _virtual_json_safe(left) == _virtual_json_safe(right)


def _ensure_fresh_virtual_session(context_key: str, *, loaded_dashboard_active: bool = False):
    """Prepare per-browser-session state for the virtual React viewer.

    A fresh dashboard start must not resurrect browser-local tags from an older
    run. Saved dashboard uploads still restore their own tags through
    visual_tag_intervals_<context_key> and saved_tags.
    """
    token_key = f"_virtual_browser_session_token_{context_key}"
    if token_key not in st.session_state:
        st.session_state[token_key] = uuid.uuid4().hex

    initialized_key = f"_virtual_fresh_context_initialized_{context_key}"
    if st.session_state.get(initialized_key):
        return

    if not loaded_dashboard_active:
        for key in (
            f"visual_tag_intervals_{context_key}",
            f"hit_result_history_{context_key}",
            f"virtual_tag_mode_{context_key}",
        ):
            st.session_state.pop(key, None)

    st.session_state[initialized_key] = True


def _build_virtual_window_info(
    time_df: pd.DataFrame,
    context_key: str,
    visible_hours: int = 12,
    margin_hours: int = 4,
) -> dict | None:
    """
    Virtual viewer backend window.

    Browser-visible range: 12 hours.
    Python-loaded buffer: viewport plus 4 hours before/after.
    No downsampling.
    """
    if time_df is None or time_df.empty:
        return None

    section_start = pd.Timestamp(time_df.index.min())
    section_end = pd.Timestamp(time_df.index.max())
    if pd.isna(section_start) or pd.isna(section_end) or section_end <= section_start:
        return None

    viewport_key = f"virtual_viewport_start_{context_key}"
    span_key = f"virtual_viewport_span_seconds_{context_key}"
    max_visible_delta = _virtual_visible_delta(visible_hours=visible_hours)
    max_visible_seconds = max_visible_delta.total_seconds()

    try:
        active_visible_seconds = float(st.session_state.get(span_key, max_visible_seconds))
    except Exception:
        active_visible_seconds = max_visible_seconds
    active_visible_seconds = max(30.0, min(active_visible_seconds, max_visible_seconds))
    visible_delta = _virtual_visible_delta(
        visible_hours=visible_hours,
        visible_seconds=active_visible_seconds,
    )
    margin_delta = pd.Timedelta(hours=float(margin_hours))

    viewport_start = _clamp_virtual_viewport_start(
        st.session_state.get(viewport_key, section_start),
        section_start,
        section_end,
        visible_hours=visible_hours,
        visible_seconds=active_visible_seconds,
    )
    st.session_state[viewport_key] = viewport_start
    st.session_state[span_key] = float(visible_delta.total_seconds())

    viewport_end = min(viewport_start + visible_delta, section_end)
    buffer_start = max(section_start, viewport_start - margin_delta)
    buffer_end = min(section_end, viewport_end + margin_delta)

    return {
        "index": 0,
        "count": 1,
        "start": buffer_start,
        "end": buffer_end,
        "viewport_start": viewport_start,
        "viewport_end": viewport_end,
        "section_start": section_start,
        "section_end": section_end,
        "plot_context_key": (
            f"{context_key}__virtual_"
            f"{_virtual_dt_text(viewport_start)}_{_virtual_dt_text(viewport_end)}"
        ),
        "visible_hours": float(visible_hours),
        "viewport_span_seconds": float(visible_delta.total_seconds()),
        "margin_hours": float(margin_hours),
        "virtual": True,
    }


def _apply_virtual_component_event(component_value, context_key: str, section_start, section_end) -> bool:
    """Store React component changes and reload the raw buffer only when needed.

    React now sends two different events:
    - state_update: save chart-drawn tags and hit rows only.
    - viewport_request: move the backend data window only.

    Keeping these paths separate prevents tag drawing/resizing from accidentally
    changing the virtual scroll position and triggering a rerun loop.
    """
    if not isinstance(component_value, dict):
        return False

    event_type = str(component_value.get("event") or "state_update").strip() or "state_update"
    state_changed = False

    if event_type == "state_update":
        normalized_tags: list[dict] | None = None
        tags = component_value.get("tags")
        if isinstance(tags, list):
            normalized_tags = _deduplicate_virtual_component_tags(tags, chart_only=True)
            visual_key = f"visual_tag_intervals_{context_key}"
            existing_tags = _deduplicate_virtual_component_tags(
                st.session_state.get(visual_key, []) or [],
                chart_only=True,
            )
            if not _same_virtual_json_value(existing_tags, normalized_tags):
                st.session_state[visual_key] = normalized_tags
                state_changed = True

        # Preserve Tagging mode across the rerun caused by accepting a tag.
        # Without this, one drawn tag remounts the component with Tagging off,
        # so a second drag appears to be refused.
        if "tag_mode" in component_value:
            tag_mode_key = f"virtual_tag_mode_{context_key}"
            new_tag_mode = bool(component_value.get("tag_mode"))
            if st.session_state.get(tag_mode_key) != new_tag_mode:
                st.session_state[tag_mode_key] = new_tag_mode
                state_changed = True

        hit_results = component_value.get("hit_results")
        if isinstance(hit_results, list):
            if normalized_tags is None:
                normalized_tags = _deduplicate_virtual_component_tags(
                    st.session_state.get(f"visual_tag_intervals_{context_key}", []) or [],
                    chart_only=True,
                )
            hit_key = f"hit_result_history_{context_key}"
            # React sends the current Hit results table, including both manual
            # sidebar tags and browser-drawn tags. Do not filter this list with
            # chart-only tags, otherwise manual-tag hit rows disappear from
            # saved/restored sessions. React has already rebuilt the rows from
            # the current tag set, so de-duplication is enough here.
            safe_hit_results = _deduplicate_virtual_hit_results(hit_results, None)
            if not _same_virtual_json_value(st.session_state.get(hit_key, []), safe_hit_results):
                st.session_state[hit_key] = safe_hit_results
                state_changed = True

        return state_changed

    if event_type != "viewport_request":
        return False

    # Accept backend window changes only from the React plot-area wheel handler.
    # This is a server-side safety net for the browser/page-scroll mix-up: stale
    # or accidental component values must not move the backend data window.
    if str(component_value.get("source") or "") not in {"arrow_scroll", "set_datetime"}:
       return False

    viewport_text = component_value.get("viewport_start")
    if viewport_text:
        span_seconds = component_value.get("viewport_span_seconds")
        try:
            span_seconds = float(span_seconds)
        except Exception:
            span_seconds = 12 * 3600.0
        span_seconds = max(30.0, min(span_seconds, 12 * 3600.0))

        viewport_start = _clamp_virtual_viewport_start(
            viewport_text,
            section_start,
            section_end,
            visible_hours=12,
            visible_seconds=span_seconds,
        )
        key = f"virtual_viewport_start_{context_key}"
        span_key = f"virtual_viewport_span_seconds_{context_key}"
        last_request_key = f"virtual_last_viewport_request_{context_key}"
        request_fingerprint = f"{_virtual_dt_text(viewport_start)}|{round(span_seconds, 3)}"

        # Do not execute the same window request repeatedly while Streamlit is
        # already processing reruns. This prevents old ScriptRunner messages from
        # creating an apparent reload loop.
        old_span = st.session_state.get(span_key)
        same_span = False
        try:
            same_span = abs(float(old_span) - float(span_seconds)) < 1.0
        except Exception:
            same_span = False

        if (
            st.session_state.get(last_request_key) == request_fingerprint
            and st.session_state.get(key) == viewport_start
            and same_span
        ):
            return False

        if st.session_state.get(key) != viewport_start or not same_span:
            st.session_state[key] = viewport_start
            st.session_state[span_key] = float(span_seconds)
            st.session_state[last_request_key] = request_fingerprint
            st.rerun()

    return False


def _parameter_units_from_catalog(labels: list[list[str]]) -> dict[str, str]:
    units: dict[str, str] = {}
    for track in labels:
        for label in track:
            units[str(label)] = str(PARAMETER_CATALOG.get(str(label), {}).get("unit", ""))
    return units


def _render_virtual_log_component(
    *,
    df: pd.DataFrame,
    context_key: str,
    selected_well: str,
    selected_sections: tuple[str, ...],
    track_params_real: list[list[str]],
    track_param_labels: list[list[str]],
    agent_cfg: dict,
    window_info: dict,
    chart_height: int,
    parameter_ranges: dict[str, tuple[float, float]] | None = None,
):
    if render_virtual_log_viewer is None:
        st.error(
            "The virtual React log viewer is not available. Build the component first:\n\n"
            "cd streamlit_components/virtual_log_viewer/frontend\n"
            "npm install\n"
            "npm run build"
        )

        if VIRTUAL_LOG_VIEWER_IMPORT_ERROR is not None:
            st.exception(VIRTUAL_LOG_VIEWER_IMPORT_ERROR)

        return None

    track_payload = dataframe_to_track_payload(
        df,
        track_params_real=track_params_real[:3],
        track_param_labels=track_param_labels[:3],
        parameter_units=_parameter_units_from_catalog(track_param_labels[:3]),
        parameter_ranges=parameter_ranges,
    )

    manual_or_sidebar_tags = _deduplicate_virtual_component_tags(
        agent_cfg.get("tag_intervals", []) or [],
        chart_only=False,
    )
    visual_tags = _deduplicate_virtual_component_tags(
        st.session_state.get(f"visual_tag_intervals_{context_key}", []) or [],
        chart_only=True,
    )

    # agent_cfg["tag_intervals"] may already contain visual tags from the sidebar
    # merge. Prefer the session-state visual tags because they carry the stable
    # created_at id needed for resize/delete. Fall back to chart tags from
    # agent_cfg only when session state has none, e.g. loaded older sessions.
    manual_tags = [tag for tag in manual_or_sidebar_tags if not _is_virtual_chart_tag(tag)]
    chart_tags_from_agent = [tag for tag in manual_or_sidebar_tags if _is_virtual_chart_tag(tag)]
    chart_tags = visual_tags if visual_tags else chart_tags_from_agent
    saved_tags = _virtual_json_safe(
        _deduplicate_virtual_component_tags(
            list(manual_tags) + list(chart_tags),
            chart_only=False,
        )
    )
    saved_hit_results = _deduplicate_virtual_hit_results(
        st.session_state.get(f"hit_result_history_{context_key}", []) or [],
        saved_tags,
    )

    result = render_virtual_log_viewer(
        key=f"virtual_log_viewer_{context_key}",
        context_key=context_key,
        browser_session_token=str(st.session_state.get(f"_virtual_browser_session_token_{context_key}", "fresh")),
        restore_saved_dashboard=bool(st.session_state.get(f"_loaded_dashboard_active_{context_key}", False)),
        selected_well=selected_well,
        selected_sections=list(selected_sections),
        section_start=_virtual_dt_text(window_info["section_start"]),
        section_end=_virtual_dt_text(window_info["section_end"]),
        buffer_start=_virtual_dt_text(window_info["start"]),
        buffer_end=_virtual_dt_text(window_info["end"]),
        viewport_start=_virtual_dt_text(window_info["viewport_start"]),
        viewport_end=_virtual_dt_text(window_info["viewport_end"]),
        viewport_span_seconds=float(window_info.get("viewport_span_seconds", 12 * 3600)),
        visible_hours=12,
        buffer_margin_hours=4,
        height=int(chart_height),
        track_data=_virtual_json_safe(track_payload),
        agent_intervals=_virtual_json_safe(agent_cfg.get("agent_intervals", []) or []),
        show_agent_intervals=bool(agent_cfg.get("show_agent_intervals", True)),
        selected_agent_name=str(agent_cfg.get("selected_agent", "") or ""),
        agent_source=str(agent_cfg.get("agent_source", "") or ""),
        saved_tags=saved_tags,
        saved_hit_results=_virtual_json_safe(saved_hit_results),
        saved_tag_mode=bool(st.session_state.get(f"virtual_tag_mode_{context_key}", False)),
        marker_display=st.session_state.get(f"marker_display_{context_key}", DEFAULT_MARKER_DISPLAY),
    
    )

    component_state_changed = _apply_virtual_component_event(
        result,
        context_key=context_key,
        section_start=window_info["section_start"],
        section_end=window_info["section_end"],
    )

    # Do not call st.rerun() after a tag state_update. The React component keeps
    # drawn/edited tags locally and browser-persisted, and Python stores them for
    # later Save Dashboard Session/export use. Forcing an immediate rerun here is
    # what made the Plotly component refresh and start the tag-disappear loop.
    return result


def render_bottom_window_navigation(window_info: dict, context_key: str):
    """
    Show Previous/Next controls directly below the four-track chart.

    The active data loading remains controlled by render_window_pager(), but
    these bottom buttons change the same window_index_<context_key> value.
    """
    if not window_info:
        return

    index_key = f"window_index_{context_key}"
    current_index = int(window_info.get("index", st.session_state.get(index_key, 0)))
    window_count = int(window_info.get("count", 1))
    start = pd.Timestamp(window_info.get("start"))
    end = pd.Timestamp(window_info.get("end"))

    st.markdown(
        """
        <style>
            div[data-testid="stHorizontalBlock"]:has(button[kind="secondary"]) {
                margin-top: -0.25rem;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )

    col_prev, col_status, col_next = st.columns([1.2, 2.0, 1.2])

    with col_prev:
        if st.button(
            "⬅ Previous window",
            key=f"bottom_window_prev_{context_key}",
            disabled=current_index <= 0,
            width="stretch",
        ):
            st.session_state[index_key] = max(0, current_index - 1)
            st.session_state[f"_window_changed_{context_key}"] = True
            st.session_state[f"_scroll_to_chart_top_{context_key}"] = True
            st.rerun()

    with col_status:
        st.markdown(
            f"<div style='text-align:center; color:#555; font-size:0.92rem; padding-top:0.45rem;'>"
            f"Window {current_index + 1} / {window_count}: "
            f"{start.strftime('%Y-%m-%d %H:%M')} → {end.strftime('%Y-%m-%d %H:%M')}"
            f"</div>",
            unsafe_allow_html=True,
        )

    with col_next:
        if st.button(
            "Next window ➡",
            key=f"bottom_window_next_{context_key}",
            disabled=current_index >= window_count - 1,
            width="stretch",
        ):
            st.session_state[index_key] = min(window_count - 1, current_index + 1)
            st.session_state[f"_window_changed_{context_key}"] = True
            st.session_state[f"_scroll_to_chart_top_{context_key}"] = True
            st.rerun()

def main():
    begin_undo_tracking()

    catalog = load_catalog()
    if not catalog["sections"]:
        st.error("data/catalog.json not found or empty.")
        st.stop()

    sections_by_well = build_sections_by_well(catalog)

    loaded_review_payload = render_review_loader_before_well_selector()

    selected_well, selected_sections = render_well_section_selector(sections_by_well)

    if not selected_well:
        st.stop()

    if not selected_sections:
        st.stop()

    selected_sections = tuple(sorted(selected_sections, key=float))
    context_key = make_context_key(selected_well, selected_sections)

    

    if loaded_review_payload is not None:
        pending_payload_key = f"_pending_loaded_review_payload_{context_key}"

        # The loader returns a payload only once per uploaded-file content hash.
        # Therefore it is safe and more reliable to apply it whenever it is returned.
        # This avoids the old problem where _loaded_review_restored_done_<context>
        # blocked a newly uploaded file from being applied.
        st.session_state[pending_payload_key] = loaded_review_payload

        apply_loaded_dashboard_state_early(
            uploaded_data=loaded_review_payload,
            context_key=context_key,
        )

        # A saved dashboard file was uploaded for this context. This flag lets
        # the chart restore saved/browser zoom only for loaded sessions, while
        # a fresh app restart starts from the unzoomed/default view.
        st.session_state[f"_loaded_dashboard_active_{context_key}"] = True

    _ensure_fresh_virtual_session(
        context_key=context_key,
        loaded_dashboard_active=bool(st.session_state.get(f"_loaded_dashboard_active_{context_key}", False)),
    )

    agent_gate_source, agent_gate_display, agent_gate_internal = render_agent_picker_gate(
        context_key=context_key,
    )

    if agent_gate_source == "None":
        st.stop()


    time_df = load_section_time_index(
        well=selected_well,
        sections=selected_sections,
    )

    if time_df is not None and not time_df.empty:
        st.session_state[f"_section_time_start_{context_key}"] = pd.Timestamp(
            time_df.index.min()
        ).strftime("%Y-%m-%d %H:%M:%S")
        st.session_state[f"_section_time_end_{context_key}"] = pd.Timestamp(
            time_df.index.max()
        ).strftime("%Y-%m-%d %H:%M:%S")

    use_virtual_log_viewer = True
    st.session_state[f"use_virtual_log_viewer_{context_key}"] = True

    if False:
        with st.sidebar:
            use_virtual_log_viewer = st.toggle(
                "Use smooth virtual log viewer",
                value=True,
                key=f"use_virtual_log_viewer_{context_key}",
                help=(
                    "Use the left-side arrow rail to move through time. Mouse-wheel scrolls the main page only; "
                    "Python loads only the active viewport plus a 4-hour margin. No downsampling."
                ),
            )

    if use_virtual_log_viewer:
        window_info = _build_virtual_window_info(
            time_df=time_df,
            context_key=context_key,
            visible_hours=12,
            margin_hours=4,
        )
    else:
        window_info = render_window_pager(
            time_df=time_df,
            context_key=context_key,
            window_hours=12,
        )

    if window_info is None:
        st.warning("No valid time window is available for the selected section.")
        st.stop()

    selected_time_window = (window_info["start"], window_info["end"])
    plot_context_key = window_info["plot_context_key"]
    zoom_percent = 100.0
    
    discovered_params = get_available_numeric_columns(selected_well, selected_sections)

    context_parameter_aliases = build_context_parameter_aliases(
        selected_well=selected_well,
        selected_sections=selected_sections,
        global_aliases=GLOBAL_PARAMETER_ALIASES,
        well_aliases=WELL_PARAMETER_ALIASES,
        section_aliases=SECTION_PARAMETER_ALIASES,
    )

    label_to_column = build_label_to_column_map(
        discovered_params=discovered_params,
        parameter_aliases=context_parameter_aliases,
    )

    required_activity_labels = [
        label for label in REQUIRED_ACTIVITY_INPUTS if label in label_to_column
    ]

    required_symptom_labels = [
        label for label in REQUIRED_SYMPTOM_INPUTS if label in label_to_column
    ]

    # Columns needed to compute data-agent intervals. This is intentionally
    # separate from plot/diagnostic columns so the section-wide interval table
    # can be built window-by-window without loading unnecessary plot columns.
    
    context_cleaning_rules = build_context_cleaning_rules(
        selected_well=selected_well,
        selected_sections=selected_sections,
        global_rules=CLEANING_RULES,
        well_rules=WELL_CLEANING_RULES,
        section_rules=SECTION_CLEANING_RULES,
    )
    
    section_agent_requested_columns = build_requested_columns(
        selected_labels=[],
        required_activity_labels=required_activity_labels,
        required_symptom_labels=required_symptom_labels,
        label_to_column=label_to_column,
    )

    # Agent controls and agent intervals must be available immediately after
    # the data agent is locked, before plot parameters are selected.
    agent_df = load_sections_for_columns(
        well=selected_well,
        sections=selected_sections,
        requested_columns=tuple(section_agent_requested_columns),
        time_start=selected_time_window[0],
        time_end=selected_time_window[1],
    )

    if agent_df.empty:
        st.error("No data loaded for the selected agent inputs.")
        st.stop()

    agent_df, agent_clean_label_to_column, agent_cleaning_summary_df = apply_cleaning_layer(
        df=agent_df,
        label_to_column=label_to_column,
        cleaning_rules=context_cleaning_rules,
        required_activity_labels=required_activity_labels,
        required_symptom_labels=required_symptom_labels,
    )

    # Create sidebar containers early, immediately after data agent is locked.
    # This allows agent settings, manual tags, and agent interval table to appear
    # before plot parameters are selected.
    agent_controls = render_data_agent_lane_and_settings(
        context_key=context_key,
        agent_source=agent_gate_source,
        selected_agent_internal=agent_gate_internal,
        df=agent_df,
        parent=st.sidebar,
    )

    activity_ui = agent_controls["activity_ui"]
    symptom_ui = agent_controls["symptom_ui"]

    activity_cfg = run_activity_agent(
        df=agent_df,
        label_to_column=agent_clean_label_to_column,
        activity_ui=activity_ui,
    )

    if activity_ui["enabled"] and not activity_cfg["labels"].empty:
        agent_df["activity"] = activity_cfg["labels"]

    symptom_cfg = run_symptom_agent(
        df=agent_df,
        label_to_column=agent_clean_label_to_column,
        symptom_ui=symptom_ui,
        activity_ui=activity_ui,
        activity_cfg=activity_cfg,
    )

    section_windows = _build_fixed_time_windows_from_index(
        time_df.index,
        window_hours=12,
    )

    section_window_tuple = tuple(
        (
            item["start"].strftime("%Y-%m-%d %H:%M:%S"),
            item["end"].strftime("%Y-%m-%d %H:%M:%S"),
        )
        for item in section_windows
    )

    section_wide_agent_intervals = build_section_wide_symptom_intervals(
        well=selected_well,
        sections=selected_sections,
        windows=section_window_tuple,
        requested_columns=tuple(section_agent_requested_columns),
        label_to_column=label_to_column,
        cleaning_rules=context_cleaning_rules,
        required_activity_labels=tuple(required_activity_labels),
        required_symptom_labels=tuple(required_symptom_labels),
        activity_enabled=bool(activity_ui.get("enabled", False)),
        selected_activity=str(activity_ui.get("selected_activity", "All activities")),
        activity_config=activity_ui.get("config"),
        symptom_enabled=bool(symptom_ui.get("enabled", False)),
        selected_symptom=str(symptom_ui.get("selected_symptom", "")),
        symptom_config=symptom_ui.get("config"),
    )

    selected_agent_label = ""
    if agent_controls.get("agent_source") == "Activity agent":
        selected_agent_label = str(activity_ui.get("selected_activity", ""))
    elif agent_controls.get("agent_source") == "Symptom agent":
        selected_agent_label = str(symptom_ui.get("selected_symptom", ""))

    agent_interval_table_cfg = {
        "intervals": section_wide_agent_intervals,
        "interval_scope": "Full selected section, computed window-by-window; each loaded window is released after interval extraction.",
        "interval_table_title": "Agent intervals",
        "selected_agent": selected_agent_label,
        "agent_source": agent_controls.get("agent_source", "None"),
    }

    render_result_tables(
        activity_cfg=activity_cfg,
        symptom_cfg=agent_interval_table_cfg,
        activity_validation_df=pd.DataFrame(),
        review_df=pd.DataFrame(),
    )

    available_param_labels = list(dict.fromkeys(list(label_to_column.keys())))

    if not available_param_labels:
        st.error(
            "None of the requested drilling parameters were found for the selected well/sections. "
            f"Found numeric columns: {', '.join(discovered_params[:30])}"
        )
        st.stop()
    if False:
        with st.expander("Parameter catalog for review", expanded=False):
            st.dataframe(
                build_parameter_catalog_df(
                    label_to_column=label_to_column,
                    parameter_catalog=PARAMETER_CATALOG,
                ),
                width="stretch",
            )

    # If a saved dashboard session was uploaded and its normal track_params
    # widget values were empty in the JSON, recover the plot selections before
    # the multiselect widgets are created. This makes restored parameters both
    # visible in the sidebar and available for plotting.
    restored_tracks_before_widget = _infer_track_params_from_loaded_payload(
        context_key=context_key,
        label_to_column=label_to_column,
    )
    if any(restored_tracks_before_widget):
        for idx in range(3):
            widget_key = f"track_params_{idx + 1}_{context_key}"
            current_value = st.session_state.get(widget_key, [])
            if not current_value:
                st.session_state[widget_key] = restored_tracks_before_widget[idx]
        _remember_track_params_for_save(context_key, restored_tracks_before_widget)

    # Keep parameter selections section-level, not window-level.
    # When the user moves to the next/previous 12-hour window, the same
    # previously selected parameters are plotted automatically for the new window.
    track_param_labels = render_track_parameter_selector(
        available_param_labels=available_param_labels,
        context_key=context_key,
    )

    track_param_labels = _restore_track_params_after_window_change(
        track_param_labels=track_param_labels,
        context_key=context_key,
        label_to_column=label_to_column,
    )

    selected_labels = flatten_selected_params(track_param_labels)

    if not selected_labels:
        st.info("Select parameters from the sidebar to display plots.")
        st.stop()

    parameter_ranges = render_parameter_range_controls(
        selected_labels=selected_labels,
        context_key=context_key,
    )

    with st.sidebar:
        st.subheader("Curve Source")
        curve_source = st.radio(
            "Values shown in Tracks 1–3",
            options=["Raw values", "Cleaned values"],
            index=0,
            key=f"curve_source_{context_key}",
            help=(
                "Raw values preserve the original sensor data. "
                "Cleaned values apply the dashboard cleaning rules. "
                "Agents always use cleaned values."
            ),
        )

    requested_columns = build_requested_columns(
        selected_labels=selected_labels,
        required_activity_labels=required_activity_labels,
        required_symptom_labels=required_symptom_labels,
        label_to_column=label_to_column,
    )

    # Also load all mapped columns so the diagnostic table can check them.
    # Without this, parameters like ROP may appear as "Missing raw column"
    # simply because they were not selected for plotting and not required by agents.
    diagnostic_columns = list(label_to_column.values())

    requested_columns = list(
        dict.fromkeys(requested_columns + diagnostic_columns)
    )

    df = load_sections_for_columns(
        well=selected_well,
        sections=selected_sections,
        requested_columns=tuple(requested_columns),
        time_start=selected_time_window[0],
        time_end=selected_time_window[1],
    )

    if df.empty:
        st.error("No data loaded. Check the parquet files in the data folder.")
        st.stop()

    if st.session_state.get("_show_hidden_time_sampling_raw", False):
        with st.expander("Time sampling diagnostics — raw loaded data", expanded=False):
            st.caption(
                "This table shows the real timestamp spacing in the loaded data. "
                "Use it to check whether the source data is seconds-sampled or minute-sampled."
            )
    
            cadence_df = build_time_cadence_df(df)
            st.dataframe(cadence_df, width="stretch")
    
            if not cadence_df.empty:
                median_steps = pd.to_numeric(cadence_df["Median step sec"], errors="coerce")
                worst_median_step = median_steps.max()
    
                if pd.notna(worst_median_step) and worst_median_step > 30.0:
                    st.warning(
                        "The selected data appears to be low-frequency or minute-range sampled. "
                        "Fast symptoms such as TRQErratic may not be detectable from this data."
                    )
                else:
                    st.success(
                        "The selected data is not minute-range sampled based on the median timestamp step. "
                        "If the chart still looks sparse, it is probably a plotting scale/downsampling issue."
                    )
    
    

    df, clean_label_to_column, cleaning_summary_df = apply_cleaning_layer(
        df=df,
        label_to_column=label_to_column,
        cleaning_rules=context_cleaning_rules,
        required_activity_labels=required_activity_labels,
        required_symptom_labels=required_symptom_labels,
    )

    if st.session_state.get("_show_hidden_parameter_mapping_diagnostics", False):
        with st.expander("Parameter mapping diagnostics", expanded=False):
            st.caption(
                "This table checks whether each logical dashboard parameter is connected "
                "to the expected raw mnemonic and whether its values look physically reasonable."
            )
    
            mapping_diagnostic_df = build_mapping_diagnostic_df(
                df=df,
                label_to_column=label_to_column,
                parameter_catalog=PARAMETER_CATALOG,
            )
    
            st.dataframe(mapping_diagnostic_df, width="stretch")
    
            bad_rows = mapping_diagnostic_df[
                mapping_diagnostic_df["Status"].astype(str).ne("OK")
            ]
    
            if not bad_rows.empty:
                st.warning(
                    "Some curves contain values outside the expected display/diagnostic range. "
                    "This does not automatically mean wrong mapping. It may indicate sensor zero drift, "
                    "unit mismatch, outliers, or valid high-range operation. Check both this table "
                    "and the Data cleaning diagnostics table."
                )
    
            with st.expander("Data cleaning diagnostics", expanded=False):
                st.caption(
                    "Raw data is preserved. The dashboard creates cleaned columns for agent logic. "
                    "Small negative zero-drift values can be corrected to 0. Extreme impossible values become NaN."
                )
    
                if cleaning_summary_df.empty:
                    st.info("No cleaning summary is available.")
                else:
                    st.dataframe(cleaning_summary_df, width="stretch")
    
                    changed_rows = cleaning_summary_df[
                        (
                            cleaning_summary_df["Zero drift corrected"]
                            .fillna(0)
                            .astype(int)
                            > 0
                        )
                        | (
                            cleaning_summary_df["Below hard min invalid"]
                            .fillna(0)
                            .astype(int)
                            > 0
                        )
                        | (
                            cleaning_summary_df["Above hard max invalid"]
                            .fillna(0)
                            .astype(int)
                            > 0
                        )
                        | (
                            cleaning_summary_df["Infinite invalid"]
                            .fillna(0)
                            .astype(int)
                            > 0
                        )
                    ]
    
                    if not changed_rows.empty:
                        st.warning(
                            "Some raw values were corrected or marked invalid for agent use. "
                            "The original raw columns are still preserved for visual review."
                        )
    
    # The dataframe has already been loaded only for the selected fixed 12-hour window.
    # No secondary time filter and no downsampling are used.
    marker_display = DEFAULT_MARKER_DISPLAY

    # Consume chart-drawn tag URL payloads before Track 4 controls and the Plotly
    # figure are built. Tags are stored as section-level absolute timestamps.
    apply_visual_tag_from_query_params(
        context_key=context_key,
        t_min=df.index.min(),
        t_max=df.index.max(),
    )

    review_controls_container = st.sidebar.container()

    track4_controls = render_track4_manual_tag_controls(
        df=df,
        context_key=context_key,
        parent=review_controls_container,
    )

    agent_controls.update(track4_controls)

    if st.session_state.get("_show_hidden_time_sampling_window", False):
        with st.expander("Time sampling diagnostics — selected 12-hour window", expanded=False):
            selected_cadence_df = build_time_cadence_df(df)
            st.dataframe(selected_cadence_df, width="stretch")
    
            st.caption(
                f"Selected 12-hour window contains {len(df):,} raw rows. "
                "No dashboard downsampling is applied; every loaded point is plotted."
            )
    
    


    # This is visually placed above the agent settings because it is rendered
    # into review_controls_container, which was created first.
    agent_cfg = build_agent_cfg_from_controls(
        controls=agent_controls,
        activity_cfg=activity_cfg,
        symptom_cfg=symptom_cfg,
    )

    render_agent_review_outputs(
        agent_cfg=agent_cfg,
        context_key=context_key,
        parent=review_controls_container,
        selected_well=selected_well,
        selected_sections=selected_sections,
    )

    render_dashboard_header(
        selected_well=selected_well,
        selected_sections=selected_sections,
        review_mode=agent_cfg.get("review_mode", "Standard review"),
    )

    summary = agent_cfg.get("summary", {})
    render_review_caption(summary)

    activity_validation_df = build_activity_validation_df(
        agent_cfg.get("activity_validation_summary", {})
    )

    review_df = build_manual_review_df(summary)

    render_result_tables(
        activity_cfg=activity_cfg,
        symptom_cfg={
            "intervals": [],
            "selected_agent": "",
            "agent_source": "None",
        },
        activity_validation_df=activity_validation_df,
        review_df=review_df,
    )

    # Show the miss-reason table only when a Symptom Agent is selected.
    show_symptom_miss_reason_table = (
        agent_cfg.get("agent_source") == "Symptom agent"
        and symptom_ui.get("enabled", False)
        and bool(agent_cfg.get("tag_intervals", []))
    )

    if show_symptom_miss_reason_table:
        professional_review_df = build_professional_symptom_review_df(
            tag_intervals=agent_cfg.get("tag_intervals", []),
            symptom_cfg=symptom_cfg,
            activity_cfg=activity_cfg,
            df_index=df.index,
        )

        boss_presentation_df = build_boss_symptom_presentation_df(
            tag_intervals=agent_cfg.get("tag_intervals", []),
            symptom_cfg=symptom_cfg,
            selected_well=selected_well,
            selected_sections=selected_sections,
        )

        boss_excel_bytes = build_boss_symptom_presentation_excel(
            boss_df=boss_presentation_df,
            professional_df=professional_review_df,
        )

        boss_table_key = (
            "boss_symptom_presentation_"
            f"{context_key}_"
            f"{agent_cfg.get('agent_source')}_"
            f"{symptom_cfg.get('selected_symptom', '')}_"
            f"{len(agent_cfg.get('tag_intervals', []))}_"
            f"{len(symptom_cfg.get('intervals', []))}_"
            f"{hash(str(agent_cfg.get('tag_intervals', [])))}_"
            f"{hash(str(symptom_cfg.get('intervals', [])))}"
        )
        if False:
            with st.expander(
                "Presentation 1 — simple agent result summary",
                expanded=False,
            ):
                st.caption(
                    "Boss-friendly summary. One selected symptom at a time. "
                    "This table compares manual tag intervals against selected agent intervals."
                )

                st.markdown(
                    f"**Symptom:** {symptom_cfg.get('selected_symptom', '')}  \n"
                    f"**Well:** {selected_well}  \n"
                    f"**Section:** {', '.join(f'{str(sec)} in' for sec in selected_sections)}"
                )

                st.dataframe(
                    boss_presentation_df,
                    width="stretch",
                    key=boss_table_key,
                )

                st.download_button(
                    "Download Presentation 1 Excel",
                    data=boss_excel_bytes,
                    file_name=(
                        f"agent_presentation_"
                        f"{selected_well}_"
                        f"{'_'.join(str(sec).replace('.', '_') for sec in selected_sections)}_"
                        f"{symptom_cfg.get('selected_symptom', '')}.xlsx"
                    ),
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=f"download_boss_presentation_excel_{boss_table_key}",
                )

        if False and not professional_review_df.empty:
            with st.expander(
                "Detailed evaluation table",
                expanded=False,
            ):
                st.caption(
                    "Detailed evaluation remains here and in the second Excel sheet. "
                    "Track 4 remains visually clean: Tagger, Overlap, Agent."
                )

                st.dataframe(
                    professional_review_df,
                    width="stretch",
                    key=f"detailed_{boss_table_key}",
                )

    if (
        agent_cfg.get("agent_source") == "Symptom agent"
        and symptom_cfg.get("selected_symptom") == "TRQSpike"
        and not symptom_cfg.get("features", pd.DataFrame()).empty
    ):
        trq_spike_eval_df = build_trq_spike_evaluation_df(symptom_cfg)

        with st.expander(
            "TRQSpike agent result for evaluation — Ratio and z-value",
            expanded=False,
        ):
            st.caption(
                "This table prints the TRQ Ratio and TRQ z-value used by the TRQSpike agent. "
                "Use it to evaluate whether the ratio and z-score thresholds should be adjusted. "
                "Prev. TRQ Std Dev means previous torque standard deviation."
            )

            st.dataframe(
                trq_spike_eval_df,
                width="stretch",
                key=f"trq_spike_eval_{context_key}_{len(trq_spike_eval_df)}",
            )

    if symptom_cfg and not symptom_cfg.get("features", pd.DataFrame()).empty:
        if st.session_state.get("_show_hidden_selected_symptom_debug", False):
            with st.expander("Selected symptom debug features", expanded=False):
                st.dataframe(
                    symptom_cfg["features"].tail(1000),
                    width="stretch",
                )
    
    section_ranges = compute_section_ranges(df, list(selected_sections))

    track_colors = [
        TRACK_COLOR_PALETTE[: len(params)]
        for params in track_param_labels
    ]

    plot_label_to_column = (
        clean_label_to_column
        if curve_source == "Cleaned values"
        else label_to_column
    )

    track_params_real = [
        [
            plot_label_to_column[label]
            for label in track
            if label in plot_label_to_column
        ]
        for track in track_param_labels
    ]

    track_params_real = track_params_real + [[]]
    track_param_labels = track_param_labels + [[]]
    track_colors = track_colors + [[]]

    fig = create_multi_track_chart(
        df=df,
        track_params=track_params_real,
        track_param_labels=track_param_labels,
        track_colors=track_colors,
        zoom_percent=zoom_percent,
        section_ranges=section_ranges,
        agent_cfg=agent_cfg,
        chart_height=agent_cfg.get("chart_height", 950),
        parameter_ranges=parameter_ranges,
        marker_display=marker_display,
        curve_source=curve_source,
    )

    chart_key = f"multi_track_chart_{context_key}"

    saved_hit_results = st.session_state.get(f"hit_result_history_{context_key}", [])

    chart_anchor_id = f"chart_top_anchor_{_safe_html_id(context_key)}"
    st.markdown(
        f'<div id="{chart_anchor_id}" style="scroll-margin-top: 0.75rem;"></div>',
        unsafe_allow_html=True,
    )

    if use_virtual_log_viewer:
        if False:
            st.caption(
                "Virtual log viewer: mouse-wheel scrolls the main page only. Hold the left-side "
                "arrow rail to move through time and load the next raw buffer near the edge. "
                "Raw points are not downsampled."
            )

        _render_virtual_log_component(
            df=df,
            context_key=context_key,
            selected_well=selected_well,
            selected_sections=selected_sections,
            track_params_real=track_params_real,
            track_param_labels=track_param_labels,
            agent_cfg=agent_cfg,
            window_info=window_info,
            chart_height=agent_cfg.get("chart_height", 950),
            parameter_ranges=parameter_ranges,
        )
    else:
        render_chart(
            fig,
            chart_key,
            visual_tag_context_key=context_key,
            restore_saved_browser_zoom=False,
            current_window_start=selected_time_window[0],
            current_window_end=selected_time_window[1],
            saved_hit_results=saved_hit_results,
        )

        render_bottom_window_navigation(window_info=window_info, context_key=context_key)
        _render_scroll_to_chart_top_once(context_key)

    commit_undo_tracking()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback

        st.error("Dashboard crashed. Full Python traceback is shown below.")
        st.exception(e)

        print("\n\n========== DASHBOARD CRASH TRACEBACK ==========")
        print(traceback.format_exc())
        print("========== END DASHBOARD CRASH TRACEBACK ==========\n\n")

        raise
