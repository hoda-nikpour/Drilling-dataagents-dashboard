"""Strict, read-only normalization of existing dashboard session exports.

Existing session JSON and the live React Hit Results remain untouched.
A reviewed interval means the expert has checked that WHOLE interval, not
merely drawn one or more tags within it.
"""
from __future__ import annotations

import hashlib
from typing import Any

from .events import ValidationError, _interval, _merged, _covered, _intersection
from services.validation_continuous import utc_iso


def session_expert_tags(session: dict, *, well: str, sections: list[str],
                        agent: str, agent_kind: str,
                        log_utc_offset: str) -> list[dict]:
    if not isinstance(session, dict) or not isinstance(session.get('dashboard_context'), dict):
        raise ValidationError('Expected dashboard session JSON with dashboard_context')
    ctx = session['dashboard_context']
    if str(ctx.get('selected_well')) != well or [str(s) for s in ctx.get('selected_sections', [])] != [str(s) for s in sections]:
        raise ValidationError('Saved session well/sections differ from the active dashboard')
    source = 'Symptom agent' if agent_kind == 'symptom' else 'Activity agent'
    key = 'selected_symptom' if agent_kind == 'symptom' else 'selected_activity'
    if ctx.get('agent_source') != source or ctx.get(key) != agent:
        raise ValidationError('Saved session selected agent differs from current agent/settings')
    # Canonical tag_intervals already includes chart and manual tags. NEVER
    # append tag_ledger or drawn_tag_intervals again: that double-counts tags.
    raw = session.get('tag_intervals')
    if not isinstance(raw, list):
        raise ValidationError('Missing canonical tag_intervals in saved dashboard session')
    out = []
    seen = set()
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValidationError('Invalid expert tag row')
        if str(item.get('status', 'active')).lower() == 'deleted':
            continue
        start, end = utc_iso(item.get('start'), log_utc_offset), utc_iso(item.get('end'), log_utc_offset)
        if start == end:
            raise ValidationError('Zero-length expert interval; correct in dashboard')
        tag_id = str(item.get('tag_id') or '').strip()
        if not tag_id:
            text = f'{item.get("source", "manual")}|{item.get("label", "")}|{start}|{end}|{i}'
            tag_id = 'legacy-' + hashlib.sha256(text.encode()).hexdigest()[:20]
        if tag_id in seen:
            raise ValidationError(f'Duplicate expert tag_id in saved session: {tag_id}')
        seen.add(tag_id)
        out.append({'id': tag_id, 'agent': agent, 'start': start, 'end': end})
    return out


def reviewed_windows(raw: Any, log_utc_offset: str) -> list[dict]:
    if not isinstance(raw, list) or not raw:
        raise ValidationError('At least one explicitly confirmed reviewed interval is required')
    normalized = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValidationError('Reviewed intervals must be objects')
        s, e = utc_iso(item.get('start'), log_utc_offset), utc_iso(item.get('end'), log_utc_offset)
        _interval({'start': s, 'end': e})
        normalized.append({'start': s, 'end': e})
    return normalized


def binary_activity_timelines(expert_tags: list[dict], predictions: list[dict],
                              review_windows: list[dict], *, agent: str,
                              sample_cadence_seconds: float | None = None) -> tuple[list[dict], list[dict]]:
    """One selected activity vs NotSelected, NOT exhaustive multiclass review.

    Only valid if all occurrences of selected activity have been independently
    labeled over the reviewed range (including reviewed negative time).
    """
    reviewed = _merged([_interval(x) for x in review_windows])
    def build(items, prefix, require_contained):
        positives = []
        for obj in items:
            iv = _interval(obj, allow_point=not require_contained,
                           cadence=sample_cadence_seconds if not require_contained else None)
            if require_contained and not _covered(iv, reviewed):
                raise ValidationError('Expert activity tag extends outside reviewed interval')
            for w in reviewed:
                if _intersection(iv, w) > 0:
                    positives.append((max(iv.start,w.start), min(iv.end,w.end)))
        positives.sort()
        if require_contained and any(positives[i][1] > positives[i+1][0] for i in range(len(positives)-1)):
            raise ValidationError('Overlapping expert activity tags require adjudication')
        if not require_contained:
            compact = []
            for s,e in positives:
                if compact and s <= compact[-1][1]:
                    compact[-1] = (compact[-1][0], max(e,compact[-1][1]))
                else:
                    compact.append((s,e))
            positives = compact
        result = []
        def append(label,s,e):
            if e <= s: return
            from datetime import datetime, timezone
            iso = lambda v: datetime.fromtimestamp(v, tz=timezone.utc).isoformat()
            result.append({'id':f'{prefix}-{len(result)}','activity':label,'start':iso(s),'end':iso(e)})
        for w in reviewed:
            cursor = w.start
            for s,e in positives:
                if e <= w.start or s >= w.end: continue
                s,e = max(s,w.start),min(e,w.end)
                if cursor < s: append('NotSelected',cursor,s)
                if cursor < e:
                    append(agent, max(cursor,s),e)
                    cursor=e
            if cursor < w.end: append('NotSelected',cursor,w.end)
        return result
    return build(expert_tags,'expert',True), build(predictions,'prediction',False)
