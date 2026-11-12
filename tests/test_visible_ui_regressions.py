"""Data-loss, session epoch and live gap regressions for the visible drawn-tag workflow."""
import io
import json
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
import streamlit as st

from agents.activity_support import bool_to_intervals
from agents.symptom_support import mask_to_intervals
from agents.activity_agents import ActivityConfig
from agents.symptom_agents import SymptomConfig
from services.dashboard_service import run_activity_agent, run_symptom_agent
from services.live_gap_service import build_live_gap_plan, gap_break_positions, run_live_agents
from services.virtual_window_service import dataframe_to_track_payload
from ui import sidebar
from app import _apply_virtual_component_event, _build_virtual_window_info, _apply_temporal_activity_resolution

CTX = 'W__8.5'
TAG = dict(tag_id='stable-id', label='Expert tag', source='chart_drag',
           start='2026-01-01 06:10:00', end='2026-01-01 06:12:00')

@pytest.fixture(autouse=True)
def clear_state():
    st.session_state.clear()
    yield
    st.session_state.clear()

@pytest.mark.parametrize('builder', [bool_to_intervals, mask_to_intervals])
@pytest.mark.parametrize('duplicate', [False, True])
def test_interval_close_uses_previous_row_even_with_duplicate_times(builder, duplicate):
    ix = pd.date_range('2026-01-01', periods=5, freq='4s')
    if duplicate:
        ix = pd.DatetimeIndex([ix[0], ix[1], ix[1], ix[3], ix[4]])
    result = builder(pd.Series([True, True, False, True, False], index=ix), 'x')
    assert [(r['start'],r['end']) for r in result] == [(ix[0],ix[1]),(ix[3],ix[3])]


def test_restore_empty_is_authoritative_and_new_restore_clears_tombstones():
    st.session_state[f'tag_ledger_{CTX}'] = [TAG]
    st.session_state[f'deleted_tag_ids_{CTX}'] = ['stable-id']
    st.session_state[f'hit_result_history_{CTX}'] = [{'stale':True}]
    sidebar.apply_loaded_dashboard_state_early({'tag_intervals':[], 'tag_ledger':[TAG]}, CTX)
    token1 = st.session_state[f'_virtual_browser_session_token_{CTX}']
    assert st.session_state[f'tag_ledger_{CTX}'] == []
    assert st.session_state[f'hit_result_history_{CTX}'] == []
    sidebar.apply_loaded_dashboard_state_early({'tag_intervals':[TAG]}, CTX)
    assert st.session_state[f'tag_ledger_{CTX}'][0]['tag_id'] == 'stable-id'
    assert st.session_state[f'deleted_tag_ids_{CTX}'] == []
    assert st.session_state[f'_virtual_browser_session_token_{CTX}'] != token1


def test_loaded_view_is_available_before_window_and_late_restore_preserves_navigation():
    start,span = f'virtual_viewport_start_{CTX}', f'virtual_viewport_span_seconds_{CTX}'
    payload={'tag_intervals':[], 'dashboard_state':{'widget_state':{start:'2026-01-01 06:00:00',span:3600}}}
    sidebar.apply_loaded_dashboard_state_early(payload,CTX)
    frame=pd.DataFrame({'_section_in':8.5},index=pd.date_range('2026-01-01', periods=24*900+1, freq='4s'))
    window=_build_virtual_window_info(frame, CTX)
    assert window['viewport_start'] == pd.Timestamp('2026-01-01 06:00:00')
    assert window['viewport_span_seconds'] == 3600
    st.session_state[start]='2026-01-01 07:00:00'
    sidebar._apply_loaded_review_to_state(payload,CTX)
    assert st.session_state[start] == '2026-01-01 07:00:00'


