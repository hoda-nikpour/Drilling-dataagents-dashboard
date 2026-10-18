# Patch 3: opt-in, independent final validation

**Base:** Patch 2 already applied to commit `0a6d784` (or `fix/validation-engine`).

## Scope and safety

- Adds an **opt-in** expander at the bottom of the Streamlit sidebar: `Final validation — independent (opt-in)`.
- Requires a **saved expert session JSON**, taken after the last annotation edit. Imports only its canonical `tag_intervals` (does not double-count `tag_ledger` or browser tags). Existing saved-session layout is unchanged.
- Requires the explicit full **reviewed time ranges**, the **same selected agent and well/section**, independently confirmed clock offset, actual sample cadence, maximum permitted sample gap, and operator confirmation that agent settings match the exported session. For symptom event matching, requires a positive expert-approved event IoU threshold.
- Computes a **continuous** full-section prediction set once, using exactly the already selected agent configuration. For evaluation, the interval end is extended by one explicitly known sampling cadence because the underlying detectors use inclusive last-sample timestamps. This does not change dashboard-drawn intervals or saved predictions. It requires the full raw/cleaned timestamp sequence to match the section index. Predictions crossing gaps/review boundaries are not silently counted as false positives.
- Activity evaluation is **binary selected activity vs NotSelected**, not exhaustive multiclass classification. It is valid only if the reviewer marked all occurrences of the selected activity over the stated coverage, including reviewed negative time.
- The opt-in panel currently accepts **one selected section** with a unique time index and no gap beyond the verified maximum allowable sample gap. Multi-section or gap-crossing state continuity is not yet independently certified and fails closed.
- The downloaded JSON includes a config hash, expert-session hash, reviewed coverage, rules and the actual result. Empty denominators remain N/A; incomplete coverage means **Not evaluable**, not a zero score.
- Leaves the **existing live Hit Results algorithm, tag dragging/editing, chart navigation and saved JSON/Excel headings unchanged.** Adds a visible warning that the Hit Results table is a *viewport-dependent preview*, and uses durable tag IDs for result-row deduplication in React, the browser-side session-save HTML and the Python export filter, with a fallback for legacy rows. The stored annotation tags and underlying export structure remain unchanged. Preserves the old 95% field only in the legacy export.

## User workflow

1. With the patched frontend rebuilt and running, select the same well, section(s), and agent as the saved expert session. Restore the expert session through the usual dashboard if you want to align the agent's configured thresholds; verify the selected agent settings before validating.
2. Finish tagging, then **save** the dashboard session JSON, including any browser edits.
3. Expand **Final validation — independent (opt-in)** in the sidebar. Upload that JSON.
4. Enter reviewed ranges as JSON, for example `[{"start":"2026-01-01 00:00:00","end":"2026-01-01 02:00:00"}]` (example only, not assumed reviewed). Include empty-event time only if truly checked.
5. Enter the known UTC offset (`+00:00` etc.), actual sampling cadence (seconds), and maximum acceptable gap. For symptoms, enter an agreed positive minimum IoU; it is intentionally not hard-coded.
6. Confirm **every** field, and press Generate. If any input fails, no definitive score is emitted. For large sections over 300,000 samples, perform an offline, memory-controlled evaluation rather than bypassing the guard untested.
7. Download the independent JSON report; use its `validation_report` metrics for evaluation, **not** the legacy React table or 95% acceptance field.

## Validation/limitations

Tests run in the patch-authoring environment:

- Existing independent-validator unit suite (40 tests): PASS.
- Continuous helper tests: PASS.
- Session adapter/binary activity tests: PASS.
- React row-ID, browser-session-save row-ID and Python export regression tests: PASS.
- JSX parser/ Python syntax: PASS.

**Unverified here:** complete Streamlit runtime and Vite build (Streamlit/pyarrow and cached npm dependencies were unavailable); precise per-agent output against all original well logs; real browser timezone consistency; large-section memory performance; physical data-quality adequacy. Therefore both patches are **candidates for local integration testing**, not guaranteed production fixes.

The original dashboard's 12-hour **display-table** detector still runs each window independently and may still split detections at boundaries. This patch deliberately does not alter that working display pipeline; *only the new final validation calculation* uses full-section continuous processing. If you must fix the legacy table itself, that is a separate, higher-risk detector pipeline change.

## Apply/rollback

Use a new branch/commit for each step, never reapply a patch already applied. Run `git apply --check /path/patch2.patch`, apply it, run tests, commit; then repeat for Patch 3. Rebuild the React frontend after Patch 3:

```bash
cd streamlit_components/virtual_log_viewer/frontend
npm ci
npm run build
cd ../../..
python3 -m streamlit run app.py
```

After applying Patch 3, test: draw/edit/delete/restore tags; same-time tags with distinct IDs; scroll and confirm React preview changes do not change downloaded final report; saved-session export/reload; full section with a 12-hour boundary; sections with a time gap; single-sample detection; ordinary and narrow browser widths.

Revert the Patch 3 **commit** (recommended) or use `git apply -R /path/patch3.patch` if no overlapping changes were made. Rebuild frontend after reverting. Patch 2 can be independently reverted after Patch 3 is removed.

## Follow-up audit corrections

- Three further Hit Results deduplication paths were found: the Python viewport-history helper in `app.py`, and the browser-side session-save functions (`readBrowserHitResults` and `mergePayloadWithDrawnTags`) in `ui/sidebar.py`. All now preserve distinct active tag IDs. Old manually entered tags using source/label/time fallback identities are retained where verifiable. New regression tests cover these paths; rows with neither a durable ID nor an unambiguous legacy identity still cannot be perfectly disambiguated.
- The UI reports `status=partial...` as a warning rather than a success.
- The independent run rejects multiple selected sections, duplicated timestamps, and long data gaps until correct state resets across sections/gaps have been verified. This deliberately limits where definitive scoring is offered, without changing the live display.
