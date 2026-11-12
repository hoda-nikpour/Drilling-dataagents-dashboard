"""Explicit table navigation must not replay or change expert tags."""
from unittest.mock import patch

import pandas as pd
import pytest
import streamlit as st

from app import _apply_virtual_component_event, _build_virtual_window_info
from app import _render_virtual_log_component
from ui.layout import _apply_agent_interval_click
from services.virtual_window_service import agent_interval_view_start
import uuid

CTX = 'navigation__8.5'
START = pd.Timestamp('2026-01-01')
END = pd.Timestamp('2026-01-03')


@pytest.fixture(autouse=True)
def clear_state():
    st.session_state.clear()
    st.session_state[f'_virtual_browser_session_token_{CTX}'] = 'editor'
    yield
    st.session_state.clear()


def queue(start='2026-01-02 06:00:00', column='start', row=0):
    value=dict(event='agent_interval_click' if column=='start' else 'unrelated',request_id=uuid.uuid4().hex,
        row_index=row,context_key=CTX,table_revision='revision',browser_session_token='editor')
    _apply_agent_interval_click(value, (start,), CTX, 'revision')
    return st.session_state.get(f'_virtual_navigation_request_{CTX}')


@pytest.mark.parametrize('start,column,row', [
    ('2026-01-02', 'end', 0), ('2026-01-02', 'label', 0),
    ('2026-01-02', 'start', -1), ('2026-01-02', 'start', 5),
    ('invalid', 'start', 0), (pd.NaT, 'start', 0),
])
def test_only_valid_start_cells_queue_navigation(start, column, row):
    assert queue(start, column, row) is None
    assert f'_agent_interval_table_generation_{CTX}' not in st.session_state


def test_reclick_same_start_creates_distinct_one_shot_commands():
    first = queue()
    second = queue()
    assert first['start'] == second['start'] == '2026-01-02 06:00:00'
    assert first['id'] != second['id']
    assert st.session_state[f'_agent_interval_table_generation_{CTX}'] == 2


class Rerun(BaseException):
    pass


def event(request, start=None, span=1800, token='editor'):
    return dict(event='viewport_request', source='agent_interval',
                navigation_id=request['id'], browser_session_token=token,
                viewport_start=start or str(agent_interval_view_start(
                    request['start'], span, lead_fraction=request.get('lead_in_fraction', 0))),
                viewport_span_seconds=span)


@pytest.mark.parametrize('target,span,expected', [
    ('2026-01-02 06:00:00', 1800, '2026-01-02 05:57:30'),
    ('2026-01-02 23:50:00', 1800, '2026-01-02 23:30:00'),
    ('2026-01-02 23:50:00', 1835.1, '2026-01-02 23:29:24'),
    ('2026-01-02 06:00:00', 43200, '2026-01-02 05:00:00'),
])
def test_jump_preserves_span_loads_target_buffer_and_leaves_tags_unchanged(target, span, expected):
    request = queue(target)
    st.session_state[f'_virtual_browser_session_token_{CTX}'] = 'editor'
    tag = {'tag_id': 'expert', 'start': '2026-01-01 02:00:00', 'end': '2026-01-01 03:00:00'}
    st.session_state[f'tag_ledger_{CTX}'] = [tag]
    with patch.object(st, 'rerun', side_effect=Rerun):
        with pytest.raises(Rerun):
            _apply_virtual_component_event(event(request, start=expected, span=span), CTX, START, END)
    window = _build_virtual_window_info(pd.DataFrame({'_section_in': [8.5, 8.5]}, index=pd.DatetimeIndex([START, END])), CTX)
    assert window['viewport_start'] == pd.Timestamp(expected)
    assert window['viewport_span_seconds'] == span
    assert window['start'] <= pd.Timestamp(target) <= window['end']
    assert st.session_state[f'tag_ledger_{CTX}'] == [tag]
    assert f'_virtual_navigation_request_{CTX}' not in st.session_state
    # The previous component value can be returned again during a rerun.
    assert _apply_virtual_component_event(event(request, start=expected, span=span), CTX, START, END) is False


