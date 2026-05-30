# Plot 9/5 replacement files — follow-up patch

These files patch the replacement code already copied into the dashboard.

Implemented fixes in this patch:

1. Track background
   - React virtual viewer now draws a dense page/grid background on all four tracks by default using Plotly background shapes plus CSS fallback.

2. Agent must be selected before tagging
   - The `Choose Agent to Tag` picker is rendered before manual tag controls.
   - Manual sidebar tag checkboxes are disabled until a data agent is selected.
   - React Track 4 Tagging button and keyboard `T` tagging mode are disabled until a data agent is selected.
   - Any stale pre-agent tag/hit state is cleared before a data agent is selected.

3. Saved dashboard JSON wrong tags
   - Sidebar Save Dashboard Session now trusts the current React viewer tag list as the source of truth for drawn tags.
   - It no longer merges stale Python/session `drawn_tag_intervals` into the downloaded JSON.
   - Saved hit rows are kept only for tags actually saved in that JSON.
   - Automatic data-agent intervals remain excluded from saved user tags.

4. Left arrow rail double-click
   - Hold-scroll now starts only after a short hold delay.
   - Double-clicking the upper/lower arrow jumps exactly 2 hours earlier/later and requests the matching plotted data window, without adding an unwanted extra hold-scroll step.

Validation:
- Python syntax check passed for app.py, ui/sidebar.py, ui/layout.py, visualization/chart_builder.py, and visualization/chart_agent_track.py.
- Removed accidental trailing `#####################` separator blocks from all replaceable files.

After copying these files, rebuild the React component:

```bash
cd streamlit_components/virtual_log_viewer/frontend
rm -rf dist
npm install
npm run build
cd ../../..
python3 -m compileall .
python3 -m streamlit run app.py
```
