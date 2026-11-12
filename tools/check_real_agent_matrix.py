"""Smoke-test actual live processing on beginning/middle/end buffers of all logs.

These are execution/time-bound checks, not drilling accuracy measurements.
Original parquet files are only read through the production loader.
"""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from contextlib import redirect_stdout
from io import StringIO
import pandas as pd
import app
from agents.activity_agents import ActivityConfig,REQUIRED_ACTIVITY_INPUTS
from agents.symptom_agents import SymptomConfig,REQUIRED_SYMPTOM_INPUTS
from services.live_gap_service import build_live_gap_plan,run_live_agents

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/core_ui_reliability_2026-11-11'
ACTIVITIES=['Drilling','Reaming','TrippingIn','TrippingOut','Conditioning','Circulating','MakingConnection']
SYMPTOMS=['OpenHoleLength','TRQSpike','TRQErratic','PSpike','OverPull','TookWeight']


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    results=[]
    for well,section in [('34-10-C47','12.25'),('34-10-C47','17.5'),('F-10','12.25'),('F-10','17.5')]:
        sections=(section,)
        times=app.load_section_time_index(well,sections)
        index=times.index
        discovered=app.get_available_numeric_columns(well,sections)
        aliases=app.build_context_parameter_aliases(selected_well=well,selected_sections=sections,
            global_aliases=app.GLOBAL_PARAMETER_ALIASES,well_aliases=app.WELL_PARAMETER_ALIASES,
            section_aliases=app.SECTION_PARAMETER_ALIASES)
        mapping=app.build_label_to_column_map(discovered,aliases)
        act_required=[x for x in REQUIRED_ACTIVITY_INPUTS if x in mapping]
        sym_required=[x for x in REQUIRED_SYMPTOM_INPUTS if x in mapping]
        columns=app.build_requested_columns([],act_required,sym_required,mapping)
        rules=app.build_context_cleaning_rules(selected_well=well,selected_sections=sections,
            global_rules=app.CLEANING_RULES,well_rules=app.WELL_CLEANING_RULES,
            section_rules=app.SECTION_CLEANING_RULES)
        activity_ui=dict(enabled=True,selected_activity='Drilling',config=ActivityConfig())
        symptom_ui=dict(enabled=True,selected_symptom='TRQSpike',config=SymptomConfig())
        plan=build_live_gap_plan(index,activity_ui,symptom_ui,times.get('_section_in'))
        for position,row in [('beginning',0),('middle',len(index)//2),('end',len(index)-1)]:
            start=max(index[0],min(index[row]-pd.Timedelta(hours=8),index[-1]-pd.Timedelta(hours=16)))
            end=min(index[-1],start+pd.Timedelta(hours=16))
            frame=app.load_sections_for_columns(well,sections,tuple(columns),time_start=start,time_end=end)
            assert not frame.empty,(well,section,position)
            with redirect_stdout(StringIO()):
                cleaned,clean_map,_=app.apply_cleaning_layer(df=frame,label_to_column=mapping,
                    cleaning_rules=rules,required_activity_labels=act_required,required_symptom_labels=sym_required)
            output={}
            for symptom in SYMPTOMS:
                activity,symptom_result=run_live_agents(df=cleaned,label_to_column=clean_map,
                    activity_ui=activity_ui,symptom_ui=dict(symptom_ui,selected_symptom=symptom),
                    run_activity=app.run_activity_agent,resolve_activity=app._apply_temporal_activity_resolution,
                    run_symptom=app.run_symptom_agent,gap_plan=plan)
                output[symptom]=symptom_result['intervals']
            for name in ACTIVITIES:
                output[name]=[v for v in activity['intervals'] if v['label']==name]
            checks=[]
            for name,intervals in output.items():
                previous=None
                for value in intervals:
                    left,right=pd.Timestamp(value['start']),pd.Timestamp(value['end'])
                    assert frame.index[0]<=left<=right<=frame.index[-1],(well,section,name,value)
                    assert previous is None or left>=previous,(well,section,name,'unsorted')
                    previous=left
                checks.append(dict(agent=name,passed=True,intervals=len(intervals),
                    single_sample_intervals=sum(pd.Timestamp(v['start'])==pd.Timestamp(v['end']) for v in intervals)))
            result=dict(well=well,section=section,buffer=position,start=str(frame.index[0]),end=str(frame.index[-1]),
                rows=len(frame),missing_inputs=[x for x in ['Casing Depth','Mud Motor On'] if x not in mapping],
                checks=checks)
            results.append(result)
            (OUT/'real-agent-matrix.json').write_text(json.dumps(dict(passed=True,complete=len(results)==12,
                scope='execution and timestamp invariants on 16-hour buffers; not scientific accuracy',results=results),indent=2))
            print(well,section,position,len(frame),'rows: all 13 agents passed',flush=True)


if __name__=='__main__':main()
