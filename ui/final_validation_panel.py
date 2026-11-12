"""Opt-in final-validation panel. Does not change live Hit Results or saves."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
import hashlib
import json
from pathlib import Path

import streamlit as st

from data_access.data_loader import load_sections_for_columns
from services.data_cleaning import apply_cleaning_layer
from drillmate_validation.events import ValidationError, evaluate_events, RULE_VERSION
from drillmate_validation.activities import evaluate_activities
from drillmate_validation.offline_prediction_exchange import (
    make_job, verify_prediction_file, section_path, clean_ui, source_fingerprint, sha256_file,
)
from services.offline_duplicate_rows import verified_offline_unique_index
from drillmate_validation.smoke_test import run_builtin_validation_selftest
from drillmate_validation.dashboard_adapter import (
    session_expert_tags, reviewed_windows, binary_activity_timelines,
)
from services.validation_continuous import (
    MAX_VALIDATION_ROWS, assert_full_section_loaded,
    assert_unbroken_prediction_state, calculate_continuous_predictions,
    continuous_prediction_coverage,
    normalize_predictions,
)


def _report_input_signature(fields, *, full_time_index, session_file, offline_file):
    """Invalidate a displayed result whenever its inputs, code or data change."""
    root = Path(__file__).resolve().parents[1]
    identity = dict(fields, software_sha256=source_fingerprint(root))
    if len(fields['sections']) == 1:
        data_file = root / 'data' / f'{fields["well"]}_{str(fields["sections"][0]).replace(".", "_")}in.parquet'
        if data_file.is_file():
            stat = data_file.stat()
            identity['data_file_stat'] = [stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]
    serial = json.dumps(identity, sort_keys=True, allow_nan=False,
                        default=lambda value: asdict(value) if is_dataclass(value) else str(value))
    hasher = hashlib.sha256(serial.encode())
    hasher.update(full_time_index.asi8.tobytes())
    hasher.update(str(full_time_index.tz).encode())
    # Hash each upload separately so file boundaries cannot be confused.
    for uploaded in (session_file, offline_file):
        hasher.update(hashlib.sha256(uploaded.getvalue()).digest() if uploaded is not None else b'missing')
    return hasher.hexdigest()


def render_final_validation_panel(*, well, sections, agent_source, activity_ui, symptom_ui,
                                  full_time_index, requested_columns, label_to_column,
                                  cleaning_rules, required_activity_labels,
                                  required_symptom_labels, run_activity,
                                  resolve_activity, run_symptom):
    """Optional, deliberate full-section run using same CURRENT agent controls.

    Requires an exported session snapshot because browser-edited tags may be
    newer than the Python-side Streamlit state during a live rerender.
    """
    with st.sidebar.expander('Final validation — independent (opt-in)', expanded=False):
        st.caption('This is NOT the live Hit/Miss table. No existing tags, settings or exports are changed.')
        # Read-only backend smoke test. Does not require a well, session or agent selection.
        # The result NEVER represents real-well validation.
        if st.button('Run built-in engine self-test (synthetic data)', key='online_engine_selftest'):
            try:
                example_result = run_builtin_validation_selftest()
                st.success('Both production validation engines calculated the expected synthetic results.')
                st.json(example_result)
            except Exception as exc:
                st.error('Online validation-engine self-test failed. No real-well result was calculated.')
                st.exception(exc)
        kind = 'symptom' if agent_source == 'Symptom agent' else 'activity' if agent_source == 'Activity agent' else None
        agent = (symptom_ui.get('selected_symptom') if kind == 'symptom'
                 else activity_ui.get('selected_activity') if kind == 'activity' else '')
        if not kind or not agent or agent == 'All activities':
            st.info('Select a single symptom or activity agent first.')
            return
        session_file = st.file_uploader('Saved expert session JSON', type=['json'],
                                        key=f'final_validation_session_{well}_{"_".join(map(str,sections))}')
        # Optional large-section exchange: only prediction data is uploaded;
        # existing chart/session state and in-app prediction path stay intact.
        offline_mode = st.checkbox('Use offline full-section predictions (large sections)', value=False,
            help='Generate predictions locally using an exact data/configuration manifest. This does not change tagging.')
        offline_file = None
        if offline_mode:
            offline_file = st.file_uploader('Offline prediction JSON (from local command)',
                type=['json'], key=f'offline_predictions_{well}_{"_".join(map(str,sections))}')
            st.caption('After confirming the clock/cadence fields, prepare a job manifest below, '
                       'run it locally, and upload the result here. No synthetic data is used.')
            st.warning('Gap restarts exclude an agent-configuration-based warm-up from validation coverage. Reviewed periods must not include gaps or warm-up. Unknown UTC offset must be confirmed before a definitive report.')
        reviewed_text = st.text_area('Fully reviewed periods (JSON list of start/end pairs)',
                                     value='[]', height=95,
                                     help='Tommy must explicitly confirm every moment in these periods was reviewed, including no-event intervals.')
        log_offset = st.text_input('Fixed UTC offset of log AND saved-tag timestamps', value='',
                                   placeholder='+00:00', help='Required; do not assume browser timezone and log timezone match.')
        cadence = st.number_input('Verified sample cadence (seconds)', min_value=0.0,
                                  value=0.0, step=1.0)
        max_gap = st.number_input('Largest permitted gap between samples (seconds)',
                                  min_value=0.0, value=0.0, step=1.0)
        min_iou = None
        min_overlap = None
        if kind == 'symptom':
            min_iou = st.number_input('Agreed minimum event IoU (0–1)', min_value=0.0,
                                      max_value=1.0, value=0.0, step=0.05)
            min_overlap = st.number_input('Minimum overlapping seconds', min_value=0.0,
                                          value=0.0, step=1.0)
        st.caption(f'Conservative in-app memory guard: {MAX_VALIDATION_ROWS:,} samples per full section.')
        acknowledged = st.checkbox('Confirmed: full reviewed periods, timezone, cadence, gap policy and current agent settings are correct')
        activity_exhaustive = (kind != 'activity' or st.checkbox(
            'For this activity: confirmed ALL occurrences were tagged in the reviewed intervals; other time really means NotSelected'))
        if offline_mode and st.button('Prepare offline prediction job manifest'):
            try:
                if len(sections) != 1:
                    raise ValidationError('Only one section can be evaluated at a time')
                root = Path(__file__).resolve().parents[1]
                canonical_index = verified_offline_unique_index(full_time_index,
                    section_path(str(well), str(sections[0]), data_dir=root / 'data'))
                job = make_job(root=root,
                    well=str(well), section=str(sections[0]), agent=str(agent), agent_kind=kind,
                    full_sample_count=len(canonical_index), log_utc_offset=log_offset,
                    cadence_seconds=float(cadence), max_gap_seconds=float(max_gap),
                    activity_ui=activity_ui, symptom_ui=symptom_ui,
                    requested_columns=list(requested_columns),
                    label_to_column=label_to_column, cleaning_rules=cleaning_rules,
                    required_activity_labels=list(required_activity_labels),
                    required_symptom_labels=list(required_symptom_labels))
                st.session_state['offline_validation_job'] = job
            except Exception as exc:
                st.session_state.pop('offline_validation_job', None)
                st.error(f'Cannot prepare offline job: {exc}')
        if offline_mode and isinstance(st.session_state.get('offline_validation_job'), dict):
            saved_job = st.session_state['offline_validation_job']
            current_settings = {
                'activity_ui': clean_ui(activity_ui, 'activity'),
                'symptom_ui': clean_ui(symptom_ui, 'symptom'),
                'requested_columns': list(requested_columns), 'label_to_column': label_to_column,
                'cleaning_rules': cleaning_rules,
                'required_activity_labels': list(required_activity_labels),
                'required_symptom_labels': list(required_symptom_labels),
                'software_sha256': source_fingerprint(Path(__file__).resolve().parents[1]),
            }
            if (len(sections) != 1 or saved_job.get('well') != str(well)
                    or saved_job.get('section') != str(sections[0])):
                st.warning('The prepared job belongs to another well/section. Prepare a new job.')
            elif (saved_job.get('agent') != str(agent) or saved_job.get('agent_kind') != kind
                    or saved_job.get('log_utc_offset') != log_offset
                    or saved_job.get('cadence_seconds') != float(cadence)
                    or saved_job.get('max_gap_seconds') != float(max_gap)
                    or any(saved_job.get(key) != value for key, value in current_settings.items())):
                st.warning('Agent, processing or clock settings changed. Prepare a new job.')
            else:
                st.download_button('Download offline prediction job JSON',
                    data=json.dumps(saved_job, indent=2),
                    file_name='drillmate_offline_job.json', mime='application/json')
                st.code('python3 tools/generate_full_section_predictions.py '
                        '--job ~/Downloads/drillmate_offline_job.json '
                        '--output ~/Downloads/drillmate_offline_predictions.json', language='bash')
        generate_report = st.button('Generate independent validation report', disabled=not (acknowledged and activity_exhaustive))
        report_key = f'_independent_validation_report_{well}_{"_".join(map(str, sections))}'
        signature = _report_input_signature({
            'well': str(well), 'sections': list(sections), 'agent': str(agent), 'kind': kind,
            'activity_ui': activity_ui, 'symptom_ui': symptom_ui,
            'requested_columns': list(requested_columns), 'label_to_column': label_to_column,
            'cleaning_rules': cleaning_rules, 'required_activity_labels': list(required_activity_labels),
            'required_symptom_labels': list(required_symptom_labels),
            'reviewed_text': reviewed_text, 'log_offset': log_offset, 'cadence': cadence,
            'max_gap': max_gap, 'min_iou': min_iou, 'min_overlap': min_overlap,
            'offline_mode': offline_mode, 'acknowledged': acknowledged,
            'activity_exhaustive': activity_exhaustive,
        }, full_time_index=full_time_index, session_file=session_file, offline_file=offline_file)
        if st.session_state.get(report_key, {}).get('signature') != signature or generate_report:
            st.session_state.pop(report_key, None)
        if generate_report:
            try:
                if not session_file:
                    raise ValidationError('Upload the expert session JSON saved after final tag edits')
                if not log_offset or cadence <= 0 or max_gap < cadence:
                    raise ValidationError('Specify verified timezone offset and 0 < sample cadence <= maximum gap')
                if max_gap > 10 * cadence:
                    raise ValidationError('Verified gap must be between one and ten sample cadences; a larger gap could hide missing data')
                if kind == 'symptom' and not (min_iou and 0 < min_iou <= 1):
                    raise ValidationError('Select a positive IoU threshold approved for this symptom')
                if len(sections) != 1:
                    raise ValidationError('Final validation currently supports one section at a time; section-boundary state handling is not yet verified')
                if (not offline_mode) and len(full_time_index) > MAX_VALIDATION_ROWS:
                    raise ValidationError(f'Full section has {len(full_time_index):,} samples: exceeds {MAX_VALIDATION_ROWS:,} safety guard; run offline with sufficient RAM')
                saved = json.loads(session_file.getvalue().decode('utf-8'))
                review = reviewed_windows(json.loads(reviewed_text), log_offset)
                experts = session_expert_tags(saved, well=str(well), sections=[str(x) for x in sections],
                                              agent=str(agent), agent_kind=kind, log_utc_offset=log_offset)
                if offline_mode:
                    if not offline_file:
                        raise ValidationError('Upload offline predictions generated locally using this dashboard job')
                    root = Path(__file__).resolve().parents[1]
                    canonical_index = verified_offline_unique_index(full_time_index,
                        section_path(str(well), str(sections[0]), data_dir=root / 'data'))
                    expected_job = make_job(root=root,
                        well=str(well), section=str(sections[0]), agent=str(agent), agent_kind=kind,
                        full_sample_count=len(canonical_index), log_utc_offset=log_offset,
                        cadence_seconds=float(cadence), max_gap_seconds=float(max_gap),
                        activity_ui=activity_ui, symptom_ui=symptom_ui,
                        requested_columns=list(requested_columns),
                        label_to_column=label_to_column, cleaning_rules=cleaning_rules,
                        required_activity_labels=list(required_activity_labels),
                        required_symptom_labels=list(required_symptom_labels))
                    uploaded = json.loads(offline_file.getvalue().decode('utf-8'))
                    predictions, coverage = verify_prediction_file(uploaded,
                        expected_job=expected_job, full_time_index=canonical_index)
                else:
                    # Start with full section; NO independent 12-hour agent resets.
                    full_df = load_sections_for_columns(
                        well=well, sections=tuple(sections), requested_columns=tuple(requested_columns),
                        time_start=None, time_end=None)
                    assert_full_section_loaded(full_time_index, full_df.index)
                    full_df, mapped, _ = apply_cleaning_layer(
                        df=full_df, label_to_column=label_to_column, cleaning_rules=cleaning_rules,
                        required_activity_labels=list(required_activity_labels),
                        required_symptom_labels=list(required_symptom_labels))
                    assert_full_section_loaded(full_time_index, full_df.index)
                    coverage = continuous_prediction_coverage(full_df.index,
                        log_utc_offset=log_offset, cadence_seconds=float(cadence),
                        max_gap_seconds=float(max_gap))
                    # State resolution currently runs over the entire section with no
                    # missing-data reset. Refuse gaps rather than silently bridge them.
                    assert_unbroken_prediction_state(coverage)
                    detected = calculate_continuous_predictions(
                        full_df=full_df, label_to_column=mapped, activity_ui=activity_ui,
                        symptom_ui=symptom_ui, selected_agent=str(agent), agent_kind=kind,
                        run_activity=run_activity, resolve_activity=resolve_activity,
                        run_symptom=run_symptom)
                    predictions = normalize_predictions(detected, agent=str(agent),
                        log_utc_offset=log_offset, sample_cadence_seconds=float(cadence),
                        sample_index=full_df.index)
                payload = dict(schema_version=1, well=str(well), section=' + '.join(map(str,sections)),
                    agent=str(agent), agent_kind=kind, reviewed_intervals=review,
                    prediction_coverage=coverage, predictions_complete=True,
                    prediction_generation=uploaded['prediction_generation'] if offline_mode else 'continuous',
                    sample_cadence_seconds=float(cadence))
                if kind == 'symptom':
                    payload.update(expert_tags=experts, predictions=predictions,
                        matching={'version':RULE_VERSION,'method':'iou_one_to_one',
                                  'min_iou':float(min_iou), 'min_overlap_seconds':float(min_overlap)})
                    result = evaluate_events(payload)
                else:
                    # The UI labels ONE selected activity; do not fabricate other
                    # activity classes. Compare selected activity vs NotSelected.
                    expert_binary, prediction_binary = binary_activity_timelines(
                        experts, predictions, review, agent=str(agent),
                        sample_cadence_seconds=float(cadence))
                    payload.update(activity_labels=[str(agent),'NotSelected'],
                        expert_activities=expert_binary, predicted_activities=prediction_binary)
                    result = evaluate_activities(payload)
                    result['interpretation'] = 'Binary selected-activity vs NotSelected, not full multiclass accuracy.'
                activity_conf = activity_ui.get('config')
                symptom_conf = symptom_ui.get('config')
                config_serialized = json.dumps({
                    'activity': asdict(activity_conf) if is_dataclass(activity_conf) else str(activity_conf),
                    'symptom': asdict(symptom_conf) if is_dataclass(symptom_conf) else str(symptom_conf),
                }, sort_keys=True, default=str)
                root = Path(__file__).resolve().parents[1]
                report = {'validation_report': result,
                          'validation_input': payload,
                          'processing_configuration': {
                              'activity_ui': clean_ui(activity_ui, 'activity'),
                              'symptom_ui': clean_ui(symptom_ui, 'symptom'),
                              'requested_columns': list(requested_columns),
                              'label_to_column': label_to_column, 'cleaning_rules': cleaning_rules,
                              'required_activity_labels': list(required_activity_labels),
                              'required_symptom_labels': list(required_symptom_labels),
                          },
                          'provenance': {'agent_configuration_sha256':hashlib.sha256(config_serialized.encode()).hexdigest(),
                                         'expert_session_sha256':hashlib.sha256(session_file.getvalue()).hexdigest(),
                                         'log_utc_offset':log_offset,'sample_cadence_seconds':cadence,
                                         'max_data_gap_seconds':max_gap,
                                         'full_section_sample_count':expected_job['full_sample_count'] if offline_mode else len(full_time_index),
                                         'raw_section_sample_count':len(full_time_index),
                                         'interval_endpoint_policy':'next_observed_sample_or_final_cadence_v1',
                                         'software_sha256':source_fingerprint(root),
                                         'data_sha256':expected_job['data_sha256'] if offline_mode else sha256_file(
                                             section_path(str(well), str(sections[0]), data_dir=root / 'data')),
                                         'warning':'Legacy Hit Results/95% acceptance do not measure these final metrics.',
                                         'review_completeness_and_clock_confirmed_by_operator':True,
                                         'prediction_source':'verified_offline_upload' if offline_mode else 'online_continuous',
                                         'prediction_job_sha256':expected_job['job_sha256'] if offline_mode else None}}
                st.session_state[report_key] = {'signature': signature, 'report': report}
            except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                st.error(f'Not evaluable: {exc}')
            except Exception as exc:
                st.error('Final validation failed; no score has been accepted. Check input and processing diagnostics.')
                st.exception(exc)
        saved_report = st.session_state.get(report_key)
        if saved_report is not None:
            report = saved_report['report']
            result = report['validation_report']
            if result.get('status') == 'evaluated':
                st.success('Independent report calculated from verified offline full-section predictions.' if offline_mode else
                           'Independent report calculated from continuously processed full-section data.')
            else:
                st.warning('Partial evaluation only: unmatched boundary-crossing predictions require review. FP, precision and F1 are not definitive.')
            st.json(result)
            st.download_button('Download independent validation report',
                data=json.dumps(report,indent=2,allow_nan=False), mime='application/json',
                file_name='independent_validation_report.json', on_click='ignore')