def test_old_editor_event_cannot_delete_restored_tag_or_move_view():
    sidebar.apply_loaded_dashboard_state_early({'tag_intervals':[TAG]},CTX)
    before=st.session_state[f'_virtual_browser_session_token_{CTX}']
    for event in ({'event':'tag_autosave','tags':[],'deleted_tag_ids':['stable-id']},
                  {'event':'viewport_request','viewport_start':'2026-01-01 00:00:00'}):
        assert _apply_virtual_component_event(dict(event,browser_session_token='old'),context_key=CTX,
            section_start=pd.Timestamp('2026-01-01'),section_end=pd.Timestamp('2026-01-02')) is False
    assert st.session_state[f'tag_ledger_{CTX}'][0]['tag_id']=='stable-id'
    assert st.session_state[f'_virtual_browser_session_token_{CTX}']==before


class Rerun(BaseException): pass

def test_upload_same_name_different_contents_a_b_a_and_clear_reupload_once():
    current=[None]
    def uploader(*a,**kw): return current[0]
    def upload(tagset):
        f=io.BytesIO(json.dumps({'tag_intervals':tagset}).encode()); f.name='same.json'; f.file_id=str(id(f)); current[0]=f
    with patch.object(st,'file_uploader',uploader), patch.object(st,'rerun',side_effect=Rerun):
        for tags in ([TAG],[],[TAG]):
            upload(tags)
            with pytest.raises(Rerun): sidebar.render_review_loader_before_well_selector()
            assert sidebar.render_review_loader_before_well_selector()['tag_intervals']==tags
            assert sidebar.render_review_loader_before_well_selector() is None
        current[0]=None
        assert sidebar.render_review_loader_before_well_selector() is None
        upload([TAG])
        with pytest.raises(Rerun): sidebar.render_review_loader_before_well_selector()
        assert sidebar.render_review_loader_before_well_selector()['tag_intervals']==[TAG]
        # An intentional re-upload of the very same bytes is a new operation.
        upload([TAG])
        with pytest.raises(Rerun): sidebar.render_review_loader_before_well_selector()


def test_malformed_session_does_not_partially_replace_active_tags():
    st.session_state[f'tag_ledger_{CTX}']=[TAG]
    with pytest.raises(ValueError):
        sidebar._replace_saved_tag_state({'tag_intervals':[TAG], 'hit_results':{}},CTX,new_edit_session=True)
    assert st.session_state[f'tag_ledger_{CTX}']==[TAG]


def settings():
    return ({'enabled':True,'selected_activity':'Drilling','config':ActivityConfig()},
            {'enabled':True,'selected_symptom':'TRQSpike','config':SymptomConfig()})


@pytest.mark.parametrize('unit', ['s','ms','us','ns'])
def test_gap_cadence_is_independent_of_parquet_datetime_resolution(unit):
    ix=pd.date_range('2026-01-01',periods=10,freq='4s').append(
        pd.date_range('2026-01-01 01:00:00',periods=10,freq='4s')).as_unit(unit)
    a,s=settings();plan=build_live_gap_plan(ix,a,s)
    assert plan['policies']['']['cadence_seconds']==4.0
    assert plan['policies']['']['max_gap_seconds']==40.0
    assert gap_break_positions(ix,plan=plan)==[9]


def frame(index):
    n=len(index)
    return pd.DataFrame({'BD':1000+np.arange(n)*.02,'WD':1000+np.arange(n)*.02,
        'BPOS':10.,'HKL':120.,'MFI':500.,'RPMB':80.,'WOB':8.,'TRQ':5.,'_section_in':8.5},index=index)

MAP={'Bit Depth':'BD','Well Depth':'WD',**{key:key for key in ['BPOS','HKL','MFI','RPMB','WOB','TRQ']}}

def run(frame,plan=None):
    a,s=settings()
    return run_live_agents(df=frame,label_to_column=MAP,activity_ui=a,symptom_ui=s,
        run_activity=run_activity_agent,resolve_activity=_apply_temporal_activity_resolution,
        run_symptom=run_symptom_agent,gap_plan=plan)


