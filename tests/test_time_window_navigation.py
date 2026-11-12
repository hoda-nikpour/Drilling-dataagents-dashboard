"""Explicit 12-hour paging must preserve tags and beat delayed old navigation."""
from unittest.mock import patch
import pandas as pd
import pytest
import streamlit as st
from app import _apply_virtual_component_event,_build_virtual_window_info
from ui.layout import _apply_agent_interval_click

CTX='paging__8.5'
START=pd.Timestamp('2026-01-01')
END=pd.Timestamp('2026-01-03')
TAG=dict(tag_id='expert',source='chart_drag',start='2026-01-01 03:00:00',end='2026-01-01 03:05:00')


class Rerun(BaseException):pass


@pytest.fixture(autouse=True)
def state():
    st.session_state.clear()
    st.session_state[f'_virtual_browser_session_token_{CTX}']='editor'
    st.session_state[f'tag_ledger_{CTX}']=[TAG]
    yield
    st.session_state.clear()


def navigate(start,order,source='time_page',token='editor'):
    return dict(event='viewport_request',source=source,browser_session_token=token,request_order=order,
        viewport_start=start,viewport_span_seconds=43200)


def apply(value):
    with patch.object(st,'rerun',side_effect=Rerun):
        try:_apply_virtual_component_event(value,CTX,START,END)
        except Rerun:pass


def test_forward_back_and_repeated_pages_load_the_right_data_without_changing_tags():
    for order,start in enumerate(['2026-01-01 12:00:00','2026-01-02 00:00:00',
                                  '2026-01-01 12:00:00','2026-01-01 00:00:00'],1):
        apply(navigate(start,order))
        window=_build_virtual_window_info(pd.DataFrame({'_section_in':[8.5,8.5]},index=[START,END]),CTX)
        assert window['viewport_start']==pd.Timestamp(start)
        assert window['viewport_span_seconds']==43200
        assert window['start']<=window['viewport_start']<window['viewport_end']<=window['end']
        assert st.session_state[f'tag_ledger_{CTX}']==[TAG]


@pytest.mark.parametrize('source',['time_page','set_datetime'])
def test_latest_explicit_choice_can_return_to_the_same_range_after_a_table_preload(source):
    target='2026-01-02 00:00:00'
    apply(navigate(target,100,source))
    click=dict(event='agent_interval_click',request_id='table',request_order=101,row_index=0,
        context_key=CTX,table_revision='revision',browser_session_token='editor')
    _apply_agent_interval_click(click,('2026-01-01 06:00:00',),CTX,'revision')
    assert st.session_state[f'virtual_viewport_start_{CTX}']!=pd.Timestamp(target)
    # The previous table reply has not arrived yet; a new manual operation is
    # authoritative even though its destination matches a prior fingerprint.
    apply(navigate(target,102,source))
    assert st.session_state[f'virtual_viewport_start_{CTX}']==pd.Timestamp(target)
    assert f'_virtual_navigation_request_{CTX}' not in st.session_state


def test_old_page_reply_and_old_editor_cannot_replace_a_newer_page():
    apply(navigate('2026-01-02 00:00:00',200))
    for event in [navigate('2026-01-01',199),navigate('2026-01-01',201,token='old-editor')]:
        assert not _apply_virtual_component_event(event,CTX,START,END)
    assert st.session_state[f'virtual_viewport_start_{CTX}']==pd.Timestamp('2026-01-02')
    assert st.session_state[f'tag_ledger_{CTX}']==[TAG]


def test_paging_is_limited_to_the_section_and_always_uses_a_twelve_hour_view():
    for order,start,expected in [(1,'2025-12-31','2026-01-01'),(2,'2026-01-10','2026-01-02 12:00:00')]:
        apply(navigate(start,order))
        assert st.session_state[f'virtual_viewport_start_{CTX}']==pd.Timestamp(expected)
        assert st.session_state[f'virtual_viewport_span_seconds_{CTX}']==43200
