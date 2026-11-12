"""Exercise the built viewer in isolated Chrome with synthetic Streamlit inputs.

No production app session, well file, or existing browser storage is changed.
Use --baseline to exercise the saved pre-change bundle and record its failure.
"""
import argparse
import asyncio
import base64
import functools
import http.server
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import threading
import time
import urllib.request
import websockets

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/ui_plot_resize_fix_2026-11-11/evidence'
DIST = ROOT / 'streamlit_components/virtual_log_viewer/frontend/dist'
from browser_cdp import CDP

class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass

def inputs():
    times = [f'2026-01-01 {hour:02d}:00:00' for hour in range(24)]
    return dict(
        height=650, visible_hours=12, context_key='resize_fixture__8.5',
        browser_session_token='isolated-resize-check', selected_well='resize_fixture',
        selected_sections=['8.5'], selected_agent_name='Drilling', agent_source='Activity agent',
        section_start=times[0], section_end=times[-1], buffer_start=times[0], buffer_end=times[-1],
        viewport_start=times[0], show_agent_intervals=True,
        saved_tags=[dict(tag_id='existing-tag', source='chart_drag', label='Existing expert tag',
                         start=times[3], end=times[4], status='active')],
        agent_intervals=[dict(label='Drilling', start=times[3], end=times[6])],
        prediction_coverage=[dict(start=times[0], end=times[-1])],
        track_data=dict(time_start=times[0], time_end=times[-1], tracks=[
            dict(track=n, curves=[dict(label=label, unit='test', display_min=0, display_max=100,
                                      x=[20 + (h % 5)*10 for h in range(24)], y=times)])
            for n,label in [(1,'Torque'),(2,'WOB'),(3,'Pressure')]
        ]),
    )