def test_live_contiguous_pipeline_preserves_results_including_duplicates():
    ix=pd.date_range('2026-01-01',periods=800,freq='4s')
    ix=ix.insert(15,ix[15])
    df=frame(ix); a,s=settings()
    expected=_apply_temporal_activity_resolution(df.copy(),run_activity_agent(df,MAP,a))
    expected_s=run_symptom_agent(df,MAP,s,a,expected)
    actual,actual_s=run(df)
    pd.testing.assert_series_equal(expected['labels'],actual['labels'])
    pd.testing.assert_frame_equal(expected_s['features'],actual_s['features'])
    assert actual['intervals']==expected['intervals']
    assert len(actual['labels'])==len(ix)


def test_real_agents_restart_and_no_interval_crosses_gap_or_warmup():
    ix=pd.date_range('2026-01-01',periods=800,freq='4s').append(pd.date_range('2026-01-01 02:00:00',periods=800,freq='4s'))
    df=frame(ix); a,s=settings(); plan=build_live_gap_plan(ix,a,s,df['_section_in'])
    actual,actual_s=run(df,plan)
    assert gap_break_positions(ix,sections=df['_section_in'],plan=plan)==[799]
    warmup=plan['restart_warmup_samples']
    coverage=actual['prediction_coverage']
    assert len(coverage)==2 and pd.Timestamp(coverage[1]['start'])==ix[800+warmup]
    for cfg in (actual,actual_s):
        for interval in cfg['intervals']:
            assert any(pd.Timestamp(c['start'])<=interval['start']<=interval['end']<=pd.Timestamp(c['end']) for c in coverage)
    # Feature state after the gap equals an independently started segment.
    standalone_a,standalone_s=run(df.iloc[800:])
    pd.testing.assert_frame_equal(actual_s['features'].iloc[800:],standalone_s['features'])
    assert actual['labels'].iloc[800:800+warmup].isna().all()
    payload=dataframe_to_track_payload(df,track_params_real=[['TRQ']],track_param_labels=[['TRQ']],gap_plan=plan)
    assert payload['sample_count']==len(df) and payload['gap_after_indices']==[799]
    assert len(payload['tracks'][0]['curves'][0]['x'])==len(df)
    # Loaded buffer starts just before the global restart cutoff: still needs local history.
    buffered,_=run(df.iloc[800+warmup-1:],plan)
    assert pd.Timestamp(buffered['prediction_coverage'][0]['start'])==ix[800+2*warmup-1]


def test_symptom_event_crossing_warmup_is_not_a_certified_miss():
    ix=pd.date_range('2026-01-01',periods=500,freq='4s').append(pd.date_range('2026-01-01 02:00:00',periods=700,freq='4s'))
    df=frame(ix); a,s=settings();plan=build_live_gap_plan(ix,a,s,df['_section_in']);warmup=plan['restart_warmup_samples']
    def symptom(**kw):
        part=kw['df'];start=10;end=warmup+20
        return {'intervals':[{'label':'TRQSpike','start':part.index[start],'end':part.index[end]}]}
    _,result=run_live_agents(df=df,label_to_column=MAP,activity_ui=a,symptom_ui=s,
        run_activity=run_activity_agent,resolve_activity=_apply_temporal_activity_resolution,
        run_symptom=symptom,gap_plan=plan)
    assert len(result['uncertified_intervals'])==1
    assert pd.Timestamp(result['prediction_coverage'][1]['start'])==ix[500+warmup+21]
    assert len(result['intervals'])==1


def test_prediction_revision_includes_configuration_and_coverage():
    from app import _live_prediction_revision
    window={'start':'2026-01-01','end':'2026-01-02'}
    config={'selected_agent':'Drilling','agent_intervals':[], 'model_configuration':{'x':1}}
    revision=_live_prediction_revision(config,window)
    assert revision!=_live_prediction_revision(dict(config,model_configuration={'x':2}),window)
    assert revision!=_live_prediction_revision(dict(config,prediction_coverage=[]),window)


