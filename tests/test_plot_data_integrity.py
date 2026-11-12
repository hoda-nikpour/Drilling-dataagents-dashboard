"""Independent invariants for sensor hover and drawn-tag time boundaries."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]


def test_hover_uses_nearest_recorded_time_and_never_invents_missing_measurements():
    if not shutil.which('node'):pytest.skip('Node required')
    script=r'''
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const {normalizeValues,buildHoverIndex,closestHoverPoint,boundedTagTimes}=await import(pathToFileURL(process.argv[1]));
assert.deepEqual(normalizeValues([10,null,20]),[0,null,1]);
assert.deepEqual(normalizeValues([0,null,100],0,100),[0,null,1]);
assert.equal(normalizeValues(Array(150000).fill(7))[0],.5);
const track=(x,y,breaks=[])=>({tracks:[{track:1,curves:[{label:'TRQ',unit:'kN.m',x,y,display_min:0,display_max:100}]}],gap_after_indices:breaks});
let data=buildHoverIndex(track([0,100,null],[0,240000,300000]),v=>v);
assert.equal(closestHoverPoint(data,1,0,1).value,0,'X proximity must not choose a sample four minutes later');
assert.equal(closestHoverPoint(data,1,300000,0),null,'missing sample is not zero');
data=buildHoverIndex(track([0,100,50],[0,0,4000]),v=>v);
assert.equal(closestHoverPoint(data,1,0,1).value,100,'duplicate timestamps preserve distinct samples');
data=buildHoverIndex(track([20,30],[0,600000],[0]),v=>v);
assert.equal(closestHoverPoint(data,1,300000,.5),null,'no measurement in the middle of a real gap');
assert.equal(closestHoverPoint(data,1,0,.5).value,20,'gap boundary is still a valid sample');
assert.deepEqual(boundedTagTimes(9999,10000,0,10000),[9000,10000],'minimum duration cannot extend beyond section end');
assert.deepEqual(boundedTagTimes(-4000,5000,0,10000),[0,5000]);
assert.deepEqual(boundedTagTimes(8000,2000,0,10000),[2000,8000]);
assert.equal(boundedTagTimes(NaN,5000,0,10000),null);
'''
    result=subprocess.run(['node','--input-type=module','-e',script,
        str(ROOT/'streamlit_components/virtual_log_viewer/frontend/src/plotData.mjs')],capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr
