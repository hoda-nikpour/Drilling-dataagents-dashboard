"""Real table clicks and viewer navigation in an isolated Streamlit/Chrome run."""
import argparse
import asyncio
import base64
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import websockets

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/agent_interval_navigation_2026-11-11/evidence'
FIXTURE=ROOT/'tools/agent_interval_navigation_fixture.py'
from browser_cdp import CDP
PLOT_PREFIX='(()=>{const f=Array.from(document.querySelectorAll("iframe")).find(f=>f.contentDocument?.querySelector(".vlv-plot"));const d=f?.contentDocument,g=d?.querySelector(".vlv-plot"),a=g?._fullLayout;'
TABLE_PREFIX='(()=>{const f=Array.from(document.querySelectorAll("iframe")).find(f=>f.contentDocument?.querySelector(".ait-root"));const d=f?.contentDocument;'


async def table_click(c, expression):
    """Click the actual table control, including its containing iframe offset."""
    await c.js('(()=>{const s=Array.from(document.querySelectorAll("summary")).find(s=>s.textContent.includes("Agent intervals"));if(!s.closest("details").open)s.click();})()')
    await c.wait_js(TABLE_PREFIX+'return !!d;})()')
    await c.js(TABLE_PREFIX+'f.scrollIntoView({block:"center",behavior:"instant"});const e='+expression+';e?.scrollIntoView({block:"nearest",inline:"nearest",behavior:"instant"});})()')
    for _ in range(40):
        rect=await c.js(TABLE_PREFIX+'const e='+expression+';if(!e)return null;const r=e.getBoundingClientRect(),p=f.getBoundingClientRect();return {x:p.left+r.left+r.width/2,y:p.top+r.top+r.height/2};})()')
        if rect is None:
            await asyncio.sleep(.2)
            continue
        await c.call('Input.dispatchMouseEvent',dict(type='mouseMoved',**rect))
        await asyncio.sleep(.2)
        current=await c.js(TABLE_PREFIX+'const e='+expression+';if(!e)return null;const r=e.getBoundingClientRect(),p=f.getBoundingClientRect();return {x:p.left+r.left+r.width/2,y:p.top+r.top+r.height/2};})()')
        hit=await c.js(TABLE_PREFIX+'const e='+expression+';if(!e)return false;const r=e.getBoundingClientRect(),p=f.getBoundingClientRect();const x=r.left+r.width/2,y=r.top+r.height/2;const child=d.elementFromPoint(x,y);return document.elementFromPoint(p.left+x,p.top+y)===f && (child===e || e.contains(child));})()')
        if current and abs(current['y']-rect['y'])<.5 and hit:
            await c.click(rect['x'],rect['y'])
            return
    raise AssertionError('Table control did not settle before clicking: '+expression)


async def table_search(c, query):
    await table_click(c,'d.querySelector("input")')
    # Use the native setter so React observes an actual input value change.
    await c.js(TABLE_PREFIX+'const e=d.querySelector("input");Object.getOwnPropertyDescriptor(d.defaultView.HTMLInputElement.prototype,"value").set.call(e,'+json.dumps(query)+');e.dispatchEvent(new d.defaultView.Event("input",{bubbles:true}));})()')
    await asyncio.sleep(.2)


async def select_agent(c, name):
    await c.js('document.querySelector("[role=combobox]").scrollIntoView({block:"center",behavior:"instant"});document.querySelector("[role=combobox]").click()')
    await c.wait_js('Array.from(document.querySelectorAll("[role=option]")).some(o=>o.textContent.trim()==='+json.dumps(name)+')')
    await c.js('Array.from(document.querySelectorAll("[role=option]")).find(o=>o.textContent.trim()==='+json.dumps(name)+').click()')
    await c.wait_js('document.body.innerText.includes('+json.dumps('Selected agent: '+name)+')')


