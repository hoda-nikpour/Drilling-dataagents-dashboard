"""Check real rendered pixels for point/short agent events, preserving times."""
import argparse
import asyncio
import base64
from io import BytesIO
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys

from PIL import Image
import websockets
import check_plot_container_resize as static_driver
import check_agent_interval_navigation as app_driver

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "docs/agent_point_visibility_2026-11-11"
STATIC = '(()=>{const f=null,d=document,g=d.querySelector(".vlv-plot"),a=g?._fullLayout;'


async def marker_pixels(c, prefix, timestamp):
    point = await c.js(prefix + 'const r=g.getBoundingClientRect(),p=f?.getBoundingClientRect()||{left:0,top:0};return {x:p.left+r.left+a.xaxis4._offset+a.xaxis4.d2p(.76),y:p.top+r.top+a.yaxis4._offset+a.yaxis4.d2p(' + json.dumps(timestamp) + ')};})()')
    shot = await c.call("Page.captureScreenshot", dict(format="png"))
    raw = base64.b64decode(shot["data"])
    pic = Image.open(BytesIO(raw)).convert("RGB")
    x, y = round(point["x"]), round(point["y"])
    assert 0 <= x < pic.width and 0 <= y < pic.height, (point, pic.size)
    count = sum(
        1 for py in range(max(0, y-7), min(pic.height, y+8))
        for px in range(max(0, x-7), min(pic.width, x+8))
        if (lambda color: color[0] > 65 and color[1] < 65 and color[2] < 65)(pic.getpixel((px, py)))
    )
    return dict(time=timestamp, red_pixels=count, position=point), raw


async def traces(c, prefix):
    return await c.js(prefix + 'return g.data.filter(t=>t.meta?.source==="agent").map(t=>({mode:t.mode,x:t.x,y:t.y,size:t.marker?.size}));})()')


