"""Synthetic two-day Streamlit fixture using the production table and viewer."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
import time
import numpy as np
import pandas as pd
import streamlit as st

from app import (_ensure_fresh_virtual_session, _build_virtual_window_info,
                 _render_virtual_log_component, _render_scroll_to_chart_top_once)
from ui.layout import render_result_tables

st.set_page_config(layout='wide')
ctx = 'navigation_fixture__8.5'
_ensure_fresh_virtual_session(ctx)
if '_fixture_seeded' not in st.session_state:
    st.session_state[f'tag_ledger_{ctx}'] = [dict(
        tag_id='expert-original', source='chart_drag', label='Expert reference',
        start='2026-01-01 03:05:00', end='2026-01-01 03:08:00', status='active')]
    st.session_state['_fixture_seeded'] = True

st.button('Unrelated rerun')
long_list = st.checkbox('Long interval list')
agent = st.selectbox('Fixture agent', ['Drilling', 'TRQSpike'])
index = pd.date_range('2026-01-01', '2026-01-03', freq='4s')
intervals = [dict(label=agent, start=pd.Timestamp(start), end=pd.Timestamp(end)) for start, end in [
    ('2026-01-01 03:00:00', '2026-01-01 03:10:00'),
    ('2026-01-02 06:15:00', '2026-01-02 06:30:00'),
    ('2026-01-02 23:50:00', '2026-01-02 23:59:56'),
]]
if long_list:
    intervals = [dict(label=agent, start=start, end=start+pd.Timedelta(seconds=20))
                 for start in pd.date_range('2026-01-02',periods=120,freq='1min')]
render_result_tables(activity_cfg={'summary_df': pd.DataFrame()},
    symptom_cfg=dict(intervals=intervals, selected_agent=agent, agent_source='Activity agent' if agent=='Drilling' else 'Symptom agent'),
    activity_validation_df=pd.DataFrame(), review_df=pd.DataFrame(), context_key=ctx)
# Optional isolated-test latency models a slower buffer/model computation.
delay_ms=min(1500,max(0,int(st.query_params.get('delay_ms','0'))))
if delay_ms and st.session_state.get(f'_agent_interval_table_generation_{ctx}',0):
    time.sleep(delay_ms/1000)
window = _build_virtual_window_info(pd.DataFrame({'_section_in':8.5}, index=index), ctx)
loaded = index[(index>=window['start']) & (index<=window['end'])]
frame = pd.DataFrame({'TRQ':10+np.sin(np.arange(len(loaded))/20)}, index=loaded)
cfg = dict(selected_agent=agent, agent_source='Activity agent' if agent=='Drilling' else 'Symptom agent',
           agent_intervals=intervals, tag_intervals=[], prediction_coverage=[dict(start=window['start'],end=window['end'])])
st.markdown('<div id="chart_top_anchor_navigation_fixture__8_5"></div>',unsafe_allow_html=True)
_render_virtual_log_component(df=frame,context_key=ctx,selected_well='navigation_fixture',selected_sections=('8.5',),
    track_params_real=[['TRQ'],[],[]],track_param_labels=[['TRQ'],[],[]],agent_cfg=cfg,window_info=window,chart_height=650)
_render_scroll_to_chart_top_once(ctx)
st.code(json.dumps(dict(start=str(window['viewport_start']),span=window['viewport_span_seconds'],
    buffer_start=str(window['start']),buffer_end=str(window['end']),
    generation=st.session_state.get(f'_agent_interval_table_generation_{ctx}',0),
    pending=st.session_state.get(f'_virtual_navigation_request_{ctx}'),
    click_order=st.session_state.get(f'_agent_interval_click_order_{ctx}_'+st.session_state.get(f'_virtual_browser_session_token_{ctx}','fresh'),0),
    ledger=st.session_state.get(f'tag_ledger_{ctx}',[])),default=str),language='json')
