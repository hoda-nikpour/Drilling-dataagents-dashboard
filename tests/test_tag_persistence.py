import json

import streamlit as st

from ui.sidebar import _build_export_payload, apply_loaded_dashboard_state_early


def _clear_tag_state() -> None:
    st.session_state.clear()


def test_build_export_payload_preserves_chart_drawn_tags_and_hit_results() -> None:
    _clear_tag_state()

    context_key = "ctx"
    st.session_state[f"tag_ledger_{context_key}"] = [
        {
            "tag_id": "tag_a",
            "label": "Drawn tag",
            "start": "2024-01-01 00:00:00",
            "end": "2024-01-01 00:10:00",
            "source": "chart_drag",
            "status": "active",
            "created_at": "tag_a",
            "updated_at": "2024-01-01T00:00:00Z",
            "revision": 1,
        }
    ]
    st.session_state[f"hit_result_history_{context_key}"] = [
        {
            "tag_label": "Drawn tag",
            "tag_start": "2024-01-01 00:00:00",
            "tag_end": "2024-01-01 00:10:00",
            "result": "Hit",
        }
    ]

    payload_text, _ = _build_export_payload(
        tag_intervals=[
            {
                "tag_id": "manual_1",
                "label": "Manual tag",
                "start": "2024-01-01 00:00:00",
                "end": "2024-01-01 00:05:00",
                "source": "manual",
                "status": "active",
                "created_at": "manual_1",
                "updated_at": "2024-01-01T00:00:00Z",
                "revision": 1,
            }
        ],
        agent_intervals=[],
        summary={},
        selected_well="WELL_A",
        selected_sections=("8.5",),
        context_key=context_key,
    )
    payload = json.loads(payload_text)

    assert payload["drawn_tag_intervals"][0]["tag_id"] == "tag_a"
    assert payload["tag_ledger"][0]["tag_id"] == "tag_a"
    assert payload["tag_intervals"][0]["tag_id"] == "manual_1"
    assert payload["hit_results"][0]["tag_label"] == "Drawn tag"


def test_apply_loaded_dashboard_state_early_restores_visual_tags_and_hits() -> None:
    _clear_tag_state()

    uploaded_data = {
        "drawn_tag_intervals": [
            {
                "tag_id": "tag_b",
                "label": "Restored tag",
                "start": "2024-01-02 01:00:00",
                "end": "2024-01-02 01:15:00",
                "source": "chart_drag",
                "status": "active",
                "created_at": "tag_b",
                "updated_at": "2024-01-02T01:00:00Z",
                "revision": 1,
            }
        ],
        "tag_ledger": [
            {
                "tag_id": "tag_b",
                "label": "Restored tag",
                "start": "2024-01-02 01:00:00",
                "end": "2024-01-02 01:15:00",
                "source": "chart_drag",
                "status": "active",
                "created_at": "tag_b",
                "updated_at": "2024-01-02T01:00:00Z",
                "revision": 1,
            }
        ],
        "hit_results": [
            {
                "tag_label": "Restored tag",
                "tag_start": "2024-01-02 01:00:00",
                "tag_end": "2024-01-02 01:15:00",
                "result": "Hit",
            }
        ],
        "dashboard_state": {"widget_state": {}},
    }

    apply_loaded_dashboard_state_early(uploaded_data, "ctx")

    assert st.session_state["visual_tag_intervals_ctx"][0]["tag_id"] == "tag_b"
    assert st.session_state["tag_ledger_ctx"][0]["tag_id"] == "tag_b"
    assert st.session_state["hit_result_history_ctx"][0]["tag_label"] == "Restored tag"
