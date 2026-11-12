"""Independent screen-coordinate checks against the built visible viewer."""
import asyncio
import base64
import json
from datetime import datetime
import sys
import websockets
import check_plot_container_resize as driver


async def exercise(ws_url,url,baseline):
    async with websockets.connect(ws_url,max_size=40_000_000) as ws:
        c=driver.CDP(ws)
        await c.call('Runtime.enable');await c.call('Page.enable')
        await c.call('Emulation.setDeviceMetricsOverride',dict(width=1800,height=1500,deviceScaleFactor=1,mobile=False))
        await c.call('Page.addScriptToEvaluateOnNewDocument',dict(source='window.uiEvents=[];window.addEventListener("message",e=>{if(e.data?.type==="streamlit:componentReady")window.ready=true;if(e.data?.type==="streamlit:setComponentValue")window.uiEvents.push(e.data.value);});'))
        args=driver.inputs()
        args.update(context_key='times__8.5',browser_session_token='times',saved_tags=[],
                    section_end='2026-01-03 00:00:00',buffer_end='2026-01-01 16:00:00')
        args['track_data']['tracks'][0]['curves']=[dict(label='TRQ',unit='test',display_min=0,display_max=100,
            x=[0,100,None,10,20,30,40],y=['2026-01-01 06:00:00','2026-01-01 06:04:00','2026-01-01 07:00:00',
                '2026-01-01 09:00:00','2026-01-01 09:30:00','2026-01-02 06:00:00','2026-01-02 08:00:00'])]
        args['track_data']['gap_after_indices']=[3]
        prefix='(()=>{const g=document.querySelector(".vlv-plot"),a=g?._fullLayout;'
        async def view(body):return await c.js(prefix+body+'})()')
        async def render():
            await c.js('window.postMessage('+json.dumps(dict(type='streamlit:render',args=args,disabled=False))+',"*")')
            await c.wait_js(prefix+'return !!a;})()');await asyncio.sleep(.35)
        async def launch():
            await c.call('Page.navigate',dict(url=url));await c.wait_js('window.ready===true');await render()
        async def button(label):
            await c.js('Array.from(document.querySelectorAll("button")).find(b=>b.textContent.includes('+json.dumps(label)+')).click()')
            await asyncio.sleep(.35)
        async def point(time,track=1,x=.5):
            return await view('const r=g.getBoundingClientRect(),x=a.'+('xaxis' if track==1 else 'xaxis'+str(track))+',y=a.'+('yaxis' if track==1 else 'yaxis'+str(track))+';return {x:Math.round(r.left+x._offset+x.d2p('+str(x)+')),y:Math.round(r.top+y._offset+y.d2p('+json.dumps(time)+'))};')
        async def snapshot():return await c.js('window.__drillmateSnapshotProviders["times__8.5_times"]()')
        checks=[];details=[]
        def record(text):checks.append(text);print(text,flush=True)
        try:
            for timezone in ['UTC','Europe/Oslo','America/Los_Angeles']:
                await c.call('Emulation.setTimezoneOverride',dict(timezoneId=timezone))
                await launch();await button('Tagging')
                p=await point('2026-01-01 06:00:00',x=1)
                await c.call('Input.dispatchMouseEvent',dict(type='mouseMoved',**p));await asyncio.sleep(.15)
                hover=await c.js('document.querySelector(".vlv-hover-box").innerText')
                assert 'Nearest point time: 2026-01-01 06:00:00' in hover,hover
                assert '0 test' in hover and '100 test' not in hover,hover
                error=await c.js('(()=>{const r=document.querySelector(".vlv-hover-line").getBoundingClientRect();return r.top+r.height/2-'+str(p['y'])+';})()')
                assert abs(error)<.6,error
                for time in ['2026-01-01 07:00:00','2026-01-01 09:15:00']:
                    p=await point(time,x=0)
                    await c.call('Input.dispatchMouseEvent',dict(type='mouseMoved',**p));await asyncio.sleep(.1)
                    text=await c.js('document.querySelector(".vlv-hover-box").innerText')
                    assert 'No valid sensor sample' in text,(time,text)
                # Independent inverse of the displayed axis at the final actual
                # screen pixels, rather than allowing a minute of hidden drift.
                start=await point('2026-01-01 02:00:00',4,.24)
                move=await point('2026-01-01 02:15:00',4,.24)
                release=await point('2026-01-01 02:30:00',4,.24)
                expected=await view('const r=g.getBoundingClientRect();return ['+str(start['y'])+','+str(release['y'])+'].map(y=>a.yaxis4.p2d(y-r.top-a.yaxis4._offset));')
                await c.call('Input.dispatchMouseEvent',dict(type='mousePressed',button='left',clickCount=1,**start))
                await c.call('Input.dispatchMouseEvent',dict(type='mouseMoved',button='left',buttons=1,**move))
                await c.call('Input.dispatchMouseEvent',dict(type='mouseReleased',button='left',clickCount=1,**release))
                await asyncio.sleep(.3)
                saved=(await snapshot())['tags'][-1]
                delta=await c.js('(()=>{const actual='+json.dumps([saved['start'],saved['end']])+';const expected='+json.dumps(expected)+';return actual.map((s,i)=>Math.abs(new Date(s.replace(" ","T")).getTime()-new Date(expected[i].replace(" ","T")).getTime()));})()')
                assert max(delta)<=501,(timezone,delta,saved,expected)
                details.append(dict(timezone=timezone,line_error_pixels=error,tag_error_ms=delta))
                record(timezone+': cursor line, nearest-time hover, missing/gap samples and saved drawing times match')
                await c.js('localStorage.clear()')

            await c.call('Emulation.setTimezoneOverride',dict(timezoneId='UTC'))
            await launch()
            # Zoom locally, then move the buffer far away while keeping the
            # history. Undo must request the data for its restored old range.
            p,q=await point('2026-01-01 03:00:00'),await point('2026-01-01 04:00:00')
            await c.drag(p['x'],p['y'],q['y']);await asyncio.sleep(.4)
            args.update(buffer_start='2026-01-02 00:00:00',buffer_end='2026-01-02 08:00:00',
                viewport_start='2026-01-02 04:00:00',
                navigation_request=dict(id='far',order=1,start='2026-01-02 04:00:00',lead_fraction=0))
            await render();await c.js('window.uiEvents=[]')
            await button('Undo chart zoom')
            requests=await c.js('window.uiEvents.filter(v=>v.event==="viewport_request")')
            assert requests and requests[-1]['source']=='zoom_restore',requests
            assert requests[-1]['viewport_start'].startswith('2026-01-01'),requests
            assert await c.js('!!document.querySelector(".vlv-navigation-loading")')
            args.update(buffer_start='2026-01-01 00:00:00',buffer_end='2026-01-01 16:00:00',
                        viewport_start=requests[-1]['viewport_start'])
            args.pop('navigation_request')
            await render()
            assert not await c.js('!!document.querySelector(".vlv-navigation-loading")')
            record('undo after distant navigation reloads the restored time range and shows loading until covered')

            args.update(viewport_start='2026-01-02 04:00:00',buffer_start='2026-01-02 00:00:00',
                        buffer_end='2026-01-02 08:30:00',viewport_span_seconds=1800)
            await launch();await c.js('window.uiEvents=[]');await button('Reset chart zoom')
            requests=await c.js('window.uiEvents.filter(v=>v.event==="viewport_request")')
            assert requests and requests[-1]['viewport_span_seconds']==43200,requests
            assert await c.js('!!document.querySelector(".vlv-navigation-loading")')
            record('reset from a narrow buffer requests the full 12-hour range with a loading indicator')

            args.update(buffer_start='2026-01-01 00:00:00',buffer_end='2026-01-03 00:00:00',
                viewport_start='2026-01-01 00:00:00',viewport_span_seconds=43200)
            await launch()
            await c.js('document.querySelector(".vlv-scroll-arrow-down").dispatchEvent(new MouseEvent("dblclick",{bubbles:true}))')
            await asyncio.sleep(.35)
            sync=await view('return {range:a.yaxis.range,input:document.querySelector("input[type=datetime-local]").value};')
            assert datetime.fromisoformat(sync['input'])==datetime.fromisoformat(sync['range'][1]),sync
            record('arrow navigation keeps the visible start-time input synchronized with the plot clock')
            assert not [e for e in c.events if e.get('method')=='Runtime.exceptionThrown']
            (driver.OUT/'results.json').write_text(json.dumps(dict(passed=True,checks=checks,details=details),indent=2))
        except BaseException:
            (driver.OUT/'failure-events.json').write_text(json.dumps(c.events,indent=2))
            shot=await c.call('Page.captureScreenshot',dict(format='png'))
            (driver.OUT/'failure.png').write_bytes(base64.b64decode(shot['data']))
            raise


if __name__=='__main__':
    driver.OUT=driver.ROOT/'docs/core_ui_reliability_2026-11-11/times'
    driver.exercise=exercise;sys.argv=[sys.argv[0]];driver.main()
