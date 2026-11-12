"""Final interactions: stale time tooltip and late table replies after Undo."""
import argparse
import asyncio
import base64
import json
import sys
import websockets
import check_plot_container_resize as driver

RECORD=False


async def exercise(ws_url,url,baseline):
    async with websockets.connect(ws_url,max_size=40_000_000) as ws:
        c=driver.CDP(ws);await c.call('Runtime.enable');await c.call('Page.enable')
        await c.call('Emulation.setDeviceMetricsOverride',dict(width=1800,height=1500,deviceScaleFactor=1,mobile=False))
        await c.call('Page.addScriptToEvaluateOnNewDocument',dict(source='window.uiEvents=[];window.addEventListener("message",e=>{if(e.data?.type==="streamlit:componentReady")window.ready=true;if(e.data?.type==="streamlit:setComponentValue")window.uiEvents.push(e.data.value);});'))
        args=driver.inputs()
        args.update(context_key='delivery__8.5',browser_session_token='delivery',
            section_end='2026-01-03 00:00:00',viewport_start='2026-01-01 06:00:00',viewport_span_seconds=3600,
            buffer_start='2026-01-01 00:00:00',buffer_end='2026-01-01 23:00:00')
        prefix='(()=>{const g=document.querySelector(".vlv-plot"),a=g?._fullLayout;'
        async def view(body):return await c.js(prefix+body+'})()')
        async def render():
            await c.js('window.postMessage('+json.dumps(dict(type='streamlit:render',args=args,disabled=False))+',"*")')
            await c.wait_js(prefix+'return !!a;})()');await asyncio.sleep(.4)
        async def launch():
            await c.call('Page.navigate',dict(url=url));await c.wait_js('window.ready===true');await render()
        async def button(text):
            await c.js('Array.from(document.querySelectorAll("button")).find(b=>b.textContent.includes('+json.dumps(text)+')).click()')
            await asyncio.sleep(.5)
        async def point(text):
            return await view('const r=g.getBoundingClientRect();return {x:r.left+a.xaxis._offset+a.xaxis.d2p(.5),y:r.top+a.yaxis._offset+a.yaxis.d2p('+json.dumps(text)+')};')
        async def state():
            return await view('return {range:a.yaxis.range,tooltip:document.querySelector(".vlv-hover-box").innerText,hoverVisible:getComputedStyle(document.querySelector(".vlv-hover-box")).display!=="none",lineVisible:getComputedStyle(document.querySelector(".vlv-hover-line")).display!=="none",loading:!!document.querySelector(".vlv-navigation-loading")};')
        findings=[]
        await launch();await button('Tagging')
        p=await point('2026-01-01 06:30:00')
        await c.call('Input.dispatchMouseEvent',dict(type='mouseMoved',**p));await asyncio.sleep(.2)
        before=await state();assert before['hoverVisible']
        await c.call('Input.dispatchKeyEvent',dict(type='keyDown',key='r',code='KeyR'))
        await c.call('Input.dispatchKeyEvent',dict(type='keyUp',key='r',code='KeyR'))
        await asyncio.sleep(.5)
        after=await state()
        findings.append(dict(case='reset_with_stationary_mouse',before=before,after=after,
            passed=not after['hoverVisible'] and not after['lineVisible']))
        if not RECORD:
            await c.call('Input.dispatchMouseEvent',dict(type='mouseMoved',x=p['x'],y=p['y']+3));await asyncio.sleep(.2)
            assert 'Mouse time: 2026-01-01 12:' in (await state())['tooltip']

        args.update(viewport_start='2026-01-01 00:00:00',viewport_span_seconds=43200,
                    buffer_end='2026-01-01 16:00:00')
        await launch()
        p,q=await point('2026-01-01 03:00:00'),await point('2026-01-01 04:00:00')
        await c.drag(p['x'],p['y'],q['y']);await asyncio.sleep(.4)
        args['navigation_request']=dict(id='old-table',order=100,start='2026-01-02 06:00:00',lead_in_fraction=1/12)
        await render();await c.js('window.uiEvents=[]')
        await button('Undo chart zoom')
        undo=await state();requests=await c.js('window.uiEvents')
        args.update(buffer_start='2026-01-02 02:00:00',buffer_end='2026-01-02 22:00:00',
                    viewport_start='2026-01-02 05:00:00')
        await render()
        late=await state()
        manual=[e for e in requests if e.get('source')=='zoom_restore']
        findings.append(dict(case='late_table_buffer_after_undo',undo=undo,after_late=late,requests=requests,
            passed=late['range'][1]=='2026-01-01 00:00:00' and late['loading'] and bool(manual) and manual[-1]['request_order']>100))
        if not RECORD:
            # Simulate the subsequent accepted manual buffer; it must finish on
            # the restored view without changing the saved expert tag.
            args.pop('navigation_request')
            args.update(buffer_start='2026-01-01 00:00:00',buffer_end='2026-01-01 16:00:00',
                        viewport_start='2026-01-01 00:00:00')
            await render()
            assert (await state())['range'][1]=='2026-01-01 00:00:00'
            assert not (await state())['loading']
            assert await view('return g.data.some(t=>t.meta?.source==="tag"&&t.meta?.id==="chart_drag|existing-tag");')
        result=dict(passed=all(v['passed'] for v in findings),checks=findings)
        (driver.OUT/'results.json').write_text(json.dumps(result,indent=2))
        shot=await c.call('Page.captureScreenshot',dict(format='png',captureBeyondViewport=True))
        (driver.OUT/'result.png').write_bytes(base64.b64decode(shot['data']))
        print(json.dumps(result,indent=2),flush=True)
        if not RECORD:assert result['passed'],result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--record-before',action='store_true');options=parser.parse_args()
    RECORD=options.record_before
    audit=driver.ROOT/'docs/pre_delivery_check_2026-11-12'
    if RECORD:driver.DIST=audit/'before/streamlit_components/virtual_log_viewer/frontend/dist'
    driver.OUT=audit/('interactions-before' if RECORD else 'interactions-after')
    driver.exercise=exercise;sys.argv=[sys.argv[0]];driver.main()
