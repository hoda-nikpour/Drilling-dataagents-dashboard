import unittest
from drillmate_validation.dashboard_adapter import session_expert_tags, reviewed_windows, binary_activity_timelines
from drillmate_validation.events import ValidationError
from drillmate_validation.activities import evaluate_activities

CTX={'selected_well':'W','selected_sections':['12.25'],'agent_source':'Symptom agent','selected_symptom':'TRQSpike'}
start='2026-01-01T00:00:00+00:00'
end='2026-01-01T00:01:00+00:00'

def iv(s,e,ident='e'):
    return {'id':ident,'start':s,'end':e}

class AdapterTests(unittest.TestCase):
    def test_canonical_only_and_ids(self):
        item={'tag_id':'stable','start':start,'end':end,'label':'Dragged Tag 1'}
        session={'dashboard_context':CTX,'tag_intervals':[item],'tag_ledger':[item], 'drawn_tag_intervals':[item]}
        got=session_expert_tags(session,well='W',sections=['12.25'],agent='TRQSpike',agent_kind='symptom',log_utc_offset='+00:00')
        self.assertEqual([x['id'] for x in got],['stable'])

    def test_mismatched_context_fail(self):
        with self.assertRaises(ValidationError):
            session_expert_tags({'dashboard_context':CTX,'tag_intervals':[]},well='B',sections=['12.25'],agent='TRQSpike',agent_kind='symptom',log_utc_offset='+00:00')

    def test_empty_tags_valid_when_review_complete(self):
        obj={'dashboard_context':CTX,'tag_intervals':[]}
        self.assertEqual(session_expert_tags(obj,well='W',sections=['12.25'],agent='TRQSpike',agent_kind='symptom',log_utc_offset='+00:00'),[])

    def test_activity_binary_complete(self):
        windows=[iv(start,end)]
        mid='2026-01-01T00:00:30+00:00'
        expert, pred=binary_activity_timelines([iv(start,mid)],[iv(start,mid)],windows,agent='Drilling')
        result=evaluate_activities({'schema_version':1,'agent_kind':'activity','well':'W','section':'12.25',
           'reviewed_intervals':windows, 'prediction_coverage':windows,'prediction_generation':'continuous',
           'predictions_complete':True,'activity_labels':['Drilling','NotSelected'],
           'expert_activities':expert,'predicted_activities':pred})
        self.assertEqual(result['accuracy'],1.0)

    def test_point_activity_prediction_uses_explicit_cadence(self):
        windows=[iv(start,end)]
        point={'start':start,'end':start}
        with self.assertRaises(ValidationError):
            binary_activity_timelines([], [point], windows, agent='Drilling')
        expert, prediction = binary_activity_timelines([], [point], windows,
            agent='Drilling', sample_cadence_seconds=1.0)
        self.assertEqual(prediction[0]['activity'],'Drilling')

    def test_overlap_expert_activities_fails(self):
        with self.assertRaises(ValidationError):
            binary_activity_timelines([iv(start,end,'1'),iv(start,end,'2')],[],[iv(start,end)],agent='Drilling')

if __name__ == '__main__': unittest.main()
