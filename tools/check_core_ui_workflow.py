"""End-to-end UI work preservation with actual browser downloads and uploads."""
import asyncio
import base64
import html
from openpyxl import load_workbook
import re
from datetime import datetime
import json
import sys
import time
import websockets
import check_agent_interval_navigation as driver


async def click_active_session_save(c):
    """Click the current editor's real button, respecting Streamlit's stale DOM."""
    prefix='''(()=>{const s=JSON.parse(document.querySelector("pre code").textContent);
      const f=Array.from(document.querySelectorAll("iframe")).find(f=>{
        const d=f.contentDocument,t=d?.querySelector("script")?.textContent||"";
        return d?.getElementById("save_dashboard_with_drawn_tags_btn")
          && t.includes("const browserSessionToken = "+JSON.stringify(s.token)+";")
          && t.includes("const contextKey = "+JSON.stringify(s.context)+";");});
      const d=f?.contentDocument,b=d?.getElementById("save_dashboard_with_drawn_tags_btn");'''
    for _ in range(80):
        p=await c.js(prefix+'''if(!b)return null;f.scrollIntoView({block:"center",behavior:"instant"});
          const r=b.getBoundingClientRect(),q=f.getBoundingClientRect();
          return {x:q.left+r.left+r.width/2,y:q.top+r.top+r.height/2};})()''')
        if p:
            await c.call('Input.dispatchMouseEvent',dict(type='mouseMoved',**p))
            await asyncio.sleep(.15)
            current=await c.js(prefix+'''if(!b)return null;const r=b.getBoundingClientRect(),q=f.getBoundingClientRect();
              const x=q.left+r.left+r.width/2,y=q.top+r.top+r.height/2;
              return {x,y,hit:document.elementFromPoint(x,y)===f&&d.elementFromPoint(r.left+r.width/2,r.top+r.height/2)===b};})()''')
            if current and current['hit'] and abs(current['x']-p['x'])<.5 and abs(current['y']-p['y'])<.5:
                await c.js('''(()=>{window.__auditSaveEvents=[];for(const w of [window,...Array.from(document.querySelectorAll("iframe")).map(f=>f.contentWindow)]){
                  try{const d=w.document;if(d.__auditPhysicalSave)continue;d.__auditPhysicalSave=true;
                    for(const type of ["pointerdown","pointerup","mousedown","mouseup","click"])d.addEventListener(type,e=>window.__auditSaveEvents.push({type,target:e.target.id||e.target.tagName,x:e.clientX,y:e.clientY}),true);
                  }catch(e){}}})()''')
                await c.click(current['x'],current['y'])
                result=await c.js(prefix+'return {editor:s.token,text:d?.body.innerText,position:'+json.dumps(current)+',events:window.__auditSaveEvents};})()')
                if any(e.get('type')=='click' and e.get('target')=='save_dashboard_with_drawn_tags_btn' for e in result['events']):
                    return result
        await asyncio.sleep(.15)
    raise AssertionError('The active session Save button never became clickable')


