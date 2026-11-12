"""Check the three lane headings in real rendered SVG and camera export."""
import asyncio
import base64
import json
import sys
import time
from PIL import Image
import websockets
import check_plot_container_resize as driver


async def exercise(ws_url,url,baseline):
    downloads=driver.OUT/'downloads';downloads.mkdir(parents=True,exist_ok=True)
    async with websockets.connect(ws_url,max_size=40_000_000) as ws:
        c=driver.CDP(ws);await c.call('Runtime.enable');await c.call('Page.enable')
        await c.call('Emulation.setDeviceMetricsOverride',dict(width=2300,height=1500,deviceScaleFactor=1,mobile=False))
        await c.call('Browser.setDownloadBehavior',dict(behavior='allow',downloadPath=str(downloads)))
        await c.call('Page.addScriptToEvaluateOnNewDocument',dict(source='window.addEventListener("message",e=>{if(e.data?.type==="streamlit:componentReady")window.ready=true;});'))
        await c.call('Page.navigate',dict(url=url));await c.wait_js('window.ready===true')
        args=driver.inputs()
        await c.js('window.postMessage('+json.dumps(dict(type='streamlit:render',args=args,disabled=False))+',"*")')
        prefix='(()=>{const g=document.querySelector(".vlv-plot"),a=g?._fullLayout;'
        await c.wait_js(prefix+'return !!a&&g.querySelectorAll(".annotation").length===3;})()')
        expected=['Experttags','Overlap','Agentdetections']
        async def state():
            return await c.js(prefix+'''const r=g.getBoundingClientRect();return {
              width:g.clientWidth,plotWidth:a.width,ranges:[a.xaxis.range,a.xaxis2.range,a.xaxis3.range,a.xaxis4.range,a.yaxis.range],
              tags:g.data.filter(t=>t.meta?.source==="tag").map(t=>({id:t.meta.id,y:t.y})),
              annotations:Array.from(g.querySelectorAll(".annotation")).map((e,i)=>{
                const b=e.getBoundingClientRect();return {text:e.textContent.replace(/\s/g,""),x:b.left-r.left,y:b.top-r.top,
                  right:b.right-r.left,bottom:b.bottom-r.top,center:b.left+b.width/2-r.left,
                  expectedCenter:a.xaxis4._offset+a.xaxis4.d2p([.24,.50,.76][i])};}),top:a.yaxis._offset};})()''')
        first=await state();results=[]
        async def check(width):
            await c.js('document.body.style.width='+json.dumps(str(width)+'px'))
            await c.wait_js(prefix+'return Math.abs(g.clientWidth-a.width)<1&&g.querySelectorAll(".annotation").length===3;})()')
            await asyncio.sleep(.5)
            value=await state();headers=value['annotations']
            assert [h['text'] for h in headers]==expected,value
            for index,header in enumerate(headers):
                assert header['y']>=1 and header['bottom']<=value['top']-2,header
                assert abs(header['center']-header['expectedCenter'])<1.5,header
                assert header['x']>=0 and header['right']<=value['plotWidth'],header
                if index:assert header['x']>=headers[index-1]['right']+2,(width,headers)
            assert value['tags']==first['tags']
            results.append(dict(passed=True,case='header geometry',width=width,state=value))
            print('Labels visible, separate and centered at width',width,flush=True)
        for width in [2100,1200,900,600,1800]:await check(width)
        # Preserve the current zoom while a redraw recalculates header wrapping.
        point=lambda text:prefix+'const r=g.getBoundingClientRect();return {x:r.left+a.xaxis._offset+a.xaxis.d2p(.5),y:r.top+a.yaxis._offset+a.yaxis.d2p('+json.dumps(text)+')};})()'
        p,q=await c.js(point('2026-01-01 03:00:00')),await c.js(point('2026-01-01 08:00:00'))
        await c.drag(p['x'],p['y'],q['y']);await asyncio.sleep(.4)
        zoomed=(await state())['ranges']
        for width in [900,1800]:
            await check(width);assert (await state())['ranges']==zoomed
        await c.js('Array.from(document.querySelectorAll("button")).find(b=>b.textContent==="Small dots").click()')
        await asyncio.sleep(.4);assert (await state())['ranges']==zoomed
        (driver.OUT/'geometry.json').write_text(json.dumps(results,indent=2))
        # Use the actual visible camera button, retaining the headings in PNG.
        camera=await c.js('(()=>{const e=Array.from(document.querySelectorAll(".modebar-btn")).find(b=>b.dataset.title==="Download plot as a png"),r=e.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2};})()')
        await c.click(camera['x'],camera['y'])
        deadline=time.monotonic()+15;files=[]
        while time.monotonic()<deadline:
            files=list(downloads.glob('*.png'))
            if files:break
            await asyncio.sleep(.15)
        if not files:
            (driver.OUT/'export-events.json').write_text(json.dumps(c.events,indent=2))
            print(await c.js('document.body.innerText'),flush=True)
        assert files,'No camera export'
        exported=Image.open(files[0]).convert('RGB');top=(await state())['top']
        colors={'purple':0,'green':0,'red':0}
        for y in range(min(int(top),exported.height)):
            for x in range(exported.width):
                red,green,blue=exported.getpixel((x,y))
                if red>50 and blue>50 and green<red*.6 and abs(red-blue)<45:colors['purple']+=1
                if green>45 and red<green*.65 and blue<green*.65:colors['green']+=1
                if red>55 and green<red*.4 and blue<red*.4:colors['red']+=1
        assert all(v>8 for v in colors.values()),colors
        results.append(dict(passed=True,case='camera export',image_size=exported.size,heading_color_pixels=colors))
        errors=[e for e in c.events if e.get('method')=='Runtime.exceptionThrown']
        assert not errors,errors
        shot=await c.call('Page.captureScreenshot',dict(format='png'))
        (driver.OUT/'headers.png').write_bytes(base64.b64decode(shot['data']))
        (driver.OUT/'results.json').write_text(json.dumps(dict(passed=True,checks=results),indent=2))


if __name__=='__main__':
    driver.OUT=driver.ROOT/'docs/lane_headers_2026-11-12/browser'
    driver.exercise=exercise;sys.argv=[sys.argv[0]];driver.main()
