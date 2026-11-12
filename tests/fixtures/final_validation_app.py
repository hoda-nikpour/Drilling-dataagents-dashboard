"""Streamlit integration fixture: synthetic IO, real panel and scoring engines."""
from dataclasses import replace
import json
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import streamlit as st

from agents.activity_agents import ActivityConfig
from agents.symptom_agents import SymptomConfig
from ui.final_validation_panel import render_final_validation_panel

index = pd.date_range('2026-01-01', periods=5, freq='4s')
panel_index = index
if st.session_state.get('harness_duplicates'):
    panel_index = index.insert(1, index[0])
if st.session_state.get('harness_oversized'):
    panel_index = pd.date_range('2026-01-01', periods=300001, freq='4s')
threshold = st.number_input('Harness threshold', value=100.0)
kind = st.selectbox('Harness kind', ['activity', 'symptom'])
agent = 'Drilling' if kind == 'activity' else 'TRQSpike'
source = 'Activity agent' if kind == 'activity' else 'Symptom agent'
expert = {
    'dashboard_context': {'selected_well': '34-10-C47', 'selected_sections': ['12.25'],
                          'agent_source': source,
                          'selected_activity': 'Drilling', 'selected_symptom': 'TRQSpike'},
    'tag_intervals': [{'tag_id': 'expert-1', 'start': str(index[0]), 'end': str(index[2])}],
}

def uploaded(label, **kwargs):
    key = 'harness_expert_bytes' if label == 'Saved expert session JSON' else 'harness_offline_bytes'
    value = st.session_state.get(key, json.dumps(expert).encode() if key == 'harness_expert_bytes' else None)
    return SimpleNamespace(getvalue=lambda: value) if value is not None else None

def activity(**kwargs):
    st.session_state['harness_agent_calls'] = st.session_state.get('harness_agent_calls', 0) + 1
    return {'labels': pd.Series(['Drilling', 'Drilling', 'Other', 'Other', 'Other'], index=index),
            'intervals': [{'label': 'Drilling', 'start': index[0], 'end': index[1]}]}

def symptom(**kwargs):
    return {'intervals': [{'label': 'TRQSpike', 'start': index[0], 'end': index[1]}]}

original_download = st.download_button

def download(label, **kwargs):
    if label == 'Download independent validation report':
        st.session_state['harness_downloaded_report'] = json.loads(kwargs['data'])
    return original_download(label, **kwargs)

with patch('ui.final_validation_panel.st.file_uploader', side_effect=uploaded), \
     patch('ui.final_validation_panel.st.download_button', side_effect=download), \
     patch('ui.final_validation_panel.load_sections_for_columns',
           return_value=pd.DataFrame({'X': range(5)}, index=index)), \
     patch('ui.final_validation_panel.verified_offline_unique_index',
           side_effect=lambda ix, path: ix.drop_duplicates()), \
     patch('ui.final_validation_panel.apply_cleaning_layer', side_effect=lambda df, **kw: (df, {'X': 'X'}, None)):
    render_final_validation_panel(
        well='34-10-C47', sections=('12.25',), agent_source=source,
        activity_ui={'enabled': True, 'selected_activity': 'Drilling',
                     'config': replace(ActivityConfig(), pump_on_threshold=threshold)},
        symptom_ui={'enabled': True, 'selected_symptom': 'TRQSpike', 'config': SymptomConfig()},
        full_time_index=panel_index, requested_columns=['X'], label_to_column={'X': 'X'},
        cleaning_rules={}, required_activity_labels=[], required_symptom_labels=[],
        run_activity=activity, resolve_activity=lambda **kw: kw['activity_cfg'], run_symptom=symptom,
    )
