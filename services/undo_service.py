# services/undo_service.py

from copy import deepcopy
from datetime import date, datetime, time

import pandas as pd
import streamlit as st


UNDO_HISTORY_KEY = "_undo_history"
UNDO_LAST_SNAPSHOT_KEY = "_undo_last_snapshot"
UNDO_INITIALIZED_KEY = "_undo_initialized"
UNDO_RESTORING_KEY = "_undo_restoring"
UNDO_MAX_STEPS = 10


def _is_safe_value(value) -> bool:
    """
    Only store small, UI-like values in the undo history.

    We intentionally avoid large objects such as DataFrames, uploaded files,
    Plotly figures, cached objects, etc.
    """
    safe_scalar_types = (
        str,
        int,
        float,
        bool,
        type(None),
        datetime,
        date,
        time,
        pd.Timestamp,
    )

    if isinstance(value, safe_scalar_types):
        return True

    if isinstance(value, tuple):
        return all(_is_safe_value(item) for item in value)

    if isinstance(value, list):
        return all(_is_safe_value(item) for item in value)

    if isinstance(value, dict):
        return all(
            isinstance(k, str) and _is_safe_value(v)
            for k, v in value.items()
        )

    return False


def _should_track_key(key: str) -> bool:
    """
    Track dashboard/sidebar choices, but ignore undo internals,
    one-click buttons, downloads, uploads, and chart reset controls.
    """
    # Do not track internal app/session machinery.
    # Only user-facing widget state should be undoable.
    if key.startswith("_"):
        return False

    ignored_fragments = [
        "download_",
        "upload",
        "reset_chart_zoom",
        "reset_time",
        "FormSubmitter",
    ]

    return not any(fragment in key for fragment in ignored_fragments)


def _snapshot_state() -> dict:
    snapshot = {}

    for key, value in st.session_state.items():
        if not _should_track_key(str(key)):
            continue

        if not _is_safe_value(value):
            continue

        try:
            snapshot[key] = deepcopy(value)
        except Exception:
            continue

    return snapshot


def begin_undo_tracking():
    """
    Call once near the beginning of app.py, before most widgets are rendered.

    It compares the current session_state with the previous saved snapshot.
    If the user changed something since the last run, the previous snapshot
    is pushed into the undo stack.
    """
    if UNDO_HISTORY_KEY not in st.session_state:
        st.session_state[UNDO_HISTORY_KEY] = []

    current_snapshot = _snapshot_state()

    if st.session_state.get(UNDO_RESTORING_KEY, False):
        st.session_state[UNDO_LAST_SNAPSHOT_KEY] = current_snapshot
        st.session_state[UNDO_RESTORING_KEY] = False
        st.session_state[UNDO_INITIALIZED_KEY] = True
        return

    if not st.session_state.get(UNDO_INITIALIZED_KEY, False):
        st.session_state[UNDO_LAST_SNAPSHOT_KEY] = current_snapshot
        st.session_state[UNDO_INITIALIZED_KEY] = True
        return

    previous_snapshot = st.session_state.get(UNDO_LAST_SNAPSHOT_KEY, {})

    if current_snapshot != previous_snapshot:
        history = st.session_state.get(UNDO_HISTORY_KEY, [])

        if previous_snapshot:
            history.append(previous_snapshot)

        history = history[-UNDO_MAX_STEPS:]

        st.session_state[UNDO_HISTORY_KEY] = history
        st.session_state[UNDO_LAST_SNAPSHOT_KEY] = current_snapshot


def commit_undo_tracking():
    """
    Call once near the end of app.py, after widgets have been rendered.

    This stores newly-created default widget values, so the undo system does
    not treat initial widget creation as a user mistake.
    """
    st.session_state[UNDO_LAST_SNAPSHOT_KEY] = _snapshot_state()
    st.session_state[UNDO_INITIALIZED_KEY] = True


def restore_previous_dashboard_state() -> bool:
    history = st.session_state.get(UNDO_HISTORY_KEY, [])

    if not history:
        return False

    previous_snapshot = history.pop()
    current_snapshot = _snapshot_state()

    # Remove tracked keys that do not exist in the restored snapshot.
    for key in current_snapshot:
        if key not in previous_snapshot and key in st.session_state:
            try:
                del st.session_state[key]
            except Exception:
                pass

    # Restore previous values.
    for key, value in previous_snapshot.items():
        try:
            st.session_state[key] = deepcopy(value)
        except Exception:
            pass

    st.session_state[UNDO_HISTORY_KEY] = history
    st.session_state[UNDO_LAST_SNAPSHOT_KEY] = previous_snapshot
    st.session_state[UNDO_RESTORING_KEY] = True

    return True


def render_undo_controls(parent=None, compact: bool = False):
    container = parent if parent is not None else st.sidebar

    history_count = len(st.session_state.get(UNDO_HISTORY_KEY, []))

    with container:
        if not compact:
            st.subheader("Undo")

        col1, col2 = st.columns([1.4, 1.0])

        with col1:
            if st.button(
                "Undo last dashboard change",
                disabled=(history_count == 0),
                key="_undo_button",
                help="Restores the previous dashboard/sidebar state. Keeps up to 10 previous states.",
            ):
                restored = restore_previous_dashboard_state()
                if restored:
                    st.rerun()

        with col2:
            st.caption(f"Undo history: {history_count} / {UNDO_MAX_STEPS}")