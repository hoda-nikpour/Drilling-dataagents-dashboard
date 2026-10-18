# Patch order for Drilling-dataagents-dashboard

**Read first:** These files are intended for a development branch. They have NOT been end-to-end tested inside the current GitHub checkout, which was not available to the patch author during this turn.

## Step 0. Protect the current dashboard

```sh
git switch -c fixes/height-and-validation
git status --short
```

Commit any unrelated work before applying patches.

## Step 1. Viewer height (existing patch)

Choose **one** of the user's audited height patches. Do NOT apply the original + verified GitHub patches on top of each other, and do NOT use the September ZIP patch on the GitHub code.

For the public GitHub-style source:

```sh
git apply --check /path/to/github_main_viewer_height_fix_verified.patch
git apply /path/to/github_main_viewer_height_fix_verified.patch
cd streamlit_components/virtual_log_viewer/frontend
npm ci
npm run build
cd ../../..
```

Check that `cd ../../..` returned to the repository root. Include the rebuilt `frontend/dist` in deployment if that directory is tracked/served there. Confirm that Plotly errors, tag drawing, table expansion/collapse, and mousewheel interaction work in the actual Streamlit deployment.

## Step 2. Add separate validation engine

```sh
git apply --check /path/to/drillmate_validation_additive.patch
git apply /path/to/drillmate_validation_additive.patch
python -m unittest discover -s tests -p 'test_drillmate_*.py' -v
python tools/validate_drilling_events.py docs/validation_example_symptom.json --output symptom_example_report.json
```

This creates no changes in app.py, ui/sidebar.py, main.jsx, style.css, existing JSON, or Excel exports. The resulting `symptom_example_report.json` is an independent illustrative report; you can delete it after checking.

## Step 3. Only then connect real dashboard exports

The supplied validation core intentionally **does not accept a raw dashboard session JSON**. A safe adapter requires the current checked-out source and at least one anonymized saved session for each relevant agent type. It must carry stable IDs and a selected-agent label, collect explicit review windows, and distinguish complete prediction coverage from the UI viewport buffer.

Before marking the prediction generation method as verified, test stateful/12-hour boundary behavior against full sequential processing. Do NOT set `prediction_generation='state_preserving_windows'` simply because the application currently has a section-wide window loop.

## Step 4. Later repository-specific fixes

- Make live Hit/Miss visibly an unverified viewport comparison, not a definitive validation score.
- Preserve legacy `score_percent`, `accepted` and exports; report new metrics separately.
- Fix result-row deduplication using actual stable tag IDs, after confirming old-session compatibility.
- Wire the separate activity evaluator to the real manual-tag ledger, rather than forcing `manual_activity_tags=[]` into other code paths.

Those changes should be produced as a **separate, reviewable patch** against an exact repo commit. They have deliberately not been guessed from incomplete source excerpts.