async def synthetic(ws_url, url, baseline):
    async with websockets.connect(ws_url, max_size=30_000_000) as ws:
        c = static_driver.CDP(ws)
        await c.call("Runtime.enable")
        await c.call("Page.enable")
        await c.call("Emulation.setDeviceMetricsOverride", dict(width=1800, height=1500, deviceScaleFactor=1, mobile=False))
        await c.call("Page.addScriptToEvaluateOnNewDocument", dict(source='window.addEventListener("message",e=>{if(e.data?.type==="streamlit:componentReady")window.ready=true;});'))
        await c.call("Page.navigate", dict(url=url))
        await c.wait_js("window.ready===true", timeout=15)
        args = static_driver.inputs()
        starts = ["00:00:00", "03:00:00", "04:00:00", "05:00:00", "06:00:00", "12:00:00", "13:00:00"]
        ends = ["00:00:00", "03:00:00", "04:00:01", "05:00:04", "07:00:00", "12:00:00", "13:00:00"]
        intervals = [dict(label="TRQSpike", start="2026-01-01 "+s, end="2026-01-01 "+e) for s,e in zip(starts,ends)]
        args.update(selected_agent_name="TRQSpike", agent_source="Symptom agent", agent_intervals=intervals)
        args["browser_session_token"] = "point-check"
        async def send():
            await c.js('window.postMessage('+json.dumps(dict(type="streamlit:render", args=args, disabled=False))+',"*")')
        await send()
        await c.wait_js(STATIC+'return !!a && g.data.filter(t=>t.meta?.source==="agent").length===7;})()')
        await asyncio.sleep(.5)
        checks = []
        for time in ["03:00:00", "04:00:00", "05:00:00", "06:30:00", "00:00:00", "12:00:00"]:
            measured, shot = await marker_pixels(c, STATIC, "2026-01-01 "+time)
            checks.append(measured)
        (static_driver.OUT/("baseline.png" if baseline else "after.png")).write_bytes(shot)
        if baseline:
            assert checks[0]["red_pixels"] == 0, checks
            result = dict(reproduced=True, checks=checks)
            (static_driver.OUT/"baseline.json").write_text(json.dumps(result, indent=2))
            print("Reproduced: zero-duration agent event has no visible pixels.", flush=True)
            return
        assert all(row["red_pixels"] >= 10 for row in checks), checks
        original = await traces(c, STATIC)
        assert len(original) == len(intervals)
        assert [(t["y"][0],t["y"][-1]) for t in original] == [(r["start"],r["end"]) for r in intervals]
        assert all(t["mode"] == "lines+markers" and t["size"] == 9 for t in original)
        saved = await c.js('JSON.parse(localStorage.getItem("hoda_dashboard_snapshot_resize_fixture__8.5_point-check"))')
        assert saved["agent_intervals"] == intervals
        original_tags = saved["tags"]
        original_hits = saved["hit_results"]

        # Actual mouse zoom: one-second events remain visible at a 30-minute scale.
        async def point(time):
            return await c.js(STATIC+'const r=g.getBoundingClientRect();return {x:r.left+a.xaxis._offset+a.xaxis.d2p(.5),y:r.top+a.yaxis._offset+a.yaxis.d2p('+json.dumps("2026-01-01 "+time)+')};})()')
        left, right = await point("03:50:00"), await point("04:20:00")
        await c.drag(left["x"], left["y"], right["y"])
        await asyncio.sleep(.6)
        zoomed, _ = await marker_pixels(c, STATIC, "2026-01-01 04:00:00")
        assert zoomed["red_pixels"] >= 10
        assert await traces(c, STATIC) == original
        await c.js('document.body.style.width="1200px"')
        await c.wait_js(STATIC+'return Math.abs(g.clientWidth-a.width)<=1;})()')
        await asyncio.sleep(.3)
        resized, _ = await marker_pixels(c, STATIC, "2026-01-01 04:00:00")
        assert resized["red_pixels"] >= 10

        args["show_agent_intervals"] = False
        await send()
        await c.wait_js(STATIC+'return g.data.every(t=>t.meta?.source!=="agent");})()')
        args["show_agent_intervals"] = True
        await send()
        await c.wait_js(STATIC+'return g.data.filter(t=>t.meta?.source==="agent").length===7;})()')
        assert await traces(c, STATIC) == original
        await asyncio.sleep(.3)
        final = await c.js('JSON.parse(localStorage.getItem("hoda_dashboard_snapshot_resize_fixture__8.5_point-check"))')
        assert final["agent_intervals"] == intervals
        assert final["tags"] == original_tags
        assert final["hit_results"] == original_hits
        assert not [e for e in c.events if e.get("method") == "Runtime.exceptionThrown"]
        result = dict(passed=True, checks=checks, zoomed=zoomed, resized=resized,
                      times_and_saved_intervals_unchanged=True, expert_tags_and_hit_rows_unchanged=True,
                      agent_visibility_toggle_preserved=True)
        (static_driver.OUT/"after.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2), flush=True)


async def real_log(ws_url, url, inspect_only):
    async with websockets.connect(ws_url, max_size=40_000_000) as ws:
        c = app_driver.CDP(ws)
        await c.call("Runtime.enable")
        await c.call("Page.enable")
        await c.call("Emulation.setDeviceMetricsOverride", dict(width=2100, height=1700, deviceScaleFactor=1, mobile=False))
        await c.call("Page.navigate", dict(url=url+"?well=34-10-C47&section=17.5&agent=TRQSpike"))
        prefix = app_driver.PLOT_PREFIX
        await c.wait_js(prefix+'return !!a && !!document.querySelector("pre code");})()', timeout=240)
        print("Full production app ready: C47 / 17.5 / TRQSpike", flush=True)
        async def state():
            return json.loads(await c.js('document.querySelector("pre code").textContent'))
        initial = await state()
        points = [r for r in initial["intervals"] if r["start"] == r["end"]]
        # Include both the first day and a distant single-sample event.
        targets = [points[0], next(r for r in points if r["start"].startswith("2005-12-23")), points[-1]]
        results = []
        for row in targets:
            target = row["start"]
            expected=(datetime.fromisoformat(target)-timedelta(hours=1)).isoformat(sep=' ')
            await app_driver.table_search(c, target)
            generation = (await state())["generation"]
            await app_driver.table_click(c, 'Array.from(d.querySelectorAll("button[data-interval-start]")).find(b=>b.dataset.intervalStart==='+json.dumps(target)+')')
            await c.wait_js(prefix+'try{const s=JSON.parse(document.querySelector("pre code").textContent);return s.generation>'+str(generation)+' && s.viewport==='+json.dumps(expected)+' && !s.pending && a.yaxis.range[1]==='+json.dumps(expected)+';}catch(e){return false;}})()', timeout=90)
            await asyncio.sleep(1.2)
            # Finish navigation's smooth scroll, then put the measured point
            # below Streamlit's fixed page header before taking a screenshot.
            await c.js(prefix+'f.contentWindow.scrollTo(0,0);const r=g.getBoundingClientRect(),p=f.getBoundingClientRect();const y=p.top+r.top+a.yaxis4._offset+a.yaxis4.d2p('+json.dumps(target)+');let n=f.parentElement;while(n){if(n.scrollHeight>n.clientHeight+2 && ["auto","scroll"].includes(getComputedStyle(n).overflowY)){n.scrollBy({top:y-300,behavior:"instant"});break;}n=n.parentElement;}})()')
            await asyncio.sleep(.4)
            data = await traces(c, prefix)
            exact = [t for t in data if t["y"][0] == t["y"][-1] == target]
            measured, shot = await marker_pixels(c, prefix, target)
            result = dict(target=target, exact_single_sample_trace=exact, measured=measured)
            results.append(result)
            (app_driver.OUT/"results.json").write_text(json.dumps(results, indent=2))
            (app_driver.OUT/f"point-{len(results)}.png").write_bytes(shot)
            print(json.dumps(result), flush=True)
            assert exact and all("markers" in t["mode"] for t in exact), result
            assert measured["red_pixels"] >= 10, result
        assert not [e for e in c.events if e.get("method") == "Runtime.exceptionThrown"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--real-log", action="store_true")
    options = parser.parse_args()
    if options.real_log:
        assert not options.baseline
        app_driver.OUT = AUDIT/"real-log-evidence"
        app_driver.FIXTURE = ROOT/"tools/agent_interval_real_log_fixture.py"
        app_driver.exercise = real_log
        sys.argv = [sys.argv[0]]
        app_driver.main()
    else:
        static_driver.OUT = AUDIT/"evidence"
        static_driver.exercise = synthetic
        sys.argv = [sys.argv[0]] + (["--baseline"] if options.baseline else [])
        static_driver.main()


if __name__ == "__main__":
    main()
