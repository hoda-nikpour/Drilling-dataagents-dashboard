"""Real Streamlit clicks with slow buffers and deliberately delayed old replies."""
import asyncio
import base64
from datetime import datetime, timedelta
import json
import sys

import websockets
import check_agent_interval_navigation as driver


def expected_start(target, span):
    start=datetime.fromisoformat(target)-timedelta(seconds=span/12)
    start=max(datetime(2026,1,1),min(start,datetime(2026,1,3)-timedelta(seconds=span)))
    return start.replace(microsecond=0).isoformat(sep=' ')


async def exercise(ws_url,url,inspect_only):
    async with websockets.connect(ws_url,max_size=40_000_000) as ws:
        c=driver.CDP(ws)
        await c.call('Runtime.enable')
        await c.call('Page.enable')
        await c.call('Emulation.setDeviceMetricsOverride',dict(width=1900,height=1700,deviceScaleFactor=1,mobile=False))
        await c.call('Page.addScriptToEvaluateOnNewDocument',dict(source='''
            window.intervalMessages=[];window.heldAgentAcks=[];window.holdAgentAcks=false;
            window.addEventListener("message",e=>{
              if(e.data?.type!=="streamlit:setComponentValue")return;
              const value=e.data.value;
              if(value?.event)window.intervalMessages.push(value);
              if(window.holdAgentAcks && value?.source==="agent_interval"){
                window.heldAgentAcks.push({data:e.data,source:e.source,origin:e.origin});
                e.stopImmediatePropagation();
              }
            },true);
        '''))
        await c.call('Page.navigate',dict(url=url+'?delay_ms=900'))
        prefix=driver.PLOT_PREFIX
        await c.wait_js(prefix+'return !!a && !!document.querySelector("pre code");})()',timeout=60)
        async def server():
            return json.loads(await c.js('document.querySelector("pre code").textContent'))
        async def chart():
            return await c.js(prefix+'''return {
              range:a.yaxis.range,span:Math.abs(new Date(a.yaxis.range[0])-new Date(a.yaxis.range[1]))/1000,
              tags:g.data.filter(t=>t.meta?.source==="tag").map(t=>({id:t.meta.id,y:t.y})),
              agents:g.data.filter(t=>t.meta?.source==="agent").map(t=>({label:t.meta.label,y:t.y})),
              firstCurve:g.data.find(t=>t.meta?.label==="TRQ")?.y[0],
              loading:!!d.querySelector(".vlv-navigation-loading")
            };})()''')
        original=await chart()
        ledger=(await server())['ledger']
        checks=[]
        results=[]
        a='2026-01-01 03:00:00'
        b='2026-01-02 06:15:00'
        tail='2026-01-02 23:50:00'

        async def click(target):
            before=await c.js('window.intervalMessages.filter(m=>m.event==="agent_interval_click").length')
            await driver.table_click(c,'Array.from(d.querySelectorAll("button[data-interval-start]")).find(b=>b.dataset.intervalStart==='+json.dumps(target)+')')
            await c.wait_js('window.intervalMessages.filter(m=>m.event==="agent_interval_click").length>'+str(before))
            return await c.js('window.intervalMessages.filter(m=>m.event==="agent_interval_click").at(-1)')

        async def wait_target(target,request):
            span=(await chart())['span']
            expected=expected_start(target,span)
            expression=prefix+'''try{
              const s=JSON.parse(document.querySelector("pre code").textContent);
              return s.start==='''+json.dumps(expected)+''' && !s.pending
                && s.click_order==='''+str(request['request_order'])+'''
                && a.yaxis.range[1]==='''+json.dumps(expected)+'''
                && Math.abs(s.span-Math.abs(new Date(a.yaxis.range[0])-new Date(a.yaxis.range[1]))/1000)<1.5;
            }catch(e){return false;}})()'''
            try:
                await c.wait_js(expression,timeout=60)
            except AssertionError:
                (driver.OUT/'failure.json').write_text(json.dumps(dict(expected=expected,server=await server(),chart=await chart()),indent=2))
                raise
            await asyncio.sleep(1.4)
            s,v=await server(),await chart()
            assert v['tags']==original['tags']
            assert s['ledger']==ledger
            assert v['agents']==original['agents']
            assert s['buffer_start']<=target<=s['buffer_end']
            assert 0<=(datetime.fromisoformat(v['firstCurve'])-datetime.fromisoformat(s['buffer_start'])).total_seconds()<4
            assert not v['loading']
            results.append(dict(target=target,expected_view=expected,span=v['span'],request_order=request['request_order']))
            return s,v

        for target in [a,b,a]:
            request=await click(target)
            await wait_target(target,request)
        checks.append('A → B → A keeps original tags, agent times, zoom and the correct sensor buffer')
        print(checks[-1],flush=True)

        # Hold actual chart replies before Streamlit consumes them.
        await c.js('window.holdAgentAcks=true;window.heldAgentAcks=[]')
        old=await click(b)
        await c.wait_js('window.heldAgentAcks.length>=1',timeout=60)
        latest=await click(a)
        await c.wait_js('window.heldAgentAcks.length>=2',timeout=60)
        held=await c.js('window.heldAgentAcks.map(e=>e.data.value)')
        assert held[0]['navigation_id']==old['request_id'],held
        assert held[-1]['navigation_id']==latest['request_id'],held
        await c.js('(()=>{window.holdAgentAcks=false;const e=window.heldAgentAcks[0];window.dispatchEvent(new MessageEvent("message",{data:e.data,source:e.source,origin:e.origin}));})()')
        await asyncio.sleep(1.3)
        pending=await server()
        assert pending['pending']['id']==latest['request_id'],pending
        assert pending['start']==expected_start(a,(await chart())['span']),pending
        await c.js('(()=>{const e=window.heldAgentAcks.at(-1);window.dispatchEvent(new MessageEvent("message",{data:e.data,source:e.source,origin:e.origin}));})()')
        await wait_target(a,latest)
        checks.append('a deliberately delayed old chart reply cannot replace the newer click or consume its pending command')
        print(checks[-1],flush=True)

        # A burst of actual button handlers is sent while a 900 ms backend
        # computation is still pending; the third click must be authoritative.
        await driver.table_click(c,'d.querySelector("button[data-sort-column=start]")')
        count=await c.js('window.intervalMessages.filter(m=>m.event==="agent_interval_click").length')
        await c.js(driver.TABLE_PREFIX+'const all=Array.from(d.querySelectorAll("button[data-interval-start]"));for(const target of '+json.dumps([a,b,tail])+'){all.find(b=>b.dataset.intervalStart===target).click();}})()')
        await c.wait_js('window.intervalMessages.filter(m=>m.event==="agent_interval_click").length>='+str(count+3))
        burst=await c.js('window.intervalMessages.filter(m=>m.event==="agent_interval_click").slice(-3)')
        assert len({v['request_id'] for v in burst})==3
        assert burst[0]['request_order']<burst[1]['request_order']<burst[2]['request_order']
        await wait_target(tail,burst[-1])
        await asyncio.sleep(1.5)
        assert (await server())['click_order']==burst[-1]['request_order']
        checks.append('rapid A → B → C during slow loading finishes on C without a later jump backwards')
        print(checks[-1],flush=True)
        request=await click(a)
        await wait_target(a,request)

        # Zoom before clicking a distant event: context must follow live zoom,
        # even when Python's last buffer still uses the twelve-hour span.
        await c.js(prefix+'f.scrollIntoView({block:"start",behavior:"instant"});})()')
        await asyncio.sleep(.2)
        async def point(time):
            return await c.js(prefix+'const r=g.getBoundingClientRect(),p=f.getBoundingClientRect();return {x:p.left+r.left+a.xaxis._offset+a.xaxis.d2p(.5),y:p.top+r.top+a.yaxis._offset+a.yaxis.d2p('+json.dumps(time)+')};})()')
        left,right=await point('2026-01-01 03:00:00'),await point('2026-01-01 03:30:00')
        await c.drag(left['x'],left['y'],right['y'])
        await asyncio.sleep(.6)
        zoom=(await chart())['span']
        assert 1400<zoom<2200,zoom
        assert (await server())['span']==43200
        request=await click(b)
        s,v=await wait_target(b,request)
        assert abs(v['span']-zoom)<1.5
        offset=(datetime.fromisoformat(b)-datetime.fromisoformat(s['start'])).total_seconds()
        assert abs(offset-zoom/12)<1.1
        checks.append('live 30-minute zoom is preserved and gets approximately 2.5 minutes of earlier context')
        print(checks[-1],flush=True)

        errors=[e for e in c.events if e.get('method')=='Runtime.exceptionThrown'
                or (e.get('method')=='Runtime.consoleAPICalled' and e['params'].get('type')=='error')]
        assert not errors,errors
        assert not await c.js('!!document.querySelector("[data-testid=stException]")')
        result=dict(passed=True,checks=checks,results=results,held_replies=held,burst=burst,
                    artificial_buffer_delay_ms=900,tags_and_agent_intervals_preserved=True)
        (driver.OUT/'results.json').write_text(json.dumps(result,indent=2))
        shot=await c.call('Page.captureScreenshot',dict(format='png'))
        (driver.OUT/'final.png').write_bytes(base64.b64decode(shot['data']))
        print(json.dumps(dict(passed=True,checks=checks),indent=2),flush=True)


if __name__=='__main__':
    driver.OUT=driver.ROOT/'docs/agent_interval_navigation_context_2026-11-11/rapid-clicks'
    driver.exercise=exercise
    sys.argv=[sys.argv[0]]
    driver.main()
