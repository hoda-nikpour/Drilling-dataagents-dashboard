"""Real Streamlit/Chrome paging, calendar, shortcuts and work preservation."""
import asyncio
import base64
from datetime import datetime,timedelta
import json
import sys
import websockets
import check_agent_interval_navigation as driver


async def exercise(ws_url,url,inspect_only):
    downloads=driver.OUT/'downloads';downloads.mkdir(parents=True,exist_ok=True)
    async with websockets.connect(ws_url,max_size=50_000_000) as ws:
        c=driver.CDP(ws)
        await c.call('Runtime.enable');await c.call('Page.enable')
        await c.call('Emulation.setDeviceMetricsOverride',dict(width=2100,height=2000,deviceScaleFactor=1,mobile=False))
        await c.call('Emulation.setTimezoneOverride',dict(timezoneId='UTC'))
        await c.call('Browser.setDownloadBehavior',dict(behavior='allow',downloadPath=str(downloads)))
        await c.call('Page.addScriptToEvaluateOnNewDocument',dict(source='''
          window.messages=[];window.heldPages=[];window.heldAcks=[];window.holdPages=false;window.holdAcks=false;
          window.addEventListener("message",e=>{
            if(e.data?.type!=="streamlit:setComponentValue")return;
            const v=e.data.value;if(v?.event)window.messages.push(v);
            if((window.holdPages&&v?.source==="time_page")||(window.holdAcks&&v?.source==="agent_interval")){
              (v.source==="time_page"?window.heldPages:window.heldAcks).push({data:e.data,source:e.source,origin:e.origin});
              e.stopImmediatePropagation();
            }
          },true);
        '''))
        await c.call('Page.navigate',dict(url=url))
        prefix=driver.PLOT_PREFIX
        async def view(body):return await c.js(prefix+body+'})()')
        async def server():return json.loads(await c.js('document.querySelector("pre code").textContent'))
        async def snapshot():return await c.js('(()=>{const s=JSON.parse(document.querySelector("pre code").textContent);return window.__drillmateSnapshotProviders[s.context+"_"+s.token]();})()')
        await c.wait_js(prefix+'return !!a && !!document.querySelector("pre code");})()',timeout=60)
        checks=[]
        def record(message):checks.append(message);print(message,flush=True)
        async def state():
            return await view('return {range:a.yaxis.range,span:Math.abs(new Date(a.yaxis.range[0])-new Date(a.yaxis.range[1]))/1000,input:d.querySelector("input[type=datetime-local]").value,tagging:d.querySelector(".vlv-capture").classList.contains("active"),loading:!!d.querySelector(".vlv-navigation-loading"),previous:d.querySelector(".vlv-time-navigation button:first-child").disabled,next:d.querySelector(".vlv-time-navigation button:last-child").disabled};')
        async def button(selector):
            # Use actual mouse input and wait for Streamlit's stale elements to
            # stop intercepting clicks, rather than invoking detached handlers.
            await view('const e=d.querySelector('+json.dumps(selector)+');f.scrollIntoView({block:"end",behavior:"instant"});e.scrollIntoView({block:"nearest",behavior:"instant"});return true;')
            for _ in range(60):
                p=await view('const e=d.querySelector('+json.dumps(selector)+');if(!e||e.disabled)return null;const r=e.getBoundingClientRect(),q=f.getBoundingClientRect();return {x:q.left+r.left+r.width/2,y:q.top+r.top+r.height/2};')
                if p:
                    await asyncio.sleep(.15)
                    hit=await view('const e=d.querySelector('+json.dumps(selector)+'),r=e.getBoundingClientRect(),q=f.getBoundingClientRect();return document.elementFromPoint(q.left+r.left+r.width/2,q.top+r.top+r.height/2)===f;')
                    if hit:await c.click(p['x'],p['y']);return
                await asyncio.sleep(.15)
            raise AssertionError('Control unavailable: '+selector)
        async def chart_button(label):
            # Stable data-independent selector for the existing toolbar.
            await view('Array.from(d.querySelectorAll(".vlv-toolbar button")).find(b=>b.textContent.includes('+json.dumps(label)+')).click();return true;')
            await asyncio.sleep(.25)
        async def point(text,track=1,x=.5):
            await view('f.scrollIntoView({block:"start",behavior:"instant"});return true;');await asyncio.sleep(.2)
            return await view('const r=g.getBoundingClientRect(),q=f.getBoundingClientRect(),x=a.'+('xaxis' if track==1 else 'xaxis'+str(track))+',y=a.'+('yaxis' if track==1 else 'yaxis'+str(track))+';return {x:q.left+r.left+x._offset+x.d2p('+str(x)+'),y:q.top+r.top+y._offset+y.d2p('+json.dumps(text)+')};')
        async def key(value):
            await c.call('Input.dispatchKeyEvent',dict(type='keyDown',key=value,code='Escape' if value=='Escape' else 'Key'+value.upper()))
            await c.call('Input.dispatchKeyEvent',dict(type='keyUp',key=value,code='Escape' if value=='Escape' else 'Key'+value.upper()))
            await asyncio.sleep(.3)
        async def focus_plot():await view('d.querySelector(".vlv-root").focus({preventScroll:true});return true;')
        async def ready(start,span=43200):
            await c.wait_js(prefix+'try{const s=JSON.parse(document.querySelector("pre code").textContent);return a.yaxis.range[1]==='+json.dumps(start)+' && s.view==='+json.dumps(start)+' && Math.abs(Math.abs(new Date(a.yaxis.range[0])-new Date(a.yaxis.range[1]))/1000-'+str(span)+')<1 && !d.querySelector(".vlv-navigation-loading");}catch(e){return false;}})()',timeout=60)
            await asyncio.sleep(.5)
        async def calendar(text):
            await view('const e=d.querySelector("input[type=datetime-local]");Object.getOwnPropertyDescriptor(d.defaultView.HTMLInputElement.prototype,"value").set.call(e,'+json.dumps(text.replace(' ','T'))+');e.dispatchEvent(new d.defaultView.Event("input",{bubbles:true}));return true;')
            await asyncio.sleep(.15)
            await button('.vlv-toolbar-time-jump button')
        async def save(label):
            old={str(p):p.stat().st_mtime_ns for p in downloads.glob('*.json')}
            await c.call('Runtime.evaluate',dict(expression='Array.from(document.querySelectorAll("iframe")).find(f=>f.contentDocument?.getElementById("save_dashboard_with_drawn_tags_btn")).contentDocument.getElementById("save_dashboard_with_drawn_tags_btn").click()',userGesture=True))
            for _ in range(80):
                fresh=[p for p in downloads.glob('*.json') if str(p) not in old or p.stat().st_mtime_ns!=old[str(p)]]
                if fresh:
                    file=max(fresh,key=lambda p:p.stat().st_mtime_ns);value=json.loads(file.read_text())
                    (driver.OUT/(label+'.json')).write_text(json.dumps(value,indent=2));return file,value
                await asyncio.sleep(.1)
            raise AssertionError('No session downloaded')
        previous='.vlv-time-navigation button:first-child'
        next_button='.vlv-time-navigation button:last-child'
        try:
            await ready('2026-01-01 00:00:00')
            labels=await view('return {calendar:d.querySelector(".vlv-toolbar-time-jump button").textContent,buttons:Array.from(d.querySelectorAll(".vlv-time-navigation button")).map(e=>e.textContent),below:d.querySelector(".vlv-time-navigation").getBoundingClientRect().top>=d.querySelector(".vlv-wrap").getBoundingClientRect().bottom};')
            assert labels==dict(calendar='Show selected time window',buttons=['Show previous 12 hours','Show next 12 hours'],below=True),labels
            assert (await state())['previous'] and not (await state())['next']
            record('calendar renamed, both paging buttons are below the plot, first boundary disables Previous')

            # Test the existing shortcuts and actual double-click zoom undo.
            await focus_plot();await key('z')
            p,q=await point('2026-01-01 03:00:00'),await point('2026-01-01 08:00:00')
            await c.drag(p['x'],p['y'],q['y']);await asyncio.sleep(.5)
            first=await state();assert 17000<first['span']<19000,first
            p,q=await point('2026-01-01 04:00:00'),await point('2026-01-01 06:00:00')
            await c.drag(p['x'],p['y'],q['y']);await asyncio.sleep(.5)
            assert 6800<(await state())['span']<7600
            p=await point('2026-01-01 05:00:00')
            await c.click(p['x'],p['y'],2);await asyncio.sleep(.65)
            assert abs((await state())['span']-first['span'])<1
            # Undo may synchronize an explicit viewport with Python. Wait for
            # the completed rerun before clicking a formerly stale iframe.
            await c.wait_js(prefix+'try{const s=JSON.parse(document.querySelector("pre code").textContent);return Math.abs(s.span-Math.abs(new Date(a.yaxis.range[0])-new Date(a.yaxis.range[1]))/1000)<1;}catch(e){return false;}})()')
            await asyncio.sleep(.3)
            p=await point('2026-01-01 05:00:00');await c.click(p['x'],p['y'],2);await asyncio.sleep(.65)
            assert (await state())['span']==43200
            record('Z + drag zooms; successive real mouse double-clicks undo exactly one zoom level each')
            await focus_plot();await key('t');assert (await state())['tagging']
            p,q=await point('2026-01-01 03:00:00',4,.24),await point('2026-01-01 03:20:00',4,.24)
            await c.call('Input.dispatchMouseEvent',dict(type='mousePressed',button='left',clickCount=1,**p))
            await c.call('Input.dispatchMouseEvent',dict(type='mouseMoved',button='left',buttons=1,**q))
            await key('Escape')
            await c.call('Input.dispatchMouseEvent',dict(type='mouseReleased',button='left',clickCount=1,**q))
            assert not (await snapshot())['tags']
            await c.drag(p['x'],p['y'],q['y']);await asyncio.sleep(.5)
            tags=(await snapshot())['tags'];assert len(tags)==1
            await focus_plot();await key('t');assert not (await state())['tagging']
            input_mode=await state()
            await view('d.querySelector("input[type=datetime-local]").focus();return true;');await key('t')
            assert (await state())['tagging']==input_mode['tagging']
            await focus_plot();await key('z')
            p,q=await point('2026-01-01 02:00:00'),await point('2026-01-01 04:00:00')
            await c.drag(p['x'],p['y'],q['y']);await asyncio.sleep(.4)
            await key('r');await asyncio.sleep(.4)
            assert (await state())['span']==43200
            record('T toggles tagging, Escape cancels an unfinished tag, editable input ignores T, R restores 12 hours')

            await calendar('2026-01-01 00:00:00');await ready('2026-01-01 00:00:00')
            for text in ['2026-01-01 12:00:00','2026-01-02 00:00:00','2026-01-02 12:00:00']:
                await button(next_button);await ready(text)
                assert (await snapshot())['tags']==tags
            assert (await state())['next']
            for text in ['2026-01-02 00:00:00','2026-01-01 12:00:00','2026-01-01 00:00:00']:
                await button(previous);await ready(text)
                assert (await snapshot())['tags']==tags
            record('three Next and three Previous clicks load the correct buffers, sync the calendar and preserve exact tags')

            await calendar('2026-01-01 18:30:00');await ready('2026-01-01 18:30:00')
            await button(next_button);await ready('2026-01-02 06:30:00')
            await button(previous);await ready('2026-01-01 18:30:00')
            file,saved=await save('paged-session')
            assert saved['tag_intervals']==tags
            assert saved['dashboard_state']['widget_state']['virtual_viewport_start_W__8.5']=='2026-01-01 18:30:00'
            owner=(await server())['token']
            dom=await c.call('DOM.getDocument',dict(depth=1));node=await c.call('DOM.querySelector',dict(nodeId=dom['root']['nodeId'],selector='input[type=file]'))
            await c.call('DOM.setFileInputFiles',dict(nodeId=node['nodeId'],files=[str(file)]))
            await c.wait_js('(()=>{try{return JSON.parse(document.querySelector("pre code").textContent).token!=='+json.dumps(owner)+';}catch(e){return false;}})()')
            await ready('2026-01-01 18:30:00');assert (await snapshot())['tags']==tags
            record('calendar and relative 12-hour paging at 18:30 agree; actual save/upload restores tags and viewport')

            await calendar('2026-01-02 20:00:00');await ready('2026-01-02 12:00:00')
            await focus_plot();await key('z')
            p,q=await point('2026-01-02 22:00:00'),await point('2026-01-02 23:00:00')
            await c.drag(p['x'],p['y'],q['y']);await asyncio.sleep(.4)
            zoom=await state();assert zoom['next']
            expected=(datetime.fromisoformat(zoom['range'][1])-timedelta(hours=12)).replace(microsecond=0).isoformat(sep=' ')
            await button(previous);await ready(expected)
            assert (await state())['span']==43200
            record('near section end Next cannot move backwards; Previous from a zoomed view restores a full 12-hour window')

            await calendar('2026-01-01 00:00:00');await ready('2026-01-01 00:00:00')
            await c.js('window.holdPages=true;window.heldPages=[]')
            for selector in [next_button,next_button,previous]:await button(selector)
            await c.wait_js('window.heldPages.length===3')
            values=await c.js('window.heldPages.map(e=>e.data.value)')
            assert [v['viewport_start'] for v in values]==['2026-01-01 12:00:00','2026-01-02 00:00:00','2026-01-01 12:00:00'],values
            await c.js('(()=>{window.holdPages=false;const e=window.heldPages.at(-1);window.dispatchEvent(new MessageEvent("message",{data:e.data,source:e.source,origin:e.origin}));})()')
            await ready('2026-01-01 12:00:00')
            await c.js('for(const e of window.heldPages.slice(0,2))window.dispatchEvent(new MessageEvent("message",{data:e.data,source:e.source,origin:e.origin}));')
            await asyncio.sleep(1)
            await ready('2026-01-01 12:00:00');assert (await snapshot())['tags']==tags
            record('rapid Next → Next → Previous finishes on the latest choice even when older messages arrive late')

            await c.js('window.holdAcks=true;window.heldAcks=[]')
            await driver.table_click(c,'Array.from(d.querySelectorAll("button[data-interval-start]")).find(b=>b.dataset.intervalStart==="2026-01-02 06:15:00")')
            await c.wait_js('window.heldAcks.length>=1')
            table_view=await state()
            expected=(datetime.fromisoformat(table_view['range'][1])-timedelta(hours=12)).isoformat(sep=' ')
            await button(previous);await ready(expected)
            await c.js('(()=>{window.holdAcks=false;for(const e of window.heldAcks)window.dispatchEvent(new MessageEvent("message",{data:e.data,source:e.source,origin:e.origin}));})()')
            await asyncio.sleep(1);await ready(expected)
            assert (await snapshot())['tags']==tags
            record('paging after an interval-table click supersedes its deliberately delayed acknowledgement')

            errors=[e for e in c.events if e.get('method')=='Runtime.exceptionThrown']
            assert not errors,errors
            assert not await c.js('!!document.querySelector("[data-testid=stException]")')
            result=dict(passed=True,checks=checks,labels=labels,final=await state())
            (driver.OUT/'browser-results.json').write_text(json.dumps(result,indent=2))
            shot=await c.call('Page.captureScreenshot',dict(format='png',captureBeyondViewport=True))
            (driver.OUT/'navigation.png').write_bytes(base64.b64decode(shot['data']))
        except BaseException:
            (driver.OUT/'failure.json').write_text(json.dumps(dict(server=await server(),chart=await state(),messages=await c.js('window.messages')),indent=2))
            shot=await c.call('Page.captureScreenshot',dict(format='png',captureBeyondViewport=True))
            (driver.OUT/'failure.png').write_bytes(base64.b64decode(shot['data']))
            raise


if __name__=='__main__':
    driver.OUT=driver.ROOT/'docs/time_window_navigation_2026-11-12/browser'
    driver.FIXTURE=driver.ROOT/'tools/core_ui_workflow_fixture.py'
    driver.exercise=exercise;sys.argv=[sys.argv[0]];driver.main()