async def exercise(ws_url,url,inspect_only):
    async with websockets.connect(ws_url,max_size=30_000_000) as ws:
        c=CDP(ws)
        await c.call('Runtime.enable');await c.call('Page.enable')
        await c.call('Page.addScriptToEvaluateOnNewDocument',dict(source='window.tableClicks=[];window.plannedClicks=[];document.addEventListener("pointerdown",e=>{const t=document.querySelector("[data-testid=stDataFrame]");window.tableClicks.push({x:e.clientX,y:e.clientY,target:e.target.outerHTML?.slice(0,250),rect:t?.getBoundingClientRect().toJSON()});},true);'))
        await c.call('Emulation.setDeviceMetricsOverride',dict(width=1900,height=1500,deviceScaleFactor=1,mobile=False))
        await c.call('Page.navigate',dict(url=url))
        await c.wait_js('document.body.innerText.includes("Agent intervals")',timeout=45)
        await c.js('Array.from(document.querySelectorAll("summary")).find(s=>s.textContent.includes("Agent intervals")).click()')
        prefix=PLOT_PREFIX
        await c.wait_js(prefix+'return !!a;})()',timeout=45)
        await asyncio.sleep(.5)
        if inspect_only:
            print(await c.js('(()=>{const t=document.querySelector("[data-testid=stDataFrame]");return {text:t?.innerText,html:t?.outerHTML.slice(0,5000),canvases:Array.from(t?.querySelectorAll("canvas")||[]).map(c=>({rect:c.getBoundingClientRect().toJSON(),role:c.getAttribute("role")}))}})()'),flush=True)
            shot=await c.call('Page.captureScreenshot',dict(format='png',captureBeyondViewport=True))
            (OUT/'inspect.png').write_bytes(base64.b64decode(shot['data']))
            return
        checks=[]
        def record(message):
            checks.append(message)
            print(message,flush=True)
        async def view(body):return await c.js(prefix+body+'})()')
        async def state():
            return await view('return {start:Math.min(...a.yaxis.range.map(t=>new Date(t).getTime())),end:Math.max(...a.yaxis.range.map(t=>new Date(t).getTime())),span:Math.abs(new Date(a.yaxis.range[0])-new Date(a.yaxis.range[1])),input:d.querySelector("input[type=datetime-local]").value,tags:g.data.filter(t=>t.meta?.source==="tag").map(t=>({id:t.meta.id,start:t.y[0],end:t.y.at(-1)})),firstCurve:g.data.find(t=>t.meta?.label==="TRQ")?.y[0]};')
        async def fixture():return json.loads(await c.js('document.querySelector("pre code").textContent'))
        async def cell(row,column='start'):
            if row is None: expression='d.querySelector("button[data-sort-column=start]")'
            elif isinstance(row,str): expression='Array.from(d.querySelectorAll("button[data-interval-start]")).find(b=>b.dataset.intervalStart==='+json.dumps(row)+')'
            else: expression='d.querySelectorAll("tbody tr")['+str(row)+'].querySelector('+json.dumps('button.ait-start' if column=='start' else 'td[data-column="'+column+'"]')+')'
            await table_click(c,expression)
        async def wait_start(text):
            try:
                await c.wait_js(prefix+'return !!a && Math.abs(Math.min(...a.yaxis.range.map(t=>new Date(t).getTime()))-new Date('+json.dumps(text)+').getTime())<1000;})()',timeout=30)
                await c.wait_js('(()=>{try{return JSON.parse(document.querySelector("pre code").textContent).start==='+json.dumps(text)+';}catch(e){return false;}})()',timeout=30)
                await c.wait_js(prefix+'try{return Math.abs(JSON.parse(document.querySelector("pre code").textContent).span*1000-Math.abs(new Date(a.yaxis.range[0])-new Date(a.yaxis.range[1])))<1500;}catch(e){return false;}})()',timeout=30)
            except AssertionError:
                failure=dict(expected=text,chart=await state(),server=await fixture(),
                    table=await c.js('document.querySelector("[data-testid=stDataFrame]")?.getBoundingClientRect().toJSON()'),clicks=await c.js('window.tableClicks'),planned=await c.js('window.plannedClicks'))
                (OUT/'browser-failure.json').write_text(json.dumps(failure,indent=2))
                shot=await c.call('Page.captureScreenshot',dict(format='png',captureBeyondViewport=True))
                (OUT/'browser-failure.png').write_bytes(base64.b64decode(shot['data']))
                raise
            # Let the app's delayed smooth scroll to the chart finish before
            # sending the next mouse gesture into a different page location.
            await asyncio.sleep(1.3)
        async def wait_target(text):
            span=(await state())['span']/1000
            target=datetime.fromisoformat(text)-timedelta(seconds=span/12)
            target=max(datetime(2026,1,1),min(target,datetime(2026,1,3)-timedelta(seconds=span)))
            expected=target.replace(microsecond=0).isoformat(sep=' ')
            await wait_start(expected)
            return expected
        first=await state()
        assert first['tags'][0]['id']=='chart_drag|expert-original'
        await cell(0)
        await wait_target('2026-01-01 03:00:00')
        assert (await fixture())['start']=='2026-01-01 02:00:00'
        assert (await state())['input']=='2026-01-01T02:00'
        record('Start click shows one hour before the event in the 12-hour viewport')

        await c.js(prefix+'f.scrollIntoView({block:"start",behavior:"instant"});})()')
        await asyncio.sleep(.2)
        async def point(text):
            return await view('const fr=f.getBoundingClientRect(),r=g.getBoundingClientRect();return {x:fr.left+r.left+a.xaxis._offset+a.xaxis.d2p(.5),y:fr.top+r.top+a.yaxis._offset+a.yaxis.d2p('+json.dumps(text)+')};')
        p=await point('2026-01-01 03:01:00');q=await point('2026-01-01 03:31:00')
        await c.drag(p['x'],p['y'],q['y']);await asyncio.sleep(.5)
        zoomed=await state()
        assert 1400_000<zoomed['span']<2200_000,zoomed
        # The Python viewport still has 12 h here; the jump must retain live zoom.
        assert (await fixture())['span']==43200
        await cell(1)
        expected=await wait_target('2026-01-02 06:15:00')
        late=await state();loaded=await fixture()
        assert abs(late['span']-zoomed['span'])<1500,(zoomed,late)
        assert abs(loaded['span']*1000-zoomed['span'])<1500
        assert loaded['buffer_start']==(datetime.fromisoformat(expected)-timedelta(hours=4)).isoformat(sep=' '),loaded
        curve_start=datetime.fromisoformat(late['firstCurve'])
        assert 0<=(curve_start-datetime.fromisoformat(loaded['buffer_start'])).total_seconds()<4,late
        assert datetime.fromisoformat(late['input'])==datetime.fromisoformat(expected)
        assert late['tags']==first['tags']
        record('out-of-buffer jump loads target raw data and preserves live 30-minute zoom and expert tag')

        await c.js('Array.from(document.querySelectorAll("button")).find(b=>b.textContent.includes("Unrelated rerun")).click()')
        await asyncio.sleep(.8)
        assert abs((await state())['start']-late['start'])<1000
        await view('d.querySelector(".vlv-scroll-arrow-down").dispatchEvent(new MouseEvent("dblclick",{bubbles:true}));return true;')
        await c.wait_js(prefix+'return Math.min(...a.yaxis.range.map(t=>new Date(t).getTime()))>'+str(late['start']+3600_000)+';})()')
        await asyncio.sleep(.6)
        moved=await state()
        await c.js('Array.from(document.querySelectorAll("button")).find(b=>b.textContent.includes("Unrelated rerun")).click()')
        await asyncio.sleep(.7)
        assert abs((await state())['start']-moved['start'])<1000
        record('later navigation and unrelated reruns do not replay an earlier table click')

        await cell(1)
        await wait_target('2026-01-02 06:15:00')
        assert abs((await state())['span']-zoomed['span'])<1500
        record('same Start cell can be clicked again after browsing elsewhere')
        before=(await state())['start'];generation=(await fixture())['generation']
        await cell(0,'end');await asyncio.sleep(.7)
        assert abs((await state())['start']-before)<1000
        assert (await fixture())['generation']==generation
        record('clicking an End cell does not move the plot')

        await cell(2)
        await c.wait_js(prefix+'return !!a && Math.abs(Math.max(...a.yaxis.range.map(t=>new Date(t).getTime()))-new Date("2026-01-03 00:00:00").getTime())<1000;})()')
        await asyncio.sleep(.4)
        tail=await state()
        await c.wait_js('(()=>{try{return Math.abs(new Date(JSON.parse(document.querySelector("pre code").textContent).start).getTime()-'+str(tail['start'])+')<1000;}catch(e){return false;}})()',timeout=30)
        await asyncio.sleep(.3)
        tail=await state()
        assert tail['firstCurve'].startswith('2026-01-02 19:'),tail
        assert abs(tail['span']-zoomed['span'])<1500
        assert tail['start']<tail['end']-9*60_000
        assert tail['tags']==first['tags']
        record('near-section-end jump loads the destination buffer and retains time scale with fractional zoom span')

        # Move away first so a failed sorted click cannot pass by staying put.
        await cell(0)
        await wait_target('2026-01-01 03:00:00')
        await cell(None)
        await asyncio.sleep(.2)
        rows=await c.js(TABLE_PREFIX+'return Array.from(d.querySelectorAll("tbody tr")).map(r=>r.textContent);})()')
        assert '2026-01-02 23:50' in rows[0],rows
        await cell(0)
        await c.wait_js(prefix+'return !!a && Math.abs(Math.max(...a.yaxis.range.map(t=>new Date(t).getTime()))-new Date("2026-01-03 00:00:00").getTime())<1000;})()')
        await asyncio.sleep(.4)
        assert abs((await state())['span']-zoomed['span'])<1500
        record('sorted table Start clicks navigate to the displayed interval, not an incorrect source row')

        # A selected symptom agent uses exactly the same table navigation path.
        await select_agent(c,'TRQSpike')
        await c.wait_js(TABLE_PREFIX+'return d?.querySelector("tbody")?.textContent.includes("TRQSpike");})()')
        await cell('2026-01-01 03:00:00')
        await wait_target('2026-01-01 03:00:00')
        assert (await state())['tags']==first['tags']
        record('navigation works for a symptom agent after changing the agent selection')

        # Returning to the previous agent must not replay its earlier Start click.
        generation=(await fixture())['generation']
        await select_agent(c,'Drilling')
        await asyncio.sleep(.8)
        assert (await fixture())['generation']==generation
        assert datetime.fromisoformat((await state())['input'])==datetime.fromisoformat((await fixture())['start'])
        record('returning to a previous agent does not execute its old click')

        await table_search(c,'02.01.2026')
        rows=await c.js(TABLE_PREFIX+'return Array.from(d.querySelectorAll("tbody tr")).map(r=>r.textContent);})()')
        assert len(rows)==2 and all('2026-01-02' in row for row in rows),rows
        await cell('2026-01-02 06:15:00')
        await wait_target('2026-01-02 06:15:00')
        record('date search retains original row identities and navigates to the displayed timestamp')

        await c.js('Array.from(document.querySelectorAll("label")).find(l=>l.textContent.includes("Long interval list")).click()')
        await c.wait_js(TABLE_PREFIX+'return d?.querySelector(".ait-pager")?.textContent.includes("of 120 intervals");})()')
        await table_click(c,'d.querySelector(".ait-pager button:last-child")')
        await c.wait_js(TABLE_PREFIX+'return d.querySelector("button[data-interval-start]")?.dataset.intervalStart==="2026-01-02 00:50:00";})()')
        await cell(0)
        await wait_target('2026-01-02 00:50:00')
        assert (await state())['tags']==first['tags']
        record('second-page Start clicks in a 120-interval table preserve source identity and expert tags')
        await asyncio.sleep(.5)
        exceptions=[e for e in c.events if e.get('method')=='Runtime.exceptionThrown']
        errors=[e for e in c.events if e.get('method')=='Runtime.consoleAPICalled' and e['params'].get('type')=='error']
        assert not exceptions,exceptions
        assert not errors,errors
        assert not await c.js('document.querySelector("[data-testid=stException]")')
        result=dict(passed=True,checks=checks,initial=first,zoom_span_seconds=zoomed['span']/1000,
                    target=late,near_end=tail,browser='isolated Chrome and actual Streamlit table/viewer; synthetic four-second data')
        (OUT/'browser-results.json').write_text(json.dumps(result,indent=2))
        shot=await c.call('Page.captureScreenshot',dict(format='png',captureBeyondViewport=True))
        (OUT/'navigation.png').write_bytes(base64.b64decode(shot['data']))
        print(json.dumps(dict(passed=True,checks=checks),indent=2),flush=True)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--inspect',action='store_true');args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix='drillmate-interval-nav-') as profile,(OUT/'streamlit.log').open('w') as slog,(OUT/'chrome.log').open('w') as clog:
        server=subprocess.Popen([sys.executable,'-m','streamlit','run',str(FIXTURE),'--server.address=127.0.0.1','--server.port='+str(port),'--server.headless=true','--browser.gatherUsageStats=false'],cwd=ROOT,stdout=slog,stderr=slog,start_new_session=True)
        browser=None
        try:
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                try:
                    if urllib.request.urlopen(f'http://127.0.0.1:{port}/_stcore/health',timeout=1).read()==b'ok':break
                except Exception:time.sleep(.2)
            browser=subprocess.Popen(['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome','--headless=new','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader','--disable-extensions','--disable-background-networking','--no-first-run','--no-default-browser-check','--remote-debugging-port=0','--user-data-dir='+profile,'about:blank'],stdout=clog,stderr=clog,start_new_session=True)
            portfile=Path(profile)/'DevToolsActivePort';deadline=time.monotonic()+15
            while not portfile.exists() and time.monotonic()<deadline:time.sleep(.1)
            debug_port=portfile.read_text().splitlines()[0]
            target=next(t for t in json.load(urllib.request.urlopen(f'http://127.0.0.1:{debug_port}/json/list')) if t['type']=='page')
            asyncio.run(exercise(target['webSocketDebuggerUrl'],f'http://127.0.0.1:{port}',args.inspect))
        finally:
            for proc in (browser,server):
                if proc and proc.poll() is None:
                    os.killpg(proc.pid,signal.SIGTERM)
                    try:proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL)

if __name__=='__main__':main()