@pytest.mark.parametrize('change', [
    {'navigation_id': 'old'}, {'browser_session_token': 'old-editor'},
    {'viewport_start': '2026-01-01 02:00:00'},
])
def test_stale_or_mismatched_navigation_cannot_move_the_plot(change):
    request = queue()
    st.session_state[f'_virtual_browser_session_token_{CTX}'] = 'editor'
    before = st.session_state[f'virtual_viewport_start_{CTX}']
    assert _apply_virtual_component_event(dict(event(request), **change), CTX, START, END) is False
    assert st.session_state[f'virtual_viewport_start_{CTX}'] == before
    assert st.session_state[f'_virtual_navigation_request_{CTX}'] == request


def test_restoring_another_editor_discards_its_predecessors_pending_command():
    request = queue()
    st.session_state[f'_virtual_browser_session_token_{CTX}'] = 'restored-editor'
    assert _apply_virtual_component_event(event(request, token='restored-editor'), CTX, START, END) is False
    frame = pd.DataFrame({'TRQ': [1., 2.]}, index=pd.DatetimeIndex([START, END]))
    window = _build_virtual_window_info(frame, CTX)
    with patch('app.render_virtual_log_viewer', return_value=None) as component:
        _render_virtual_log_component(df=frame, context_key=CTX, selected_well='navigation', selected_sections=('8.5',),
            track_params_real=[['TRQ']], track_param_labels=[['TRQ']], agent_cfg={}, window_info=window, chart_height=650)
    assert component.call_args.kwargs['navigation_request'] is None
    assert f'_virtual_navigation_request_{CTX}' not in st.session_state


def test_each_actual_click_moves_backend_even_without_a_chart_response():
    value=dict(event='agent_interval_click',request_id='one',row_index=1,context_key=CTX,
        table_revision='rev',browser_session_token='editor')
    starts=('2006-01-26 00:00:00','2006-02-06 05:21:45')
    assert _apply_agent_interval_click(value,starts,CTX,'rev') is True
    assert st.session_state[f'virtual_viewport_start_{CTX}']==pd.Timestamp('2006-02-06 04:21:45')
    st.session_state[f'virtual_viewport_start_{CTX}']=pd.Timestamp(starts[0])
    assert _apply_agent_interval_click(value,starts,CTX,'rev') is False
    assert _apply_agent_interval_click(dict(value,request_id='two'),starts,CTX,'rev') is True
    assert st.session_state[f'virtual_viewport_start_{CTX}']==pd.Timestamp('2006-02-06 04:21:45')


@pytest.mark.parametrize('change',[{'context_key':'other'},{'table_revision':'old'},
    {'browser_session_token':'old'},{'row_index':True},{'row_index':100}])
def test_stale_or_invalid_table_buttons_are_ignored(change):
    value=dict(event='agent_interval_click',request_id='one',row_index=0,context_key=CTX,
        table_revision='rev',browser_session_token='editor')
    assert _apply_agent_interval_click(dict(value,**change),('2006-02-06',),CTX,'rev') is False
    assert f'virtual_viewport_start_{CTX}' not in st.session_state


def test_returning_to_a_previous_agent_table_does_not_replay_its_old_value():
    def click(request_id, revision):
        return dict(event='agent_interval_click',request_id=request_id,row_index=0,
                    context_key=CTX,table_revision=revision,browser_session_token='editor')
    first=click('first','agent-a')
    second=click('second','agent-b')
    assert _apply_agent_interval_click(first,('2006-02-06',),CTX,'agent-a')
    assert _apply_agent_interval_click(second,('2006-01-30',),CTX,'agent-b')
    assert not _apply_agent_interval_click(first,('2006-02-06',),CTX,'agent-a')
    assert st.session_state[f'virtual_viewport_start_{CTX}']==pd.Timestamp('2006-01-29 23:00:00')
    assert _apply_agent_interval_click(dict(first,request_id='third'),('2006-02-06',),CTX,'agent-a')


