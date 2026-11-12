"""Strict, optional exchange protocol for *offline* section-wide predictions.

This does not change activity/symptom algorithms or online tag persistence.
Hashes detect accidental data/configuration/code mismatches; they are NOT a
cryptographic signature or a guarantee that independently edited predictions
are scientifically correct.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from hashlib import sha256
from math import isfinite
from pathlib import Path
import json

from config import DATA_DIR
from drillmate_validation.events import ValidationError, _interval, _covered, _merged
from services.validation_continuous import (
    fixed_utc_offset, continuous_prediction_coverage,
)
from services.offline_gap_segments import (split_at_gaps, restart_warmup_samples)

OFFLINE_SCHEMA = 3
OFFLINE_MAX_ROWS = 1_200_000  # must be explicit; not a permission to downsample


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def digest(obj) -> str:
    return sha256(canonical(obj)).hexdigest()


def sha256_file(path: Path) -> str:
    hasher = sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            hasher.update(chunk)
    return hasher.hexdigest()


def section_path(well: str, section: str, *, data_dir: Path = DATA_DIR) -> Path:
    """Prevent path traversal: only the catalog's normalized file naming is allowed."""
    import re
    if not re.fullmatch(r'[A-Za-z0-9_-]+', well) or not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', section):
        raise ValidationError('Invalid well/section filename')
    path = data_dir / f'{well}_{section.replace(".", "_")}in.parquet'
    if not path.is_file():
        raise ValidationError(f'Data file not found: {path.name}')
    return path


def source_fingerprint(root: Path) -> str:
    """Hash the modules that determine loading, cleaning and prediction semantics."""
    root = Path(root)
    candidates = [root / 'config.py', root / 'app.py']
    for folder in ('agents', 'services', 'data_access', 'drillmate_validation'):
        candidates.extend(sorted((root / folder).glob('*.py')))
    candidates.extend([root / 'tools/generate_full_section_predictions.py',
                       root / 'ui/final_validation_panel.py'])
    hasher = sha256()
    for file in sorted(set(candidates)):
        if not file.is_file():
            raise ValidationError(f'Software fingerprint missing file: {file.name}')
        hasher.update(file.relative_to(root).as_posix().encode() + b'\0')
        with file.open('rb') as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                hasher.update(chunk)
    return hasher.hexdigest()


def clean_ui(ui: dict, config_name: str) -> dict:
    cfg = ui.get('config')
    if not is_dataclass(cfg):
        raise ValidationError(f'{config_name} must be a dataclass')
    return {
        'enabled': ui.get('enabled') is True,
        'selected_activity' if config_name == 'activity' else 'selected_symptom':
            ui.get('selected_activity' if config_name == 'activity' else 'selected_symptom'),
        'config': asdict(cfg),
    }


def make_job(*, root: Path, well: str, section: str, agent: str, agent_kind: str,
             full_sample_count: int, log_utc_offset: str, cadence_seconds: float,
             max_gap_seconds: float, activity_ui: dict, symptom_ui: dict,
             requested_columns: list, label_to_column: dict, cleaning_rules: dict,
             required_activity_labels: list, required_symptom_labels: list) -> dict:
    if agent_kind not in ('symptom', 'activity') or not agent or not str(agent).strip():
        raise ValidationError('Select one valid activity or symptom agent')
    fixed_utc_offset(log_utc_offset)
    if (not all(isfinite(float(x)) for x in [cadence_seconds, max_gap_seconds])
            or not 0 < float(cadence_seconds) <= float(max_gap_seconds)
            or float(max_gap_seconds) > 10 * float(cadence_seconds)):
        raise ValidationError('Verified gap must be between one and ten sample cadences; a larger gap could hide missing data')
    if not isinstance(full_sample_count, int) or full_sample_count < 1:
        raise ValidationError('Full-section sample count must be positive')
    activity = clean_ui(activity_ui, 'activity')
    symptom = clean_ui(symptom_ui, 'symptom')
    if not activity['enabled']:
        raise ValidationError('Activity pipeline must be enabled')
    if agent_kind == 'symptom' and (not symptom['enabled'] or symptom['selected_symptom'] != agent):
        raise ValidationError('Selected symptom and active settings mismatch')
    if agent_kind == 'activity' and activity['selected_activity'] != agent:
        raise ValidationError('Selected activity and active settings mismatch')
    data_file = section_path(well, section, data_dir=Path(root) / 'data')
    warmup_samples = restart_warmup_samples(activity['config'], symptom['config'])
    job = {
        'schema_version': OFFLINE_SCHEMA,
        'purpose': 'drillmate-offline-prediction-job',
        'well': well, 'section': section, 'agent': agent, 'agent_kind': agent_kind,
        'full_sample_count': full_sample_count,
        'duplicate_policy': 'verify_all_raw_columns_except_source_file_v1',
        'interval_endpoint_policy': 'next_observed_sample_or_final_cadence_v1',
        'gap_restart_policy': 'independent_segment_state_with_excluded_warmup_v1',
        'gap_restart_warmup_samples': warmup_samples,
        'log_utc_offset': log_utc_offset,
        'cadence_seconds': float(cadence_seconds),
        'max_gap_seconds': float(max_gap_seconds),
        'activity_ui': activity, 'symptom_ui': symptom,
        'requested_columns': list(requested_columns),
        'label_to_column': dict(label_to_column),
        'cleaning_rules': cleaning_rules,
        'required_activity_labels': list(required_activity_labels),
        'required_symptom_labels': list(required_symptom_labels),
        'data_sha256': sha256_file(data_file),
        'software_sha256': source_fingerprint(root),
    }
    job['job_sha256'] = digest(job)
    return job


