"""Active UI restoration and preservation of the expert's latest edits."""
from unittest.mock import patch
import pandas as pd
import streamlit as st
import pytest
from app import _merge_virtual_tag_ledger
from app import _apply_virtual_component_event
from ui.sidebar import apply_loaded_dashboard_state_early, _session_from_browser_snapshot

CTX='W__8.5'
TAG=dict(tag_id='expert',label='Dragged Tag 1',source='chart_drag',start='2026-01-01 06:00:00',end='2026-01-01 06:30:00',revision=1)


@pytest.fixture(autouse=True)
def clean_state():
    st.session_state.clear()
    yield
    st.session_state.clear()


def test_saved_agent_thresholds_are_restored_before_widgets_and_computation():
    widget={f'act_short_window_{CTX}':12,f'act_pump_thr_{CTX}':123.0,
            f'sym_trq_window_{CTX}':75,f'sym_trq_l1_{CTX}':1.6,
            f'marker_display_{CTX}':'Small dots',f'virtual_tag_mode_{CTX}':True}
    apply_loaded_dashboard_state_early({'tag_intervals':[], 'dashboard_state':{'widget_state':widget}},CTX)
    assert {key:st.session_state.get(key) for key in widget}==widget


def test_older_resize_cannot_overwrite_newer_expert_boundaries():
    _merge_virtual_tag_ledger(CTX,[TAG])
    newest=dict(TAG,end='2026-01-01 07:00:00',revision=2)
    _merge_virtual_tag_ledger(CTX,[newest])
    result=_merge_virtual_tag_ledger(CTX,[TAG])
    assert result[0]['end']==newest['end']
    assert result[0]['revision']==2


def test_replayed_autosave_does_not_invent_new_revisions():
    _merge_virtual_tag_ledger(CTX,[TAG])
    for _ in range(3):_merge_virtual_tag_ledger(CTX,[TAG])
    assert st.session_state[f'tag_ledger_{CTX}'][0]['revision']==1


def test_explicit_edit_revision_migrates_old_inflated_ledgers():
    st.session_state[f'tag_ledger_{CTX}']=[dict(TAG,revision=99)]
    newest=dict(TAG,end='2026-01-01 07:00:00',revision=2,edit_revision=2)
    result=_merge_virtual_tag_ledger(CTX,[newest])
    assert result[0]['end']==newest['end']
    assert result[0]['edit_revision']==2
    assert _merge_virtual_tag_ledger(CTX,[dict(TAG,revision=100)])[0]['end']==newest['end']


@pytest.mark.parametrize('setting,value', [
    ('sym_trq_window',0),('act_short_window',999),('sym_trq_l1',float('nan')),
    ('sym_trq_l1','broken'),('virtual_tag_mode','false'),
    ('max_override_TRQ',0),('max_override_TRQ',-10),
    ('virtual_viewport_start','2026-01-01T00:00:00Z'),
])
def test_invalid_settings_leave_the_active_expert_tags_and_editor_untouched(setting,value):
    st.session_state[f'tag_ledger_{CTX}']=[TAG]
    st.session_state[f'_virtual_browser_session_token_{CTX}']='existing'
    with pytest.raises(ValueError):
        apply_loaded_dashboard_state_early({'tag_intervals':[], 'dashboard_state':{
            'widget_state':{f'{setting}_{CTX}':value}}},CTX)
    assert st.session_state[f'tag_ledger_{CTX}']==[TAG]
    assert st.session_state[f'_virtual_browser_session_token_{CTX}']=='existing'


def test_explicit_draft_recovery_preserves_tags_settings_and_view_and_empty_is_authoritative():
    snapshot=dict(schema_version=1,context_key=CTX,selected_well='W',selected_sections=['8.5'],
        selected_agent='TRQSpike',agent_source='Symptom agent',tags=[TAG],hit_results=[],
        viewport_start='2026-01-01 05:00:00',viewport_span_seconds=3600,
        marker_display='Small dots',tag_mode=True,session_base={'dashboard_state':{
            'widget_state':{f'sym_trq_window_{CTX}':75}}})
    payload=_session_from_browser_snapshot(snapshot)
    apply_loaded_dashboard_state_early(payload,CTX)
    assert st.session_state[f'tag_ledger_{CTX}'][0]['tag_id']=='expert'
    assert st.session_state[f'sym_trq_window_{CTX}']==75
    assert st.session_state[f'virtual_viewport_span_seconds_{CTX}']==3600
    assert st.session_state[f'marker_display_{CTX}']=='Small dots'
    empty=_session_from_browser_snapshot(dict(snapshot,tags=[],deleted_tag_ids=['expert']))
    apply_loaded_dashboard_state_early(empty,CTX)
    assert st.session_state[f'tag_ledger_{CTX}']==[]


