#!/usr/bin/env python3
"""Print exact files/line numbers for boss-feedback integration points.

Run from the root of Drilling-dataagents-dashboard:
    python locate_boss_feedback_points.py

No files are modified.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path.cwd()
SKIP_PARTS = {'.git', '.venv', 'venv', '__pycache__', 'node_modules', 'dist', 'build'}

GROUPS = {
    'ACTIVITY RULE / PRIORITY LOCATIONS': [
        re.compile(r'MakingConnection', re.I),
        re.compile(r'TrippingIn|TrippingOut|Tripping In|Tripping Out', re.I),
        re.compile(r'Conditioning|Circulating|Reaming', re.I),
        re.compile(r'activity.*priority|priority.*activity', re.I),
    ],
    'PRESSURE-SPIKE / SPP / MFI LOCATIONS': [
        re.compile(r'\bSPP\b|stand\s*pipe|standpipe', re.I),
        re.compile(r'pressure.*spike|spike.*pressure', re.I),
        re.compile(r'\bMFI\b|mud.*flow.*in|flow.*in', re.I),
    ],
    'DATAFRAME LOAD / APP INTEGRATION LOCATIONS': [
        re.compile(r'read_csv|read_parquet|read_excel|load_data|load_dataset', re.I),
        re.compile(r'st\.session_state', re.I),
        re.compile(r'pd\.DataFrame|DataFrame\(', re.I),
    ],
}


def python_files():
    for path in sorted(ROOT.rglob('*.py')):
        rel = path.relative_to(ROOT)
        if any(part in SKIP_PARTS for part in rel.parts):
            continue
        if rel.name == Path(__file__).name:
            continue
        yield path, rel


def matches_for(patterns):
    hits = []
    for path, rel in python_files():
        try:
            lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
        except OSError:
            continue
        seen_lines = set()
        for i, line in enumerate(lines, start=1):
            if any(p.search(line) for p in patterns):
                if i in seen_lines:
                    continue
                seen_lines.add(i)
                lo = max(1, i - 2)
                hi = min(len(lines), i + 2)
                context = [(n, lines[n - 1]) for n in range(lo, hi + 1)]
                hits.append((str(rel), i, context))
    return hits


def main():
    print(f'Project root: {ROOT}')
    print('This script is READ-ONLY; it changes nothing.\n')
    for title, patterns in GROUPS.items():
        print('=' * 88)
        print(title)
        print('=' * 88)
        hits = matches_for(patterns)
        if not hits:
            print('No matching Python lines found.\n')
            continue
        for rel, line_no, context in hits:
            print(f'\n>>> {rel}:{line_no}')
            for n, text in context:
                marker = '>>' if n == line_no else '  '
                print(f'{marker} {n:5d}: {text}')
        print()


if __name__ == '__main__':
    main()
