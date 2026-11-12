"""Run the complete app in an isolated session with C47/17.5/TRQSpike selected."""
from pathlib import Path
import sys
import json
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import streamlit as st
import app as dashboard
import ui.layout as layout
from app import main

well = st.query_params.get('well', '34-10-C47')
section = st.query_params.get('section', '17.5')
agent = st.query_params.get('agent', 'TRQSpike')
activity_names = {'Drilling','Reaming','TrippingIn','TrippingOut','Conditioning','Circulating','MakingConnection'}
ctx = f'{well}__{section}'
if not st.session_state.get('_real_log_fixture_initialized'):
    st.session_state.update({
        'locked_selected_well': well, 'well_choice_locked': True,
        f'locked_selected_sections_{well}': [section], f'section_choice_locked_{well}': True,
        f'locked_selected_agent_lane_{ctx}': ('activity::' if agent in activity_names else 'symptom::')+agent,
        f'track_params_1_{ctx}': ['TRQ'], f'track_params_2_{ctx}': ['RPMB'],
        f'track_params_3_{ctx}': ['WOB'], '_real_log_fixture_initialized': True,
    })
original_render = getattr(dashboard.render_result_tables, '_fixture_original', dashboard.render_result_tables)
def observed_render(*args, **kwargs):
    rows = kwargs.get('symptom_cfg', {}).get('intervals', [])
    if rows:
        st.session_state['_fixture_intervals'] = [dict(row) for row in rows]
    return original_render(*args, **kwargs)
observed_render._fixture_original = original_render
dashboard.render_result_tables = observed_render

original_queue = getattr(layout._apply_agent_interval_click, '_fixture_original', layout._apply_agent_interval_click)
def observed_queue(value, starts, context, revision):
    if value:
        st.session_state['_fixture_clicked_selection'] = dict(value)
    return original_queue(value, starts, context, revision)
observed_queue._fixture_original = original_queue
layout._apply_agent_interval_click = observed_queue
main()
loaded = st.session_state.get('agent_validation_df')
st.code(json.dumps(dict(viewport=str(st.session_state.get(f'virtual_viewport_start_{ctx}')),
    section_start=st.session_state.get(f'_section_time_start_{ctx}'),
    section_end=st.session_state.get(f'_section_time_end_{ctx}'),
    span=st.session_state.get(f'virtual_viewport_span_seconds_{ctx}'),
    pending=st.session_state.get(f'_virtual_navigation_request_{ctx}'),
    intervals=st.session_state.get('_fixture_intervals', []),
    clicked_selection=st.session_state.get('_fixture_clicked_selection'),
    generation=st.session_state.get(f'_agent_interval_table_generation_{ctx}',0),
    loaded_start=str(loaded.index.min()) if loaded is not None else None,
    loaded_end=str(loaded.index.max()) if loaded is not None else None),default=str),language='json')