async def exercise(ws_url,url,inspect_only):
    downloads=driver.OUT/'downloads';downloads.mkdir(parents=True,exist_ok=True)
    uploads=driver.OUT/'uploads';uploads.mkdir(exist_ok=True)
    async with websockets.connect(ws_url,max_size=50_000_000) as ws:
        c=driver.CDP(ws)
        await c.call('Runtime.enable');await c.call('Page.enable')
        await c.call('Emulation.setDeviceMetricsOverride',dict(width=2100,height=2000,deviceScaleFactor=1,mobile=False))
        await c.call('Emulation.setTimezoneOverride',dict(timezoneId='UTC'))
        await c.call('Browser.setDownloadBehavior',dict(behavior='allow',downloadPath=str(downloads),eventsEnabled=True))
        await c.call('Page.navigate',dict(url=url))
        prefix=driver.PLOT_PREFIX
        async def server():return json.loads(await c.js('document.querySelector("pre code").textContent'))
        async def ready(previous=None):
            await c.wait_js(prefix+'''try{const s=JSON.parse(document.querySelector("pre code").textContent);
              return !!a && !!window.__drillmateSnapshotProviders?.[s.context+"_"+s.token]
                '''+('&& s.token!=='+json.dumps(previous) if previous else '')+''';}catch(e){return false;}})()''',timeout=60)
            await asyncio.sleep(.6)
        await ready()
        async def view(body):return await c.js(prefix+body+'})()')
        async def snapshot():
            return await c.js('(()=>{const s=JSON.parse(document.querySelector("pre code").textContent);return window.__drillmateSnapshotProviders[s.context+"_"+s.token]();})()')
        async def chart_button(text):
            await view('Array.from(d.querySelectorAll("button")).find(b=>b.textContent.includes('+json.dumps(text)+')).click();return true;')
            await asyncio.sleep(.3)
        async def point(time,track=4,x=.24):
            return await view('const r=g.getBoundingClientRect(),p=f.getBoundingClientRect(),x=a.'+('xaxis' if track==1 else 'xaxis'+str(track))+',y=a.'+('yaxis' if track==1 else 'yaxis'+str(track))+';return {x:p.left+r.left+x._offset+x.d2p('+str(x)+'),y:p.top+r.top+y._offset+y.d2p('+json.dumps(time)+')};')
        async def show_chart():
            await view('f.scrollIntoView({block:"start",behavior:"instant"});return true;')
            await asyncio.sleep(.25)
        async def wait_tags(count):
            await c.wait_js(prefix+'return g?.data.filter(t=>t.meta?.source==="tag").length==='+str(count)+';})()')
        async def save(label):
            old={str(p):p.stat().st_mtime_ns for p in downloads.glob('*.json')}
            if getattr(driver,'PHYSICAL_SAVE',False):
                response=await click_active_session_save(c)
            else:
                response=await c.call('Runtime.evaluate',dict(expression='(()=>{const f=Array.from(document.querySelectorAll("iframe")).find(f=>f.contentDocument?.getElementById("save_dashboard_with_drawn_tags_btn"));const d=f.contentDocument;const before=d.body.innerText;d.getElementById("save_dashboard_with_drawn_tags_btn").click();return {before,after:d.body.innerText,url:location.href,frameConnected:f.isConnected,ready:d.readyState};})()',returnByValue=True,userGesture=True))
            (driver.OUT/(label+'-click.json')).write_text(json.dumps(response,indent=2))
            for _ in range(80):
                files=[p for p in downloads.glob('*.json') if str(p) not in old or p.stat().st_mtime_ns!=old[str(p)]]
                if files:
                    payload=json.loads(max(files,key=lambda p:p.stat().st_mtime_ns).read_text())
                    (driver.OUT/(label+'.json')).write_text(json.dumps(payload,indent=2))
                    return payload
                await asyncio.sleep(.1)
            status=await c.js('Array.from(document.querySelectorAll("iframe")).find(f=>f.contentDocument?.getElementById("save_dashboard_with_drawn_tags_btn"))?.contentDocument.body.innerText')
            raise AssertionError('No session download: '+str(status))
        async def upload(payload,label):
            previous=(await server())['token']
            folder=uploads/label;folder.mkdir(exist_ok=True)
            path=folder/'same.json';path.write_text(json.dumps(payload))
            dom=await c.call('DOM.getDocument',dict(depth=1))
            node=await c.call('DOM.querySelector',dict(nodeId=dom['root']['nodeId'],selector='input[type=file]'))
            await c.call('DOM.setFileInputFiles',dict(nodeId=node['nodeId'],files=[str(path)]))
            await ready(previous)
            return path
        def identities(items):
            return {t['tag_id']:(t['start'],t['end'],t.get('label')) for t in items}
        checks=[]
        def record(text):
            checks.append(text);print(text,flush=True)
        async def fail_artifact():
            (driver.OUT/'failure-state.json').write_text(json.dumps(dict(server=await server(),snapshot=await snapshot()),indent=2))
            shot=await c.call('Page.captureScreenshot',dict(format='png'))
            (driver.OUT/'failure.png').write_bytes(base64.b64decode(shot['data']))
            events=[e for e in c.events if e.get('method') in ('Runtime.exceptionThrown','Runtime.consoleAPICalled',
                    'Browser.downloadWillBegin','Browser.downloadProgress','Network.webSocketClosed')]
            (driver.OUT/'failure-events.json').write_text(json.dumps(events,indent=2))

        try:
            await chart_button('Tagging');await show_chart()
            # Save before waiting for Python: live chart state must be complete.
            a,b=await point('2026-01-01 06:10:00'),await point('2026-01-01 06:40:00')
            await c.drag(a['x'],a['y'],b['y'])
            first=await save('draw-immediate')
            assert len(first['tag_intervals'])==len(first['hit_results'])==1
            tag=first['tag_intervals'][0]
            assert first['hit_results'][0]['tag_start']==tag['start']
            assert first['hit_results'][0]['tag_end']==tag['end']
            record('immediate Save after drawing preserves one tag, its ID and matching result bounds')
            await wait_tags(1);await asyncio.sleep(.8)

            # Final release differs from the last mousemove.
            await show_chart()
            middle=await point('2026-01-01 06:25:00')
            await c.click(middle['x'],middle['y'],2);await asyncio.sleep(.2)
            edge=await point(tag['end'])
            move=await point('2026-01-01 06:50:00')
            release=await point('2026-01-01 07:10:00')
            await c.call('Input.dispatchMouseEvent',dict(type='mousePressed',button='left',clickCount=1,**edge))
            await c.call('Input.dispatchMouseEvent',dict(type='mouseMoved',button='left',buttons=1,**move))
            await c.call('Input.dispatchMouseEvent',dict(type='mouseReleased',button='left',clickCount=1,**release))
            edited=await save('resize-immediate')
            resized=edited['tag_intervals'][0]
            assert resized['tag_id']==tag['tag_id']
            assert abs((datetime.fromisoformat(resized['end'])-datetime(2026,1,1,7,10)).total_seconds())<90,resized
            assert resized['edit_revision']>tag.get('edit_revision',1)
            assert edited['hit_results'][0]['tag_end']==resized['end']
            record('resize uses final release time, preserves ID and saves the newest boundaries immediately')
            blank=await point('2026-01-01 08:00:00',x=.95)
            await c.click(blank['x'],blank['y'])
            assert await view('return Array.from(d.querySelectorAll("button")).find(b=>b.textContent.includes("Delete selected")).disabled;')
            record('blank/adjacent-lane clicks deselect without deleting an expert tag')

            await show_chart()
            start=await point('2026-01-01 11:30:00')
            outside=await view('const r=g.getBoundingClientRect(),p=f.getBoundingClientRect();return p.top+r.top+a.yaxis._offset+a.yaxis._length+25;')
            await c.drag(start['x'],start['y'],outside)
            await wait_tags(2)
            second=await save('outside-release')
            assert len(second['tag_intervals'])==2
            last=max(second['tag_intervals'],key=lambda t:t['start'])
            assert last['end']=='2026-01-01 12:00:00',last
            record('a drag released outside the plot is captured and ends at the visible boundary')

            await chart_button('Small dots')
            saved=await save('two-tags-modes')
            assert saved['dashboard_state']['widget_state']['marker_display_W__8.5']=='Small dots'
            saved_ids=identities(saved['tag_intervals'])
            await upload(saved,'A')
            assert identities((await snapshot())['tags'])==saved_ids
            assert await view('return Array.from(d.querySelectorAll("button")).find(b=>b.textContent==="Small dots").classList.contains("active-blue");')
            record('session upload restores both tags and the visible curve-dot setting')

            changed=json.loads(json.dumps(saved))
            changed['dashboard_state']['widget_state']['sym_trq_window_W__8.5']=75
            await upload(changed,'B')
            assert (await server())['config']['trq_mean_long_window']==75
            assert identities((await snapshot())['tags'])==saved_ids
            record('same filename with changed contents restores the saved agent threshold before computation')
            await upload(saved,'A-return')
            assert (await server())['config']['trq_mean_long_window']==60
            assert identities((await snapshot())['tags'])==saved_ids
            record('A → B → A upload replaces settings once and preserves exact absolute tag times')

            xls_before={str(p):p.stat().st_mtime_ns for p in downloads.glob('*.xls')}
            await chart_button('Download hit results Excel')
            for _ in range(80):
                files=[p for p in downloads.glob('*.xls') if str(p) not in xls_before or p.stat().st_mtime_ns!=xls_before[str(p)]]
                if files:break
                await asyncio.sleep(.1)
            assert files,'No hit-results spreadsheet download'
            cells=[html.unescape(v) for v in re.findall(r'<td>(.*?)</td>',files[0].read_text())]
            live_rows=(await snapshot())['hit_results']
            assert len(cells)==10*len(live_rows)
            assert cells[4::10]==[r['tag_start'] for r in live_rows]
            assert cells[5::10]==[r['tag_end'] for r in live_rows]
            await c.js(driver.TABLE_PREFIX+'Array.from(d.querySelectorAll("button")).find(b=>b.textContent.includes("Download Excel")).click();})()')
            for _ in range(80):
                files=list(downloads.glob('*.xlsx'))
                if files:break
                await asyncio.sleep(.1)
            assert files,'No agent-interval Excel download'
            workbook=load_workbook(files[0]);sheet=workbook.active
            values=list(sheet.values);exported=[dict(zip(values[0],row)) for row in values[1:]]
            assert not {'window','window_start','window_end'} & {str(v).lower() for v in values[0]}
            assert [r['Start'].strftime('%Y-%m-%d %H:%M:%S') for r in exported]==[r['start'] for r in (await snapshot())['agent_intervals']]
            assert [r['End'].strftime('%Y-%m-%d %H:%M:%S') for r in exported]==[r['end'] for r in (await snapshot())['agent_intervals']]
            record('hit-results spreadsheet and editable interval XLSX preserve exact event times without window metadata')

            # A complete loss of browser storage must not prevent file export.
            await ready();await show_chart()
            await view('w=g.ownerDocument.defaultView;w.__auditStorageSet=w.Storage.prototype.setItem;w.Storage.prototype.setItem=function(){throw new DOMException("audit quota","QuotaExceededError")};return true;')
            if not await view('return d.querySelector(".vlv-capture").classList.contains("active");'):await chart_button('Tagging')
            a,b=await point('2026-01-01 05:00:00'),await point('2026-01-01 05:30:00')
            await c.drag(a['x'],a['y'],b['y'])
            quota=await save('quota-live-save')
            assert len(quota['tag_intervals'])==3,quota
            assert len(quota['hit_results'])==3
            record('Save downloads the newest three-tag state even when browser storage throws quota errors')
            await view('const w=g.ownerDocument.defaultView;w.Storage.prototype.setItem=w.__auditStorageSet;return true;')
            await chart_button('Large dots');await asyncio.sleep(.7)
            before_refresh=await snapshot();old_owner=(await server())['token']
            assert len(before_refresh['tags'])==3
            await c.call('Page.reload')
            await ready()
            assert (await server())['token']!=old_owner
            assert (await snapshot())['tags']==[]
            recovery='(()=>{const f=Array.from(document.querySelectorAll("iframe")).find(f=>f.contentDocument?.querySelector("[data-draft-owner]"));const d=f?.contentDocument;'
            await c.wait_js(recovery+'return !!d?.querySelector("[data-draft-owner="+CSS.escape('+json.dumps(old_owner)+')+"]");})()')
            refresh_owner=(await server())['token']
            await c.js(recovery+'const details=d.querySelector("details");details.open=true;d.querySelector("[data-draft-owner="+CSS.escape('+json.dumps(old_owner)+')+"] button").click();})()')
            await ready(refresh_owner)
            restored=await snapshot()
            assert identities(restored['tags'])==identities(before_refresh['tags'])
            assert restored['marker_display']=='Larger dots'
            record('refresh starts clean and explicit browser recovery restores all unsaved tags and dot settings')

            invalid=json.loads(json.dumps(saved))
            invalid['dashboard_state']['widget_state']['sym_trq_window_W__8.5']=0
            path=uploads/'invalid.json';path.write_text(json.dumps(invalid))
            owner=(await server())['token']
            dom=await c.call('DOM.getDocument',dict(depth=1))
            node=await c.call('DOM.querySelector',dict(nodeId=dom['root']['nodeId'],selector='input[type=file]'))
            await c.call('DOM.setFileInputFiles',dict(nodeId=node['nodeId'],files=[str(path)]))
            await c.wait_js('document.body.innerText.includes("Invalid range for sym_trq_window")')
            assert (await server())['token']==owner
            assert identities((await snapshot())['tags'])==identities(restored['tags'])
            record('an invalid saved threshold is rejected without replacing the active expert work')
            await upload(saved,'valid-after-invalid')
            await wait_tags(2)
            empty=json.loads(json.dumps(saved))
            empty.update(tag_intervals=[],drawn_tag_intervals=[],tag_ledger=[],hit_results=[])
            await upload(empty,'empty')
            assert (await snapshot())['tags']==[]
            assert (await save('empty-saved'))['tag_intervals']==[]
            await upload(saved,'after-empty')
            assert identities((await snapshot())['tags'])==saved_ids
            record('explicit empty session stays empty and reloading the tagged file restores deleted IDs')

            # Exercise the actual visible deletion control, including removing
            # the last tag and saving before any Python-side synchronization.
            for remaining in [1,0]:
                await ready();await show_chart()
                item=(await snapshot())['tags'][0]
                middle=datetime.fromisoformat(item['start'])+(datetime.fromisoformat(item['end'])-datetime.fromisoformat(item['start']))/2
                p=await point(middle.isoformat(sep=' '))
                await c.click(p['x'],p['y'],2);await asyncio.sleep(.2)
                await chart_button('Delete selected')
                deleted=await save('actual-delete-'+str(remaining))
                assert len(deleted['tag_intervals'])==len(deleted['hit_results'])==remaining
                await wait_tags(remaining)
            assert len((await snapshot())['deleted_tag_ids'])==2
            await upload(saved,'after-real-deletion')
            assert identities((await snapshot())['tags'])==saved_ids
            record('visible Delete removes each tag, last-tag Save is empty, and file restore revives the original IDs')

            other=json.loads(json.dumps(saved).replace('W__8.5','Other__8.5'))
            other['dashboard_context']['selected_well']='Other'
            other_tag=dict(saved['tag_intervals'][0],tag_id='other-well-tag',label='Other well expert tag',
                           start='2026-01-01 10:00:00',end='2026-01-01 10:10:00')
            other.update(tag_intervals=[other_tag],drawn_tag_intervals=[other_tag],tag_ledger=[other_tag],hit_results=[])
            await upload(other,'other-well')
            current=await snapshot()
            assert current['selected_well']=='Other' and len(current['tags'])==1
            assert current['tags'][0]['tag_id']=='other-well-tag'
            other_saved=await save('other-well-saved')
            assert other_saved['dashboard_context']['selected_well']=='Other'
            assert other_saved['hit_results'][0]['well']=='Other'
            await upload(saved,'return-original-well')
            assert (await snapshot())['selected_well']=='W'
            assert identities((await snapshot())['tags'])==saved_ids
            record('switching wells via a session file and returning restores only that well’s tags and result context')

            errors=[e for e in c.events if e.get('method')=='Runtime.exceptionThrown']
            assert not errors,errors
            (driver.OUT/'results.json').write_text(json.dumps(dict(passed=True,checks=checks),indent=2))
            print(json.dumps(dict(passed=True,checks=checks),indent=2),flush=True)
        except BaseException:
            await fail_artifact()
            raise


if __name__=='__main__':
    driver.FIXTURE=driver.ROOT/'tools/core_ui_workflow_fixture.py'
    driver.OUT=driver.ROOT/'docs/core_ui_reliability_2026-11-11/workflow'
    driver.exercise=exercise;sys.argv=[sys.argv[0]];driver.main()
