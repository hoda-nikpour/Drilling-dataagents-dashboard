"""Isolated synthetic logs with production controls, save, upload and viewer."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dataclasses import asdict
import json
import numpy as np
import pandas as pd
import streamlit as st
from app import (_ensure_fresh_virtual_session,_build_virtual_window_info,_render_virtual_log_component,
                 _active_virtual_tag_ledger,_live_prediction_revision)
from services.live_gap_service import build_live_gap_plan
from ui.sidebar import (render_review_loader_before_well_selector,render_well_section_selector,
    apply_loaded_dashboard_state_early,render_agent_picker_gate,render_data_agent_lane_and_settings,
    render_track_parameter_selector,render_parameter_range_controls,render_agent_review_outputs)
from ui.layout import render_result_tables

st.set_page_config(layout='wide')
uploaded=render_review_loader_before_well_selector({'W':['8.5'],'Other':['8.5']})
st.session_state.setdefault('locked_selected_well','W')
st.session_state.setdefault('well_choice_locked',True)
st.session_state.setdefault('locked_selected_sections_W',['8.5'])
st.session_state.setdefault('section_choice_locked_W',True)
well,sections=render_well_section_selector({'W':['8.5'],'Other':['8.5']})
if not well or not sections:st.stop()
ctx=well+'__'+'_'.join(sections)
if uploaded is not None:
    apply_loaded_dashboard_state_early(uploaded,ctx)
    st.session_state[f'_loaded_dashboard_active_{ctx}']=True
_ensure_fresh_virtual_session(ctx,loaded_dashboard_active=st.session_state.get(f'_loaded_dashboard_active_{ctx}',False))
st.session_state.setdefault(f'locked_selected_agent_lane_{ctx}','symptom::TRQSpike')
source,display,agent=render_agent_picker_gate(ctx)
if not agent:st.stop()
controls=render_data_agent_lane_and_settings(ctx,source,agent)

st.session_state.setdefault(f'track_params_1_{ctx}',['TRQ'])
st.session_state.setdefault(f'track_params_2_{ctx}',['RPMB'])
st.session_state.setdefault(f'track_params_3_{ctx}',['WOB'])
tracks=render_track_parameter_selector(['TRQ','RPMB','WOB'],ctx)
ranges=render_parameter_range_controls(list(dict.fromkeys(sum(tracks,[]))),ctx)
with st.sidebar:
    curve_source=st.radio('Curve Source',['Cleaned values','Raw values'],key=f'curve_source_{ctx}')

index=pd.date_range('2026-01-01','2026-01-03',freq='4s')
index=index[~((index>'2026-01-01 09:00:00') & (index<'2026-01-01 09:30:00'))]
st.session_state[f'_section_time_start_{ctx}']=str(index[0])
st.session_state[f'_section_time_end_{ctx}']=str(index[-1])
window=_build_virtual_window_info(pd.DataFrame({'_section_in':8.5},index=index),ctx)
loaded=index[(index>=window['start']) & (index<=window['end'])]
frame=pd.DataFrame({'TRQ':0.0,'RPMB':60.0,'WOB':8.0},index=loaded)
if pd.Timestamp('2026-01-01 06:04:00') in frame.index:frame.loc['2026-01-01 06:04:00','TRQ']=100.0
if pd.Timestamp('2026-01-01 07:00:00') in frame.index:frame.loc['2026-01-01 07:00:00','TRQ']=np.nan
plan=build_live_gap_plan(index,controls['activity_ui'],controls['symptom_ui'])
intervals=[dict(label=agent,start=s,end=e) for s,e in [
    ('2026-01-01 06:00:00','2026-01-01 06:30:00'),
    ('2026-01-02 06:15:00','2026-01-02 06:30:00'),
    ('2026-01-02 12:00:00','2026-01-02 12:00:00')]]
tags=_active_virtual_tag_ledger(ctx)
summary=dict(tag_count=len(tags),agent_count=len(intervals),overlap_count=0,score_percent=0.0,
             acceptance_threshold_percent=95,accepted=False,tag_status_rows=[])
config=controls['symptom_ui']['config'] if source=='Symptom agent' else controls['activity_ui']['config']
cfg=dict(selected_agent=agent,agent_source=source,tag_intervals=tags,agent_intervals=intervals,
    summary=summary,show_agent_intervals=True,
    prediction_coverage=[dict(start='2026-01-01',end='2026-01-01 09:00:00'),
                         dict(start='2026-01-01 09:30:00',end='2026-01-03')],
    model_configuration=asdict(config))
st.session_state[f'_live_gap_plan_{ctx}']=plan
render_result_tables({'summary_df':pd.DataFrame()},dict(intervals=intervals,selected_agent=agent,
    agent_source=source),pd.DataFrame(),pd.DataFrame(),context_key=ctx)
st.session_state[f'_live_prediction_revision_{ctx}']=_live_prediction_revision(cfg,window)
render_agent_review_outputs(cfg,ctx,selected_well=well,selected_sections=sections)
_render_virtual_log_component(df=frame,context_key=ctx,selected_well=well,selected_sections=sections,
    track_params_real=tracks,track_param_labels=tracks,agent_cfg=cfg,window_info=window,
    chart_height=900,parameter_ranges=ranges)
st.code(json.dumps(dict(context=ctx,token=st.session_state.get(f'_virtual_browser_session_token_{ctx}'),
    ledger=st.session_state.get(f'tag_ledger_{ctx}',[]),view=str(window['viewport_start']),
    span=window['viewport_span_seconds'],buffer_start=str(window['start']),buffer_end=str(window['end']),
    config=asdict(config),curve_source=curve_source,
    marker=st.session_state.get(f'marker_display_{ctx}')),default=str),language='json')
