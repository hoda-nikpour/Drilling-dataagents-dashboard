"""Check actual Start clicks across selectable wells/sections/agents/dates."""
import argparse
import asyncio
import base64
from datetime import datetime, timedelta
import json
import sys
import time
from urllib.parse import urlencode
import websockets
import check_agent_interval_navigation as driver

CONFIG = None


def expected_view(target, initial):
    span=timedelta(seconds=float(initial.get('span') or 43200))
    first=datetime.fromisoformat(initial['section_start'])
    last=max(first,datetime.fromisoformat(initial['section_end'])-span)
    return max(first,min(datetime.fromisoformat(target)-span/12,last)).replace(microsecond=0).isoformat(sep=' ')

async def exercise(ws_url,url,inspect_only):
    async with websockets.connect(ws_url,max_size=40_000_000) as ws:
        c=driver.CDP(ws)
        await c.call('Runtime.enable');await c.call('Page.enable')
        await c.call('Emulation.setDeviceMetricsOverride',dict(width=2100,height=1600,deviceScaleFactor=1,mobile=False))
        await c.call('Page.navigate',dict(url=url+'?'+urlencode(dict(well=CONFIG.well,section=CONFIG.section,agent=CONFIG.agent))))
        prefix=driver.PLOT_PREFIX
        await c.wait_js(prefix+'return !!a && !!document.querySelector("pre code");})()',timeout=240)
        print('Full app ready:',CONFIG.well,CONFIG.section,CONFIG.agent,flush=True)
        async def server():return json.loads(await c.js('document.querySelector("pre code").textContent'))
        async def state():
            return await c.js(prefix+'return {range:a?.yaxis?.range,input:d?.querySelector("input[type=datetime-local]")?.value,caption:d?.querySelector(".vlv-time-range")?.textContent,loading:d?.querySelector(".vlv-navigation-loading")?.textContent||null,firstCurve:g?.data.find(t=>t.meta?.label==="TRQ")?.y[0]};})()')
        initial=await server();rows=initial['intervals']
        (driver.OUT/'initial-server.json').write_text(json.dumps(initial,indent=2))
        targets=[]
        for date in CONFIG.date:
            match=len(rows)-1 if date=='last' else next((i for i,row in enumerate(rows) if str(row['start']).startswith(date)),None)
            assert match is not None,('No detected interval on requested date',date)
            targets.append((match,str(rows[match]['start'])))
        await c.js('window.navigationMessages=[];window.addEventListener("message",e=>{if(e.data?.type==="streamlit:setComponentValue"&&e.data.value?.event)window.navigationMessages.push(e.data.value);})')
        results=[]
        # Return to the first timestamp after another click as well.
        if len(targets)>1:targets.append(targets[0])
        for case_index,(source_row,target) in enumerate(targets):
            expected=expected_view(target,initial)
            date=target[:10]
            # Search using the user's date format and reorder the displayed rows.
            await driver.table_search(c,'.'.join(reversed(date.split('-'))))
            if case_index%2==0:
                await driver.table_click(c,'d.querySelector("button[data-sort-column=start]")')
            before=await state()
            before_generation=(await server())['generation']
            message_count=await c.js('window.navigationMessages.filter(m=>m.event==="agent_interval_click").length')
            await driver.table_click(c,'Array.from(d.querySelectorAll("button[data-interval-start]")).find(b=>b.dataset.intervalStart==='+json.dumps(target)+')')
            await c.wait_js('window.navigationMessages.filter(m=>m.event==="agent_interval_click").length>'+str(message_count))
            deadline=time.monotonic()+90;passed=False
            while time.monotonic()<deadline:
                data=await server();view=await state()
                if data['generation']>before_generation and data['viewport']==expected and view['range'][1]==expected and view['loading'] is None and data.get('pending') is None:
                    passed=True;break
                await asyncio.sleep(.25)
            clicked=data.get('clicked_selection') or {}
            passed=passed and clicked.get('row_index')==source_row
            # Verify sensor data as well as the exact chart range and caption.
            target_time=datetime.fromisoformat(target)
            passed=passed and datetime.fromisoformat(data['loaded_start'])<=target_time<=datetime.fromisoformat(data['loaded_end'])
            passed=passed and view['firstCurve']==data['loaded_start']
            if results:
                passed=passed and clicked.get('request_id')!=results[-1]['server']['clicked_selection']['request_id']
            result=dict(target=target,expected_view=expected,source_row=source_row,passed=passed,before=before,after=view,server=data,messages=await c.js('window.navigationMessages'))
            results.append(result)
            (driver.OUT/'cases.json').write_text(json.dumps(results,indent=2))
            shot=await c.call('Page.captureScreenshot',dict(format='png',captureBeyondViewport=True))
            (driver.OUT/f'case-{len(results)}.png').write_bytes(base64.b64decode(shot['data']))
            print('Target',target,'passed',passed,'caption',view['caption'],'clicked',data.get('clicked_selection'),flush=True)
            assert passed,('Navigation did not reach the selected timestamp',result)
            await asyncio.sleep(.6)
        if CONFIG.rapid:
            await driver.table_search(c,'')
            burst=await c.js(driver.TABLE_PREFIX+'const buttons=Array.from(d.querySelectorAll("button[data-interval-start]"));const targets=[...new Set(buttons.map(b=>b.dataset.intervalStart))].slice(0,3);for(const target of targets)buttons.find(b=>b.dataset.intervalStart===target).click();return targets;})()')
            assert len(burst)==3,burst
            target=burst[-1];expected=expected_view(target,initial)
            await c.wait_js(driver.PLOT_PREFIX+'try{const s=JSON.parse(document.querySelector("pre code").textContent);return s.viewport==='+json.dumps(expected)+' && !s.pending && a.yaxis.range[1]==='+json.dumps(expected)+';}catch(e){return false;}})()',timeout=90)
            await asyncio.sleep(1.5)
            s,v=await server(),await state()
            assert s['viewport']==v['range'][1]==expected
            assert datetime.fromisoformat(s['loaded_start'])<=datetime.fromisoformat(target)<=datetime.fromisoformat(s['loaded_end'])
            (driver.OUT/'rapid.json').write_text(json.dumps(dict(passed=True,clicked=burst,expected_view=expected,after=v,server=s),indent=2))
            print('Rapid click sequence passed:',burst,'final view:',expected,flush=True)
        if CONFIG.paging:
            previous_view=(await state())['range'][1]
            tags=await c.js('Object.values(window.__drillmateSnapshotProviders).at(-1)().tags')
            expected=(datetime.fromisoformat(previous_view)+timedelta(hours=12)).isoformat(sep=' ')
            for selector,target in [('.vlv-time-navigation button:last-child',expected),
                                    ('.vlv-time-navigation button:first-child',previous_view)]:
                await c.js(prefix+'const b=d.querySelector('+json.dumps(selector)+');if(b.disabled)throw Error("Paging control disabled");b.click();})()')
                await c.wait_js(prefix+'try{const s=JSON.parse(document.querySelector("pre code").textContent);return s.viewport==='+json.dumps(target)+' && a.yaxis.range[1]==='+json.dumps(target)+' && !d.querySelector(".vlv-navigation-loading");}catch(e){return false;}})()',timeout=90)
                assert await c.js('Object.values(window.__drillmateSnapshotProviders).at(-1)().tags')==tags
                assert (await server())['span']==43200
            (driver.OUT/'twelve-hour-paging.json').write_text(json.dumps(dict(passed=True,start=previous_view,next=expected,restored=previous_view,tags_unchanged=True),indent=2))
            print('Real-log Next → Previous paging restores exact time and tags',flush=True)
        if CONFIG.workflow:
            downloads=driver.OUT/'downloads';downloads.mkdir(exist_ok=True)
            await c.call('Browser.setDownloadBehavior',dict(behavior='allow',downloadPath=str(downloads)))
            await c.js(driver.TABLE_PREFIX+'Array.from(d.querySelectorAll("button")).find(b=>b.textContent.includes("Download Excel")).click();})()')
            excel_file=None
            for _ in range(80):
                files=list(downloads.glob('*.xlsx'))
                if files:excel_file=max(files,key=lambda p:p.stat().st_mtime_ns);break
                await asyncio.sleep(.1)
            assert excel_file is not None,'No interval XLSX downloaded'
            from openpyxl import load_workbook
            sheet=load_workbook(excel_file).active
            values=list(sheet.values);headers=list(values[0]);exported=[dict(zip(headers,row)) for row in values[1:]]
            assert not {'window','window_start','window_end'} & {str(name).lower() for name in headers}
            assert len(exported)==len(rows)
            assert [r['Start'] for r in exported]==[datetime.fromisoformat(str(r['start'])) for r in rows]
            assert [r['End'] for r in exported]==[datetime.fromisoformat(str(r['end'])) for r in rows]
            (driver.OUT/'interval-excel.json').write_text(json.dumps(dict(passed=True,columns=headers,rows=len(exported),
                true_event_times_preserved=True,window_metadata_removed=True),indent=2))
            print('Real interval XLSX contains all events with exact times and no processing-window columns',flush=True)
            async def snapshot():
                return await c.js('Object.values(window.__drillmateSnapshotProviders).at(-1)()')
            before=await snapshot()
            await c.js(prefix+'Array.from(d.querySelectorAll("button")).find(b=>b.textContent.includes("Tagging")).click();f.scrollIntoView({block:"start",behavior:"instant"});})()')
            await asyncio.sleep(.35)
            points=await c.js(prefix+'const r=g.getBoundingClientRect(),p=f.getBoundingClientRect(),x=p.left+r.left+a.xaxis4._offset+a.xaxis4.d2p(.24),y=p.top+r.top+a.yaxis4._offset;return {x,start:y+a.yaxis4._length*.35,end:y+a.yaxis4._length*.42};})()')
            await c.drag(points['x'],points['start'],points['end']);await asyncio.sleep(.15)
            current=await snapshot()
            assert len(current['tags'])==len(before['tags'])+1,current
            files_before={str(p):p.stat().st_mtime_ns for p in downloads.glob('*.json')}
            await c.call('Runtime.evaluate',dict(expression='Array.from(document.querySelectorAll("iframe")).find(f=>f.contentDocument?.getElementById("save_dashboard_with_drawn_tags_btn")).contentDocument.getElementById("save_dashboard_with_drawn_tags_btn").click()',userGesture=True))
            file=None
            for _ in range(80):
                fresh=[p for p in downloads.glob('*.json') if str(p) not in files_before or p.stat().st_mtime_ns!=files_before[str(p)]]
                if fresh:file=max(fresh,key=lambda p:p.stat().st_mtime_ns);break
                await asyncio.sleep(.1)
            assert file is not None,'No downloaded session'
            saved=json.loads(file.read_text())
            assert saved['tag_intervals']==current['tags']
            assert len(saved['hit_results'])==len(current['tags'])
            dom=await c.call('DOM.getDocument',dict(depth=1))
            node=await c.call('DOM.querySelector',dict(nodeId=dom['root']['nodeId'],selector='input[type=file]'))
            await c.call('DOM.setFileInputFiles',dict(nodeId=node['nodeId'],files=[str(file)]))
            for _ in range(240):
                restored=await snapshot()
                if restored['browser_session_token']!=current['browser_session_token'] and restored['tags']==current['tags']:break
                await asyncio.sleep(.25)
            assert restored['tags']==current['tags'] and restored['browser_session_token']!=current['browser_session_token']
            assert restored['viewport_start']==current['viewport_start']
            (driver.OUT/'draw-save-restore.json').write_text(json.dumps(dict(passed=True,before=before,current=current,restored=restored),indent=2))
            print('Real-log draw → immediate download → upload: exact tags, IDs and view restored',flush=True)
            await c.js('(()=>{const s=Array.from(document.querySelectorAll("summary")).find(s=>s.textContent.includes("Final validation"));if(!s.closest("details").open)s.click();Array.from(document.querySelectorAll("button")).find(b=>b.textContent.includes("Run built-in engine self-test")).click();})()')
            await c.wait_js('document.body.innerText.includes("Both production validation engines calculated the expected synthetic results.")',timeout=60)
            assert (await snapshot())['tags']==current['tags']
            print('Visible independent-validation self-test passed and preserved all expert tags',flush=True)
            inventory=await c.js('(()=>{return {text:document.body.innerText,labels:Array.from(document.querySelectorAll("label,summary")).map(e=>e.textContent),frames:Array.from(document.querySelectorAll("iframe")).map(f=>({src:f.src,buttons:Array.from(f.contentDocument?.querySelectorAll("button")||[]).map(b=>b.textContent)}))};})()')
            (driver.OUT/'visible-interface.json').write_text(json.dumps(inventory,indent=2))
        assert not [e for e in c.events if e.get('method')=='Runtime.exceptionThrown']
        assert not [e for e in c.events if e.get('method')=='Runtime.consoleAPICalled' and e['params'].get('type')=='error']
        assert not await c.js('!!document.querySelector("[data-testid=stException]")')


def main(argv=None):
    global CONFIG
    p=argparse.ArgumentParser();p.add_argument('--well',default='34-10-C47');p.add_argument('--section',default='12.25');p.add_argument('--agent',default='TRQSpike');p.add_argument('--date',action='append',default=[]);p.add_argument('--rapid',action='store_true');p.add_argument('--workflow',action='store_true');p.add_argument('--paging',action='store_true');p.add_argument('--out-dir')
    CONFIG=p.parse_args(argv)
    if not CONFIG.date:CONFIG.date=['2006-02-06']
    driver.FIXTURE=driver.ROOT/'tools/agent_interval_real_log_fixture.py'
    driver.OUT=driver.ROOT/f'docs/agent_interval_navigation_context_2026-11-11/real-navigation/{CONFIG.well}-{CONFIG.section}-{CONFIG.agent}'
    if CONFIG.out_dir:driver.OUT=driver.ROOT/CONFIG.out_dir
    driver.exercise=exercise
    sys.argv=[sys.argv[0]]
    driver.main()


if __name__=='__main__':main()
