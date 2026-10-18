"""Targeted legacy-export and frontend row-identity regression checks."""
import ast
import pathlib
import shutil
import subprocess
import unittest

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]


class ResultRowIdentityTests(unittest.TestCase):
    def test_python_export_keeps_two_distinct_tag_ids_same_time(self):
        source = ast.parse((ROOT/'ui/sidebar.py').read_text())
        funcs = [node for node in source.body if isinstance(node, ast.FunctionDef)
                 and node.name in {'_normalized_time_identity', '_filter_hit_result_rows_for_tags'}]
        module = ast.Module(body=funcs, type_ignores=[])
        namespace = {'pd': pd}
        exec(compile(ast.fix_missing_locations(module), str(ROOT/'ui/sidebar.py'), 'exec'), namespace)
        start, end = '2026-01-01 00:00:00', '2026-01-01 00:01:00'
        tags = [{'tag_id': key, 'start': start, 'end': end} for key in ['a','b']]
        rows = [{'tag_id': key, 'tag_start': start, 'tag_end': end,
                 'tag_label': 'Dragged Tag'} for key in ['a','b','stale']]
        kept = namespace['_filter_hit_result_rows_for_tags'](rows,tags)
        self.assertEqual([r['tag_id'] for r in kept], ['a','b'])

    def test_app_history_keeps_two_durable_ids_with_same_label_and_time(self):
        source = ast.parse((ROOT/'app.py').read_text())
        funcs = [node for node in source.body if isinstance(node, ast.FunctionDef)
                 and node.name == '_deduplicate_virtual_hit_results']
        self.assertEqual(len(funcs), 1)
        namespace = {'_virtual_json_safe': lambda x: x, 'list': list, 'dict': dict}
        exec(compile(ast.fix_missing_locations(ast.Module(body=funcs, type_ignores=[])),
                     str(ROOT/'app.py'), 'exec'), namespace)
        start, end = '2026-01-01 00:00:00', '2026-01-01 00:01:00'
        tags = [{'tag_id': key, 'start': start, 'end': end, 'label': 'Dragged Tag',
                 'source': 'chart_drag'} for key in ['a', 'b']]
        rows = [{'tag_id': key, 'tag_start': start, 'tag_end': end,
                 'tag_label': 'Dragged Tag'} for key in ['a', 'b', 'stale']]
        kept = namespace['_deduplicate_virtual_hit_results'](rows, tags)
        self.assertEqual([r['tag_id'] for r in kept], ['a', 'b'])

    def test_app_history_preserves_legacy_manual_tag_fallback(self):
        source = ast.parse((ROOT/'app.py').read_text())
        funcs = [node for node in source.body if isinstance(node, ast.FunctionDef)
                 and node.name == '_deduplicate_virtual_hit_results']
        namespace = {'_virtual_json_safe': lambda x: x}
        exec(compile(ast.fix_missing_locations(ast.Module(body=funcs, type_ignores=[])),
                     str(ROOT/'app.py'), 'exec'), namespace)
        start, end = '2026-01-01 00:00:00', '2026-01-01 00:01:00'
        manual = {'label': 'Observation 1', 'start': start, 'end': end}
        row = {'tag_id': f'manual|Observation 1|{start}|{end}',
               'tag_label': 'Observation 1', 'tag_start': start, 'tag_end': end}
        self.assertEqual(len(namespace['_deduplicate_virtual_hit_results']([row], [manual])), 1)

    @unittest.skipUnless(shutil.which('node'), 'Node.js not installed')
    def test_react_normalization_preserves_distinct_ids(self):
        # Parse and execute only the two dependency-free original JS helpers.
        # This is not a replacement for the full frontend rebuild.
        script = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const raw = fs.readFileSync(process.argv[1], 'utf8');
function extract(name) {
  const start = raw.indexOf('function ' + name + '(');
  assert(start >= 0, name + ' not found');
  const end = raw.indexOf('\n}\n', start);
  assert(end > start);
  return raw.slice(start, end + 2);
}
const context = {toMs: v => new Date(v).getTime(),
  fmtTime: v => new Date(v).toISOString().slice(0, 19).replace('T',' ')};
vm.createContext(context);
vm.runInContext(extract('rowIdentity') + '\n' + extract('normalizeRowsForServer'), context);
const rows = [
{well:'W',section:'12',tag_id:'a',tag_label:'Dragged Tag',tag_start:'2026-01-01T00:00:00Z',tag_end:'2026-01-01T00:01:00Z'},
{well:'W',section:'12',tag_id:'b',tag_label:'Dragged Tag',tag_start:'2026-01-01T00:00:00Z',tag_end:'2026-01-01T00:01:00Z'}];
assert.equal(context.normalizeRowsForServer(rows).length, 2);
assert.notEqual(context.rowIdentity(rows[0]), context.rowIdentity(rows[1]));
'''
        result = subprocess.run(['node', '-e', script, str(ROOT/'streamlit_components/virtual_log_viewer/frontend/src/main.jsx')],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

if __name__ == '__main__': unittest.main()
