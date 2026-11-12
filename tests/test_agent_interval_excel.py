"""Real editable XLSX, retaining event times and omitting buffer metadata."""
from datetime import datetime,timedelta
from io import BytesIO
import json
from zipfile import ZipFile
import pytest
from openpyxl import load_workbook
from ui.layout import _agent_interval_excel_bytes


@pytest.mark.parametrize('agent,source',[('TRQSpike','Symptom agent'),('Drilling','Activity agent')])
def test_real_excel_retains_all_intervals_and_only_drops_processing_windows(agent,source):
    rows=[dict(label=agent,start='2006-02-06 05:21:45',end='2006-02-06 05:21:45',
               severity='Low',source=source,window=8,window_start='2006-02-06 00:00:00',
               window_end='2006-02-06 12:00:00'),
          dict(label=agent,start='2006-02-06 05:21:45',end='2006-02-06 05:22:15',
               severity='High',source=source,window=8,window_start='2006-02-06 00:00:00',
               window_end='2006-02-06 12:00:00')]
    serialized=json.dumps(rows)
    data=_agent_interval_excel_bytes(serialized,tuple(rows[0]))
    assert data.startswith(b'PK')
    with ZipFile(BytesIO(data)) as archive:
        assert 'xl/workbook.xml' in archive.namelist()
    sheet=load_workbook(BytesIO(data)).active
    assert list(next(sheet.values))==['Data agent','Start','End','Severity','Source']
    assert sheet.max_row==3
    assert sheet['B2'].value==sheet['C2'].value==datetime(2006,2,6,5,21,45)
    assert sheet['C3'].value==datetime(2006,2,6,5,22,15)
    assert sheet['D2'].value=='Low' and sheet['D3'].value=='High'
    assert sheet['E2'].value==source
    assert sheet['B2'].number_format=='yyyy-mm-dd hh:mm:ss'
    assert sheet.freeze_panes=='A2'
    assert sheet.auto_filter.ref=='A1:E3'
    assert json.loads(serialized)==rows


def test_expert_can_edit_and_resave_dates_in_the_downloaded_workbook():
    rows=[dict(label='TRQSpike',start='2006-02-06 05:21:45',end='2006-02-06 05:22:15',window=2)]
    data=_agent_interval_excel_bytes(json.dumps(rows),tuple(rows[0]))
    workbook=load_workbook(BytesIO(data));sheet=workbook.active
    assert not sheet.protection.sheet
    sheet['C2']=sheet['C2'].value+timedelta(minutes=3)
    output=BytesIO();workbook.save(output)
    assert load_workbook(output).active['C2'].value==datetime(2006,2,6,5,25,15)


def test_changing_an_interval_refreshes_the_cached_excel_values():
    row=dict(label='Drilling',start='2006-02-06 05:21:45',end='2006-02-06 05:22:15',window=1)
    first=_agent_interval_excel_bytes(json.dumps([row]),tuple(row))
    second=_agent_interval_excel_bytes(json.dumps([dict(row,end='2006-02-06 06:00:00')]),tuple(row))
    assert load_workbook(BytesIO(first)).active['C2'].value==datetime(2006,2,6,5,22,15)
    assert load_workbook(BytesIO(second)).active['C2'].value==datetime(2006,2,6,6,0,0)