def validate_job(job: dict, *, root: Path, check_file: bool = True) -> None:
    if not isinstance(job, dict) or job.get('schema_version') != OFFLINE_SCHEMA or job.get('purpose') != 'drillmate-offline-prediction-job':
        raise ValidationError('Invalid offline prediction job schema/purpose')
    signed = {k: v for k, v in job.items() if k != 'job_sha256'}
    if job.get('job_sha256') != digest(signed):
        raise ValidationError('Job manifest checksum mismatch')
    if job.get('software_sha256') != source_fingerprint(root):
        raise ValidationError('Offline and dashboard prediction software are not identical')
    if check_file and job.get('data_sha256') != sha256_file(section_path(job['well'], job['section'], data_dir=Path(root) / 'data')):
        raise ValidationError('Underlying Parquet file differs from the manifest')
    fixed_utc_offset(job['log_utc_offset'])
    if job.get('duplicate_policy') != 'verify_all_raw_columns_except_source_file_v1':
        raise ValidationError('Unsupported/missing offline duplicate policy; regenerate the job')
    if job.get('interval_endpoint_policy') != 'next_observed_sample_or_final_cadence_v1':
        raise ValidationError('Unsupported/missing interval endpoint policy; regenerate the job')
    if job.get('gap_restart_policy') != 'independent_segment_state_with_excluded_warmup_v1':
        raise ValidationError('Unsupported/missing gap reset policy; regenerate the job')
    if job.get('gap_restart_warmup_samples') != restart_warmup_samples(
            job['activity_ui']['config'], job['symptom_ui']['config']):
        raise ValidationError('Gap restart warm-up does not match active agent configuration')
    if (not all(isfinite(float(job[x])) for x in ('cadence_seconds', 'max_gap_seconds'))
            or not 0 < float(job['cadence_seconds']) <= float(job['max_gap_seconds'])
            or float(job['max_gap_seconds']) > 10 * float(job['cadence_seconds'])):
        raise ValidationError('Invalid sampling cadence/gap in job')


def make_prediction_file(job: dict, predictions: list[dict], coverage: list[dict], sample_count: int,
                         *, generation: str = 'continuous', segments: list[dict] | None = None) -> dict:
    if sample_count != job['full_sample_count']:
        raise ValidationError('Prediction sample count differs from manifest')
    value = {
        'schema_version': OFFLINE_SCHEMA,
        'purpose': 'drillmate-offline-predictions',
        'job_sha256': job['job_sha256'],
        'well': job['well'], 'section': job['section'],
        'agent': job['agent'], 'agent_kind': job['agent_kind'],
        'sample_count': sample_count,
        'prediction_generation': generation,
        'prediction_segments': segments,
        'prediction_coverage': coverage,
        'predictions': predictions,
    }
    value['prediction_payload_sha256'] = digest(value)
    return value


def verify_prediction_file(file: dict, *, expected_job: dict, full_time_index) -> tuple[list[dict], list[dict]]:
    """Fail closed on mismatched identity, settings, data and coverage.

    expected_job MUST be regenerated by the trusted online UI using current
    controls and the SAME Parquet file (including sha256 verification).
    """
    if not isinstance(file, dict) or file.get('schema_version') != OFFLINE_SCHEMA or file.get('purpose') != 'drillmate-offline-predictions':
        raise ValidationError('Invalid offline predictions format')
    if file.get('prediction_payload_sha256') != digest({k:v for k,v in file.items() if k != 'prediction_payload_sha256'}):
        raise ValidationError('Prediction payload was modified/corrupted')
    for key in ('well', 'section', 'agent', 'agent_kind'):
        if file.get(key) != expected_job.get(key):
            raise ValidationError(f'Prediction file {key} does not match selected dashboard settings')
    if file.get('job_sha256') != expected_job['job_sha256']:
        raise ValidationError('Prediction file belongs to different data/agent/settings/version')
    slices, expected_coverage, expected_segments = split_at_gaps(full_time_index,
        log_utc_offset=expected_job['log_utc_offset'],
        cadence_seconds=expected_job['cadence_seconds'],
        max_gap_seconds=expected_job['max_gap_seconds'],
        restart_warmup_samples=expected_job['gap_restart_warmup_samples'])
    generation = 'continuous' if len(slices) == 1 else 'gap_reset_segments'
    if file.get('prediction_generation') != generation:
        raise ValidationError('Unverified prediction generation: gap processing strategy mismatch')
    if file.get('prediction_segments') != expected_segments:
        raise ValidationError('Offline segment boundaries/warm-up differ from dashboard time index')
    if file.get('sample_count') != len(full_time_index) or file['sample_count'] != expected_job['full_sample_count']:
        raise ValidationError('Offline prediction sample count differs from dashboard')
    predicted_cov = expected_coverage
    if file.get('prediction_coverage') != predicted_cov:
        raise ValidationError('Prediction coverage differs from dashboard time index')
    rows = file.get('predictions')
    if not isinstance(rows, list):
        raise ValidationError('Missing predictions list')
    covered = _merged([_interval(i) for i in predicted_cov])
    ids = set()
    for p in rows:
        if not isinstance(p, dict) or p.get('agent') != expected_job['agent']:
            raise ValidationError('Prediction with wrong agent/format')
        if not isinstance(p.get('id'), str) or not p['id'] or p['id'] in ids:
            raise ValidationError('Prediction IDs must be unique and stable')
        ids.add(p['id'])
        if not _covered(_interval(p), covered):
            raise ValidationError('Prediction lies outside independently verified section coverage')
    return rows, predicted_cov