def test_actual_download_script_uses_snapshot_and_refuses_stale_or_missing_state(tmp_path):
    import re,shutil,subprocess
    if not shutil.which('node'):pytest.skip('Node required')
    st.session_state['_virtual_browser_session_token_ctx']='T'
    st.session_state['_live_prediction_revision_ctx']='R'
    base={'dashboard_context':{'selected_agent_name':'Drilling'},'tag_intervals':[TAG],
        'drawn_tag_intervals':[TAG], 'hit_results':[{'stale':True}], 'summary':{'tag_count':1,'overlap_count':1,'accepted':True}}
    with patch.object(sidebar.components,'html') as html:
        sidebar._render_dashboard_session_download_with_browser_tags(json.dumps(base),'ctx','out.json')
    script=re.search(r'<script>(.*?)</script>',html.call_args.args[0],re.S).group(1)
    test=r'''
const vm=require('vm'),assert=require('assert');let click=null,download=null;
const status={textContent:''};
const button={addEventListener:(event,fn)=>{if(event==='click')click=fn;},style:{}};
const storage=new Map();
const localStorage={getItem:k=>storage.has(k)?storage.get(k):null,setItem:(k,v)=>storage.set(k,v),length:0};
const document={getElementById:id=>id.endsWith('_btn')?button:status,body:{appendChild(){},removeChild(){}},
  createElement:()=>({click(){}})};
const ctx={window:{localStorage,sessionStorage:localStorage},document,console,JSON,Set,Map,Date,String,Array,Number,
  Blob:class{constructor(parts){download=JSON.parse(parts[0]);}},URL:{createObjectURL(){return 'x';},revokeObjectURL(){}}};
vm.createContext(ctx);vm.runInContext(SOURCE,ctx);
const key='hoda_dashboard_snapshot_ctx_T';
click();assert.equal(download,null);assert(status.textContent.includes('still syncing'));
const snapshot={schema_version:1,context_key:'ctx',browser_session_token:'T',prediction_revision:'R',
  tags:[],hit_results:[],selected_agent:'Drilling',agent_intervals:[],viewport_start:'2026-01-01 06:00:00',viewport_span_seconds:3600};
localStorage.setItem(key,JSON.stringify(snapshot));click();
assert.deepEqual(download.tag_intervals,[]);assert.deepEqual(download.hit_results,[]);
assert.equal(download.summary.overlap_count,0);assert.equal(download.summary.accepted,false);
assert.equal(download.dashboard_state.widget_state.virtual_viewport_span_seconds_ctx,3600);
download=null;snapshot.prediction_revision='old';localStorage.setItem(key,JSON.stringify(snapshot));click();
assert.equal(download,null);assert(status.textContent.includes('still syncing'));
snapshot.prediction_revision='R';snapshot.tags=[TAG];snapshot.hit_results=[{tag_id:TAG.tag_id,tag_start:TAG.start,tag_end:TAG.end,result:'Miss',percent_value:0}];
localStorage.setItem(key,JSON.stringify(snapshot));click();assert.equal(download.hit_results[0].result,'Miss');
assert.equal(download.tag_intervals[0].tag_id,TAG.tag_id);
// A current in-memory provider remains usable with disabled browser storage.
snapshot.marker_display='Small dots';snapshot.tag_mode=true;
snapshot.tags[0].edit_revision=7;
ctx.window.parent={__drillmateSnapshotProviders:{ctx_T:()=>snapshot}};
localStorage.getItem=()=>{throw new Error('storage blocked');};
download=null;click();assert.equal(download.tag_intervals.length,1);
assert.equal(download.tag_intervals[0].edit_revision,7);
assert.equal(download.dashboard_state.widget_state.marker_display_ctx,'Small dots');
assert.equal(download.dashboard_state.widget_state.virtual_tag_mode_ctx,true);
download=null;snapshot.hit_results[0].tag_end='2026-01-01 06:13:00';localStorage.setItem(key,JSON.stringify(snapshot));click();assert.equal(download,null);
'''
    result=subprocess.run(['node','-e','const SOURCE='+json.dumps(script)+';const TAG='+json.dumps(TAG)+';'+test],capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr
