"""Exercise the actual JavaScript embedded in the Streamlit session-save HTML."""
import pathlib
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node.js required')
class BrowserSessionHitResultsTests(unittest.TestCase):
    def test_two_different_tag_ids_survive_browser_save_and_stale_id_is_dropped(self):
        script = r'''
const fs=require('fs'),vm=require('vm'), assert=require('assert');
const src=fs.readFileSync(process.argv[1],'utf8');
function extract(name, nextName) {
  const a=src.indexOf('function '+name+'() {{');
  assert(a>=0,'missing '+name);
  const b=src.indexOf('function '+nextName+'(',a);
  assert(b>a,'missing next '+nextName);
  return src.slice(a,b).replace(/\{\{/g,'{').replace(/\}\}/g,'}');
}
// The second function has three arguments rather than zero.
function extractMerge() {
  const a=src.indexOf('function mergePayloadWithDrawnTags(');
  const b=src.indexOf('function ',a+10);
  assert(a>=0 && b>a);
  return src.slice(a,b).replace(/\{\{/g,'{').replace(/\}\}/g,'}');
}
const start='2026-01-01 00:00:00',end='2026-01-01 00:01:00';
const rows=['a','b','stale'].map(id=>({well:'W', section:'12',tag_id:id,
   tag_label:'Dragged Tag',tag_start:start,tag_end:end}));
const saved=['a','b'].map(id=>({tag_id:id,start,end,source:'manual',label:'Dragged Tag'}));
const ctx={contextKey:'my_key',
  readJsonListWithPresence:(key)=>({exists:true,items:rows}),
  readJsonList:()=>[],parseDateMs:v=>Date.parse(v),
  deduplicate:items=>items,
  selectedAgentNameFromPayload:()=> 'TRQSpike',
  normalizeHitResultAgentName:(row)=>row,
  window:{localStorage:{length:0}},
  Set,Map,JSON,String,Array};
vm.createContext(ctx);
vm.runInContext(extract('readBrowserHitResults','mergePayloadWithDrawnTags'),ctx);
vm.runInContext(extractMerge(),ctx);
const fromBrowser=ctx.readBrowserHitResults();
assert.equal(fromBrowser.length,3,'must preserve multiple tag IDs in browser results');
const base={dashboard_context:{},dashboard_state:{widget_state:{}},
  manual_tagger_intervals:saved,tag_intervals:saved};
const merged=ctx.mergePayloadWithDrawnTags(base,[],fromBrowser);
assert.equal(merged.hit_results.length,2,'must preserve two active tags and drop stale ID');
assert.equal(merged.hit_results[0].tag_id,'a');
assert.equal(merged.hit_results[1].tag_id,'b');
// A manually entered historical tag may not have a durable tag_id. React's
// fallback id is source|label|start|end, whereas session save normalizes it.
const manual={start,end,source:'manual',label:'Observation 1'};
const legacyHit={well:'W', section:'12',tag_id:'manual|Observation 1|'+start+'|'+end,
  tag_label:'Observation 1',tag_start:start,tag_end:end};
const legacyPayload={dashboard_context:{},dashboard_state:{widget_state:{}},
  manual_tagger_intervals:[manual],tag_intervals:[manual]};
const fromLegacy=ctx.mergePayloadWithDrawnTags(legacyPayload,[],[legacyHit]);
assert.equal(fromLegacy.hit_results.length,1,'must not drop current manual hit row with fallback id');
'''
        result=subprocess.run(['node','-e',script,str(ROOT/'ui/sidebar.py')],
                              capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)

if __name__ == '__main__': unittest.main()
