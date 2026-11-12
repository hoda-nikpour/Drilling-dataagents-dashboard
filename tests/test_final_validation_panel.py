"""Exercise the actual Streamlit widget rerun lifecycle, not a mock renderer."""
import json
from pathlib import Path

import pytest
import pandas as pd
from streamlit.testing.v1 import AppTest

FIXTURE = Path(__file__).parent / 'fixtures' / 'final_validation_app.py'

def widget(at, kind, label):
    return next(item for item in getattr(at, kind) if item.label == label)

def ready(kind='activity'):
    at = AppTest.from_file(str(FIXTURE), default_timeout=20).run()
    if kind != 'activity':
        widget(at, 'selectbox', 'Harness kind').set_value(kind).run()
    widget(at, 'text_area', 'Fully reviewed periods (JSON list of start/end pairs)').set_value(
        '[{"start":"2026-01-01 00:00:00","end":"2026-01-01 00:00:20"}]')
    widget(at, 'text_input', 'Fixed UTC offset of log AND saved-tag timestamps').set_value('+00:00')
    widget(at, 'number_input', 'Verified sample cadence (seconds)').set_value(4.0)
    widget(at, 'number_input', 'Largest permitted gap between samples (seconds)').set_value(4.0)
    for item in at.checkbox:
        if item.label.startswith(('Confirmed:', 'For this activity:')):
            item.check()
    if kind == 'symptom':
        widget(at, 'number_input', 'Agreed minimum event IoU (0–1)').set_value(0.5)
    return at.run()

def generate(at):
    return widget(at, 'button', 'Generate independent validation report').click().run()

def report(at):
    # Inspect the actual JSON supplied to Streamlit's real download widget.
    return at.session_state['harness_downloaded_report']

def test_report_survives_rerun_without_recalculating():
    at = generate(ready())
    assert not at.exception
    assert len(at.get('download_button')) == 1
    assert at.session_state['harness_agent_calls'] == 1
    at.run()
    assert len(at.get('download_button')) == 1
    assert at.session_state['harness_agent_calls'] == 1

@pytest.mark.parametrize('kind', ['activity', 'symptom'])
def test_downloadable_report_contains_exact_reproducible_inputs(kind):
    at = generate(ready(kind))
    assert not at.exception
    assert len(at.success) == 1
    value = report(at)
    payload = value['validation_input']
    assert payload['reviewed_intervals'][0]['end'] == '2026-01-01T00:00:20+00:00'
    assert payload['prediction_coverage'] == payload['reviewed_intervals']
    if kind == 'activity':
        assert value['validation_report']['accuracy'] == 1.0
        assert len(payload['expert_activities']) == 2
        from drillmate_validation.activities import evaluate_activities
        expected = dict(value['validation_report'])
        expected.pop('interpretation')
        assert evaluate_activities(payload) == expected
    else:
        assert value['validation_report']['event_counts'] == {'TP': 1, 'FP': 0, 'FN': 0, 'FP_lower_bound': None}
        assert payload['expert_tags'][0]['id'] == 'expert-1'
        from drillmate_validation.events import evaluate_events
        assert evaluate_events(payload) == value['validation_report']

def test_changed_settings_hide_previous_report():
    at = generate(ready())
    widget(at, 'number_input', 'Harness threshold').set_value(200.0).run()
    assert not at.get('download_button')
    assert not any(key.startswith('_independent_validation_report_') for key in at.session_state.filtered_state)

def test_online_cannot_certify_arbitrarily_large_gap():
    at = ready()
    widget(at, 'number_input', 'Largest permitted gap between samples (seconds)').set_value(914.0)
    generate(at)
    assert not at.success
    assert any('ten' in message.value.lower() for message in at.error)

def test_changed_threshold_invalidates_prepared_offline_manifest():
    at = ready()
    widget(at, 'checkbox', 'Use offline full-section predictions (large sections)').check().run()
    widget(at, 'button', 'Prepare offline prediction job manifest').click().run()
    assert len(at.get('download_button')) == 1
    widget(at, 'number_input', 'Harness threshold').set_value(200.0).run()
    assert not at.get('download_button')
    assert any('settings' in message.value.lower() for message in at.warning)

def test_invalid_expert_session_never_accepts_report():
    at = ready()
    at.session_state['harness_expert_bytes'] = json.dumps({'dashboard_context': {}}).encode()
    generate(at)
    assert not at.success
    assert not at.get('download_button')
    assert len(at.error) == 1

def test_large_online_section_keeps_memory_guard():
    at = ready()
    at.session_state['harness_oversized'] = True
    generate(at)
    assert not at.success
    assert any('safety guard' in message.value for message in at.error)
    assert 'harness_agent_calls' not in at.session_state

def test_offline_upload_reports_canonical_and_raw_sample_counts():
    from drillmate_validation.offline_prediction_exchange import make_prediction_file
    from services.offline_gap_segments import split_at_gaps
    at = ready()
    at.session_state['harness_duplicates'] = True
    widget(at, 'checkbox', 'Use offline full-section predictions (large sections)').check().run()
    widget(at, 'button', 'Prepare offline prediction job manifest').click().run()
    job = at.session_state['offline_validation_job']
    index = pd.date_range('2026-01-01', periods=5, freq='4s')
    _, coverage, segments = split_at_gaps(index, cadence_seconds=4, max_gap_seconds=4,
        log_utc_offset='+00:00', restart_warmup_samples=job['gap_restart_warmup_samples'])
    predictions = [{'id':'offline-1', 'agent':'Drilling',
                    'start':'2026-01-01T00:00:00+00:00', 'end':'2026-01-01T00:00:08+00:00'}]
    file = make_prediction_file(job, predictions, coverage, 5, segments=segments)
    at.session_state['harness_offline_bytes'] = json.dumps(file).encode()
    generate(at)
    assert not at.exception
    value = report(at)
    assert value['validation_report']['accuracy'] == 1.0
    assert value['provenance']['full_section_sample_count'] == 5
    assert value['provenance']['raw_section_sample_count'] == 6
    assert 'harness_agent_calls' not in at.session_state  # verification uses the upload
    file['predictions'][0]['end'] = '2026-01-01T00:00:12+00:00'
    at.session_state['harness_offline_bytes'] = json.dumps(file).encode()
    generate(at)
    assert not any(key.startswith('_independent_validation_report_') for key in at.session_state.filtered_state)
    assert any('modified/corrupted' in message.value for message in at.error)

def test_boundary_partial_report_is_a_warning_without_definitive_precision():
    at = ready('symptom')
    expert = {'dashboard_context': {'selected_well':'34-10-C47', 'selected_sections':['12.25'],
              'agent_source':'Symptom agent', 'selected_symptom':'TRQSpike'}, 'tag_intervals':[]}
    at.session_state['harness_expert_bytes'] = json.dumps(expert).encode()
    widget(at, 'text_area', 'Fully reviewed periods (JSON list of start/end pairs)').set_value(
        '[{"start":"2026-01-01 00:00:00","end":"2026-01-01 00:00:04"}]')
    generate(at)
    assert not at.success
    assert any('Partial evaluation' in message.value for message in at.warning)
    result = report(at)['validation_report']
    assert result['status'] == 'partial_boundary_predictions_review_required'
    assert result['metrics']['precision'] is None
    assert result['event_counts']['FP'] is None
