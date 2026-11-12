"""Chrome DevTools helper shared by isolated browser regression checks."""
import asyncio
import json
import time

class CDP:
    def __init__(self,ws): self.ws=ws; self.n=0; self.events=[]; self.contexts={}
    async def call(self,method,params=None):
        self.n+=1; n=self.n
        await self.ws.send(json.dumps({'id':n,'method':method,'params':params or {}}))
        while True:
            msg=json.loads(await self.ws.recv())
            if msg.get('method')=='Runtime.executionContextCreated':
                c=msg['params']['context']; self.contexts[c['id']]=c
            elif msg.get('method')=='Runtime.executionContextDestroyed': self.contexts.pop(msg['params']['executionContextId'],None)
            if msg.get('id')==n:
                if 'error' in msg: raise RuntimeError(msg['error'])
                return msg.get('result',{})
            self.events.append(msg)
    async def js(self,expr,ctx=None):
        params={'expression':expr,'returnByValue':True,'awaitPromise':True}
        if ctx: params['contextId']=ctx
        r=await self.call('Runtime.evaluate',params)
        if 'exceptionDetails' in r: raise RuntimeError(r['exceptionDetails'])
        return r.get('result',{}).get('value')
    async def wait_js(self,expr,ctx=None,timeout=45):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            try:
                v=await self.js(expr,ctx)
                if v: return v
            except RuntimeError: pass
            await asyncio.sleep(.3)
        raise AssertionError('Timed out: '+expr[:150])
    async def click(self,x,y,count=1):
        await self.call('Input.dispatchMouseEvent',{'type':'mouseMoved','x':x,'y':y})
        for index in range(count):
            await self.call('Input.dispatchMouseEvent',{'type':'mousePressed','x':x,'y':y,'button':'left','clickCount':index+1})
            await self.call('Input.dispatchMouseEvent',{'type':'mouseReleased','x':x,'y':y,'button':'left','clickCount':index+1})
    async def drag(self,x,y,z):
        await self.call('Input.dispatchMouseEvent',{'type':'mouseMoved','x':x,'y':y})
        await self.call('Input.dispatchMouseEvent',{'type':'mousePressed','x':x,'y':y,'button':'left','clickCount':1})
        for i in range(1,9):
            await self.call('Input.dispatchMouseEvent',{'type':'mouseMoved','x':x,'y':y+(z-y)*i/8,'button':'left','buttons':1})
            await asyncio.sleep(.02)
        await self.call('Input.dispatchMouseEvent',{'type':'mouseReleased','x':x,'y':z,'button':'left','clickCount':1})