@pytest.mark.parametrize('span,expected', [
    (43200, '2026-01-01 05:00:00'),
    (3600, '2026-01-01 05:55:00'),
    (1800, '2026-01-01 05:57:30'),
    (30, '2026-01-01 05:59:57.500'),
])
def test_context_margin_scales_with_the_current_zoom(span,expected):
    assert agent_interval_view_start('2026-01-01 06:00:00',span)==pd.Timestamp(expected)


def ordered_click(order, row):
    return dict(event='agent_interval_click',request_id=f'click-{order}',request_order=order,
                row_index=row,context_key=CTX,table_revision='ordered',browser_session_token='editor')


def test_latest_click_wins_over_old_table_values_and_chart_acknowledgements():
    starts=('2026-01-01 03:00:00','2026-01-02 06:00:00','2026-01-01 16:00:00')
    requests=[]
    for order,row in [(100,0),(101,1),(102,2)]:
        assert _apply_agent_interval_click(ordered_click(order,row),starts,CTX,'ordered')
        requests.append(st.session_state[f'_virtual_navigation_request_{CTX}'])
    assert not _apply_agent_interval_click(ordered_click(100,0),starts,CTX,'ordered')
    assert not _apply_agent_interval_click(ordered_click(101,1),starts,CTX,'ordered')
    assert not _apply_virtual_component_event(event(requests[0]),CTX,START,END)
    assert not _apply_virtual_component_event(event(requests[1]),CTX,START,END)
    assert st.session_state[f'virtual_viewport_start_{CTX}']==pd.Timestamp('2026-01-01 15:00:00')
    assert st.session_state[f'_virtual_navigation_request_{CTX}']['id']=='click-102'
    with patch.object(st,'rerun',side_effect=Rerun):
        with pytest.raises(Rerun):
            _apply_virtual_component_event(event(requests[-1],span=43200),CTX,START,END)
    assert f'_virtual_navigation_request_{CTX}' not in st.session_state


@pytest.mark.parametrize('order',[True,False,0,-1,1.5,'100',float('nan')])
def test_invalid_click_orders_cannot_replace_the_view(order):
    assert not _apply_agent_interval_click(ordered_click(order,0),('2026-01-01 06:00:00',),CTX,'ordered')
    assert f'virtual_viewport_start_{CTX}' not in st.session_state


def test_legacy_table_value_cannot_replace_a_newer_ordered_click():
    starts=('2026-01-01 06:00:00',)
    assert _apply_agent_interval_click(ordered_click(100,0),starts,CTX,'ordered')
    legacy=dict(ordered_click(101,0));legacy.pop('request_order')
    assert not _apply_agent_interval_click(legacy,starts,CTX,'ordered')


def test_retained_arrow_value_does_not_undo_a_table_click_but_a_new_return_works():
    arrow=dict(event='viewport_request',source='arrow_scroll',browser_session_token='editor',
               viewport_start='2026-01-01 02:00:00',viewport_span_seconds=43200)
    with patch.object(st,'rerun',side_effect=Rerun):
        with pytest.raises(Rerun):
            _apply_virtual_component_event(arrow,CTX,START,END)
        request=queue('2026-01-02 06:00:00')
        assert not _apply_virtual_component_event(arrow,CTX,START,END)
        assert st.session_state[f'virtual_viewport_start_{CTX}']==pd.Timestamp('2026-01-02 05:00:00')
        assert not _apply_virtual_component_event(event(request,span=43200),CTX,START,END)
        with pytest.raises(Rerun):
            _apply_virtual_component_event(arrow,CTX,START,END)


def test_context_margin_cannot_move_the_view_before_the_section_start():
    queue('2026-01-01 00:10:00')
    window=_build_virtual_window_info(pd.DataFrame({'_section_in':[8.5,8.5]},index=pd.DatetimeIndex([START,END])),CTX)
    assert window['viewport_start']==START