def test_late_tag_event_cannot_undo_a_more_recent_edit():
    st.session_state[f'_virtual_browser_session_token_{CTX}']='editor'
    old=dict(event='tag_autosave',browser_session_token='editor',event_order=100,tags=[TAG])
    new=dict(old,event_order=101,tags=[dict(TAG,end='2026-01-01 07:00:00',revision=2)])
    bounds=(pd.Timestamp('2026-01-01'),pd.Timestamp('2026-01-03'))
    assert _apply_virtual_component_event(new,CTX,*bounds)
    assert not _apply_virtual_component_event(old,CTX,*bounds)
    assert st.session_state[f'tag_ledger_{CTX}'][0]['end']=='2026-01-01 07:00:00'


def test_old_manual_navigation_cannot_overwrite_a_newer_table_click():
    st.session_state[f'_virtual_browser_session_token_{CTX}']='editor'
    st.session_state[f'_agent_interval_click_order_{CTX}_editor']=200
    st.session_state[f'virtual_viewport_start_{CTX}']=pd.Timestamp('2026-01-02 05:00:00')
    event=dict(event='viewport_request',source='zoom_restore',browser_session_token='editor',
        request_order=100,viewport_start='2026-01-01 00:00:00',viewport_span_seconds=43200)
    assert not _apply_virtual_component_event(event,CTX,pd.Timestamp('2026-01-01'),pd.Timestamp('2026-01-03'))
    assert st.session_state[f'virtual_viewport_start_{CTX}']==pd.Timestamp('2026-01-02 05:00:00')


def test_zero_width_parameter_scale_is_repaired_before_the_visible_widget():
    from streamlit.testing.v1 import AppTest
    at=AppTest.from_string('''
import streamlit as st
from ui.sidebar import render_parameter_range_controls
st.session_state.setdefault('max_override_TRQ_ctx',0.0)
limits=render_parameter_range_controls(['TRQ'],'ctx')
st.session_state['test_limits']=limits
''').run()
    assert not at.exception
    assert at.session_state['test_limits']['TRQ'][1]>at.session_state['test_limits']['TRQ'][0]
    assert len(at.warning)==1
    assert at.number_input[0].min>0


def test_unavailable_well_is_rejected_before_replacing_the_active_session():
    import io,json
    from ui.sidebar import render_review_loader_before_well_selector
    saved=dict(dashboard_context=dict(selected_well='Missing',selected_sections=['8.5']),tag_intervals=[])
    uploaded=io.BytesIO(json.dumps(saved).encode());uploaded.file_id='new'
    st.session_state['locked_selected_well']='W'
    st.session_state[f'tag_ledger_{CTX}']=[TAG]
    with patch('streamlit_components.virtual_log_viewer.render_draft_recovery',return_value=None), \
         patch.object(st,'file_uploader',return_value=uploaded), patch.object(st,'rerun') as rerun:
        assert render_review_loader_before_well_selector({'W':['8.5']}) is None
        rerun.assert_not_called()
    assert st.session_state['locked_selected_well']=='W'
    assert st.session_state[f'tag_ledger_{CTX}']==[TAG]


@pytest.mark.parametrize('well,section,choice',[
    ('34-10-C47','12.25','symptom::TRQSpike'),('34-10-C47','17.5','activity::Drilling'),
    ('F-10','12.25','symptom::TRQSpike'),('F-10','17.5','activity::Drilling'),
])
def test_fresh_visible_selection_and_parameter_edits_preserve_existing_tags(well,section,choice):
    from streamlit.testing.v1 import AppTest
    at=AppTest.from_string('''
import streamlit as st
from ui.sidebar import render_well_section_selector,render_agent_picker_gate,render_track_parameter_selector
well,sections=render_well_section_selector({'34-10-C47':['12.25','17.5'],'F-10':['12.25','17.5']})
if not well or not sections:st.stop()
ctx=well+'__'+'_'.join(sections)
source,display,agent=render_agent_picker_gate(ctx)
if not agent:st.stop()
render_track_parameter_selector(['TRQ','WOB','RPMB'],ctx)
st.session_state['test_context']=ctx
st.session_state['test_agent']=agent
''').run()
    next(w for w in at.selectbox if w.label=='Select Well').set_value(well).run()
    next(w for w in at.selectbox if w.label=='Select Section').set_value(section).run()
    next(w for w in at.selectbox if w.label=='Agent shown in Track 4 data agent lane').set_value(choice).run()
    assert not at.exception
    ctx=well+'__'+section
    assert at.session_state['test_context']==ctx
    at.session_state[f'tag_ledger_{ctx}']=[TAG]
    next(w for w in at.multiselect if w.label.startswith('Track 1 parameters')).set_value(['TRQ']).run()
    assert not at.exception
    assert at.session_state[f'tag_ledger_{ctx}']==[TAG]
    assert at.session_state['test_agent']==choice.split('::')[1]