async def exercise(ws_url, url, baseline):
    async with websockets.connect(ws_url, max_size=30_000_000) as ws:
        c=CDP(ws)
        await c.call('Runtime.enable'); await c.call('Page.enable')
        await c.call('Page.addScriptToEvaluateOnNewDocument',dict(source='window.addEventListener("message",e=>{if(e.data?.type==="streamlit:componentReady")window.viewerReady=true;});'))
        await c.call('Emulation.setDeviceMetricsOverride',dict(width=2400,height=1500,deviceScaleFactor=1,mobile=False))
        await c.call('Page.navigate',dict(url=url))
        try:
            await c.wait_js('window.viewerReady === true',timeout=10)
        except AssertionError:
            print(await c.js('({url:location.href,body:document.body.innerHTML})'),flush=True)
            print([e for e in c.events if e.get('method') in ('Runtime.exceptionThrown','Runtime.consoleAPICalled')],flush=True)
            raise
        await c.js('document.body.style.width="1000px"; window.postMessage('+json.dumps(dict(type='streamlit:render',args=inputs(),disabled=False))+',"*")')
        try:
            await c.wait_js('Boolean(document.querySelector(".vlv-plot")?._fullLayout)',timeout=15)
        except AssertionError:
            print(await c.js('document.body.innerText'),flush=True)
            print([e for e in c.events if e.get('method') in ('Runtime.exceptionThrown','Runtime.consoleAPICalled')],flush=True)
            raise
        await asyncio.sleep(.5)
        assert await c.js('!document.querySelector(".no-webgl")'),'Chrome must support WebGL for this UI check'
        prefix='(()=>{const g=document.querySelector(".vlv-plot"), f=g._fullLayout;'
        async def view(expr):return await c.js(prefix+expr+'})()')
        async def state():
            return await view('return {container:g.clientWidth,plot:f.width,height:f.height,ranges:Object.fromEntries(["xaxis","xaxis2","xaxis3","xaxis4","yaxis","yaxis2","yaxis3","yaxis4"].map(k=>[k,f[k].range])),tags:g.data.filter(t=>t.meta?.source==="tag").map(t=>({id:t.meta.id,start:t.y[0],end:t.y.at(-1),color:t.line.color})),curves:g.data.filter(t=>t.meta?.label&&!["agent","tag","overlap"].includes(t.meta?.source)).map(t=>({x:t.x,y:t.y})),history:Array.from(document.querySelectorAll("span")).find(s=>s.textContent.startsWith("Chart zoom undo history:"))?.textContent ?? null};')
        first=await state()
        await c.js('document.body.style.width="1800px"')
        if baseline:
            await asyncio.sleep(.7)
        else:
            await c.wait_js(prefix+'return Math.abs(g.clientWidth-f.width)<=1;})()')
        expanded=await state()
        if baseline:
            assert expanded['container']>first['container']+500
            assert expanded['container']-expanded['plot']>500
            result=dict(reproduced=True,initial=first,expanded=expanded)
            (OUT/'baseline.json').write_text(json.dumps(result,indent=2))
            print('Reproduced: container expanded to',expanded['container'],'but plot stayed at',expanded['plot'],flush=True)
            return
        assert abs(expanded['container']-expanded['plot'])<=1,expanded
        checks=['container-only expansion fills plot']
        async def point(time_text,track=1,x=.5):
            return await view(f'const r=g.getBoundingClientRect(),a=f.{"xaxis" if track==1 else "xaxis"+str(track)},b=f.{"yaxis" if track==1 else "yaxis"+str(track)};return {{x:r.left+a._offset+a.d2p({x}),y:r.top+b._offset+b.d2p({json.dumps(time_text)})}};')
        # Actual Plotly mouse zoom, rather than changing layout from JavaScript.
        a=await point('2026-01-01 03:00:00');b=await point('2026-01-01 08:00:00')
        await c.drag(a['x'],a['y'],b['y']);await asyncio.sleep(.6)
        zoomed=await state()
        if zoomed['ranges']['yaxis']==first['ranges']['yaxis']:
            print(await view('return {a:f.yaxis.fixedrange,dragmode:f.dragmode,rect:g.getBoundingClientRect().toJSON(),hit:document.elementFromPoint('+str(a['x'])+','+str(a['y'])+')?.outerHTML};'),flush=True)
            image=await c.call('Page.captureScreenshot',dict(format='png',captureBeyondViewport=True))
            (OUT/'zoom-debug.png').write_bytes(base64.b64decode(image['data']))
        assert zoomed['ranges']['yaxis']!=first['ranges']['yaxis'],'Mouse zoom did not take effect'
        for width in (900,2300,1500):
            await c.js(f'document.body.style.width="{width}px"')
            await c.wait_js(prefix+'return Math.abs(g.clientWidth-f.width)<=1;})()')
            await asyncio.sleep(.2)
            resized=await state()
            assert resized['ranges']==zoomed['ranges'],('zoom changed on resize',width)
            assert resized['tags']==zoomed['tags'],('tags changed on resize',width)
            assert resized['curves']==zoomed['curves'],('curves changed on resize',width)
            assert resized['history']==zoomed['history'],('zoom history changed',width)
        checks.append('zoom, all eight axis ranges, history, curves and existing tag survive repeated resize')
        # Browser-window resize, independently of a parent-only width change.
        await c.js('document.body.style.width="100%"')
        await c.call('Emulation.setDeviceMetricsOverride',dict(width=1700,height=1500,deviceScaleFactor=1,mobile=False))
        await c.wait_js(prefix+'return Math.abs(g.clientWidth-f.width)<=1;})()')
        await asyncio.sleep(.2)
        assert (await state())['ranges']==zoomed['ranges']
        checks.append('browser viewport resize fills plot without resetting zoom')

        # A width observer can finish after a React/Plotly redraw. Exercise that
        # overlap and ensure its capture geometry and saved zoom remain current.
        await c.js('''(async()=>{
          for(const [width,label] of [[1000,"Small dots"],[2200,"No dots"],[1100,"Small dots"],[1900,"No dots"]]){
            document.body.style.width=width+"px";
            Array.from(document.querySelectorAll("button")).find(b=>b.textContent.trim()===label).click();
            await new Promise(r=>setTimeout(r,35));
          }
        })()''')
        await c.wait_js(prefix+'return Math.abs(g.clientWidth-f.width)<=1;})()')
        await asyncio.sleep(.4)
        after_race=await state()
        for key in ('ranges','tags','curves','history'):
            assert after_race[key]==zoomed[key],('redraw/resize overlap changed state',key)
        checks.append('rapid container resizing during marker redraws preserves zoom, history, curves and tags')

        # Streamlit can replace component props while an earlier resize is due.
        for width,chart_height in ((1300,760),(2050,650)):
            args=inputs();args['height']=chart_height
            await c.js(f'document.body.style.width="{width}px";window.postMessage('+json.dumps(dict(type='streamlit:render',args=args,disabled=False))+',"*")')
            await c.wait_js(prefix+f'return Math.abs(g.clientWidth-f.width)<=1 && f.height==={chart_height};'+'})()')
            await asyncio.sleep(.25)
            changed=await state()
            for key in ('ranges','tags','curves','history'):
                assert changed[key]==zoomed[key],('prop/resize overlap changed state',key)
            assert await view('const l=document.querySelector(".vlv-capture");return Math.abs(parseFloat(l.style.width)-f._size.w)<1 && Math.abs(parseFloat(l.style.height)-f._size.h)<1;')
        checks.append('incoming height/width changes during redraw retain state and correct drawing geometry')

        await c.js('document.body.style.width="1000px";setTimeout(()=>document.querySelector(".vlv-wrap").style.display="none",25)')
        await asyncio.sleep(.25)
        await c.js('document.body.style.width="2100px";document.querySelector(".vlv-wrap").style.display=""')
        await c.wait_js(prefix+'return Math.abs(g.clientWidth-f.width)<=1;})()')
        await asyncio.sleep(.25)
        shown=await state()
        for key in ('ranges','tags','curves','history'):
            assert shown[key]==zoomed[key],('hide/show changed state',key)
        checks.append('hiding and showing a plot during a pending resize recovers without losing state')

        # Bring Track 4 inside the emulated browser viewport before mouse input.
        await c.js('document.body.style.width="1500px"')
        await c.wait_js(prefix+'return Math.abs(g.clientWidth-f.width)<=1;})()')

        async def button(text):
            await c.js('Array.from(document.querySelectorAll("button")).find(b=>b.textContent.includes('+json.dumps(text)+')).click()')
            await asyncio.sleep(.3)
        await button('Tagging')
        assert await view('const l=document.querySelector(".vlv-capture");return Math.abs(parseFloat(l.style.width)-f._size.w)<1;')
        a=await point('2026-01-01 05:00:00',4,.24);b=await point('2026-01-01 05:40:00',4,.24)
        await c.drag(a['x'],a['y'],b['y'])
        await c.wait_js(prefix+'return g.data.filter(t=>t.meta?.source==="tag").length===2;})()')
        await asyncio.sleep(.3)
        assert await view('const t=g.data.filter(t=>t.meta?.source==="tag").find(t=>t.meta.id!=="chart_drag|existing-tag");return Math.abs(new Date(t.y[0])-new Date("2026-01-01 05:00:00"))<60000 && Math.abs(new Date(t.y.at(-1))-new Date("2026-01-01 05:40:00"))<60000;')
        checks.append('capture layer follows plot and drawing produces correct tag times after resize')
        mid=await point('2026-01-01 05:20:00',4,.24)
        await c.click(mid['x'],mid['y'],2);await asyncio.sleep(.4)
        assert await c.js('!Array.from(document.querySelectorAll("button")).find(b=>b.textContent.includes("Delete selected")).disabled')
        selected=await state()
        await c.js('document.body.style.width="2100px"')
        await c.wait_js(prefix+'return Math.abs(g.clientWidth-f.width)<=1;})()')
        assert (await state())['tags']==selected['tags']
        await button('Delete selected')
        await c.wait_js(prefix+'return g.data.filter(t=>t.meta?.source==="tag").length===1;})()')
        assert (await state())['tags']==zoomed['tags']
        checks.append('selection survives resize; deleting the new tag preserves the original')
        await button('Tagging');await button('Undo chart zoom')
        assert (await state())['ranges']==first['ranges']
        checks.append('undo zoom still restores original ranges after resizing and tag editing')
        # Look for resize feedback loops after the page settles.
        await c.js('window.resizeProbe=0;document.querySelector(".vlv-plot").on("plotly_relayout",()=>window.resizeProbe++)')
        await asyncio.sleep(.6)
        assert await c.js('window.resizeProbe')==0
        exceptions=[e for e in c.events if e.get('method')=='Runtime.exceptionThrown']
        console_errors=[e for e in c.events if e.get('method')=='Runtime.consoleAPICalled' and e['params'].get('type')=='error']
        assert not exceptions,exceptions
        assert not console_errors,console_errors
        checks.append('no idle resize loop, JavaScript exceptions or console errors')
        screen=await c.call('Page.captureScreenshot',dict(format='png',captureBeyondViewport=True))
        (OUT/'after.png').write_bytes(base64.b64decode(screen['data']))
        result=dict(passed=True,browser='isolated headless Chrome; production built component; synthetic data',checks=checks,initial_width=first['plot'],expanded_width=expanded['plot'])
        (OUT/'after.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result,indent=2),flush=True)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--baseline',action='store_true');args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    bundle=OUT.parent/'before'/DIST.relative_to(ROOT) if args.baseline else DIST
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(QuietHandler,directory=str(bundle)))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    with tempfile.TemporaryDirectory(prefix='drillmate-resize-chrome-') as profile,(OUT/'chrome.log').open('w') as log:
        proc=subprocess.Popen(['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome','--headless=new','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader','--disable-extensions','--disable-background-networking','--no-first-run','--no-default-browser-check','--remote-debugging-port=0','--user-data-dir='+profile,'about:blank'],stdout=log,stderr=log,start_new_session=True)
        try:
            portfile=Path(profile)/'DevToolsActivePort';deadline=time.monotonic()+15
            while not portfile.exists() and time.monotonic()<deadline:time.sleep(.1)
            port=portfile.read_text().splitlines()[0]
            target=next(t for t in json.load(urllib.request.urlopen('http://127.0.0.1:'+port+'/json/list')) if t['type']=='page')
            asyncio.run(exercise(target['webSocketDebuggerUrl'],f'http://127.0.0.1:{server.server_port}',args.baseline))
        finally:
            if proc.poll() is None:os.killpg(proc.pid,signal.SIGTERM)
            proc.wait(timeout=10);server.shutdown()

if __name__=='__main__':main()
