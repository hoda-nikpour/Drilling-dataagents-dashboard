# DrillMate validation core — additive, non-invasive patch

**What this changes:** Adds `drillmate_validation/`, `tools/validate_drilling_events.py`, tests and documentation. Does **not** modify `app.py`, `ui/sidebar.py`, React, Plotly, existing session JSON, Excel exports, or automatic detection algorithms.

**What it does not yet change:** The dashboard's live Hit/Miss result and legacy 95% acceptance score still behave as before. This is an independent validation tool, not an integration of the dashboard into a finished scoring product.

## Apply safely

1. Commit or back up your existing checkout. Apply the **verified GitHub** height patch first **only if it matches your checkout**; use the ZIP height patch instead only with that historical ZIP. Rebuild `frontend/dist` after the height change.
2. From the repository root: `git apply --check /path/to/drillmate_validation_additive.patch`.
3. If the check succeeds: `git apply /path/to/drillmate_validation_additive.patch`.
4. Run: `python -m unittest discover -s tests -p 'test_drillmate_*.py' -v`.
5. For a normalized test file: `python tools/validate_drilling_events.py docs/validation_example_symptom.json --output sample_report.json`.
6. Keep the old dashboard unchanged while you compare reports against selected known-good examples.

The patch itself can be applied even if the height change is postponed: files do not overlap.

## Required inputs for symptom *event* validation

The input is a **separately normalized** JSON report request. It is **not** an existing dashboard session JSON. Importing raw dashboard sessions safely requires an adapter developed against the actual checked-out source/schema.

- `schema_version`: integer `1`.
- `well`, `section`, `agent`: nonempty strings.
- `agent_kind`: `"symptom"`.
- `reviewed_intervals`: explicit time ranges Tommy confirms he examined **completely** (including reviewed quiet periods with no tags). Adjacent ranges may be merged.
- `prediction_coverage`: independent evidence of which timestamps were actually processed by the agent; NOT inferred from the first and last detections.
- `predictions_complete`: set `true` only after ensuring every detection in the reviewed ranges is present, including across pagination/windows.
- `prediction_generation`: `"continuous"` or `"state_preserving_windows"` **only after verification**. If independent-window runs have not been checked against a continuous baseline, do not falsely mark them verified.
- `expert_tags`: objects `{id,agent,start,end}`. `id` must be unique and stable. The *agent* comes from the selected dashboard agent; don't compare it with the visual names like `Dragged Tag 1`.
- `predictions`: similarly shaped agent events. Repeated IDs are **rejected**; fix/merge genuine duplicates during normalization. Coincident intervals with different IDs are **not silently deduplicated**.
- `matching`: e.g. `{ "version":"event-v1.0", "method":"iou_one_to_one", "min_iou":0.25, "min_overlap_seconds":0 }`. **0.25 is a demonstration value, not a drilling-engineering default**. Agree agent-specific settings in advance.
- `sample_cadence_seconds`: required if any prediction has identical start and end timestamps. Use the *actual known sampling interval*, not an invented constant.

All timestamps must be timezone-aware ISO 8601, e.g. `2026-01-01T00:00:10Z` or `2026-01-01T01:00:10+01:00`. Normalize your source times before making the input. `[start,end)` intervals make touching boundaries have zero overlap. A zero-duration expert tag is invalid; a point prediction is expanded **for evaluation only** with explicit sample cadence.

No score is produced when required review coverage, prediction coverage, generation verification, or time interpretation is missing.

## Event matching and scope

- Candidate edge: strictly positive time overlap and minimum intersection-over-union (IoU) and overlap seconds.
- Deterministic **maximum-cardinality one-to-one** bipartite assignment. One predicted event cannot earn two TPs; matching preference uses descending individual IoU, but does *not* claim globally maximal sum(IoU).
- `TP`: unique matched expert/prediction pair. `FN`: unmatched fully reviewed expert event. `FP`: unmatched prediction **wholly within a reviewed interval**.
- Predictions entirely outside the review periods are excluded.
- Unmatched predictions crossing the review boundary are recorded as `partial_boundary_prediction_ids`. Since they could be false positives or valid outside-scope events, report `status=partial_boundary_predictions_review_required`, `FP=null`, `precision=null`, `F1=null` until the coverage is extended or those events are adjudicated. `FP_lower_bound` is available but MUST NOT be used as a definitive FP count.
- Separate interval-*coverage* measure: union of expert duration overlapped by any prediction / union expert duration. A long prediction covering several expert tags may score well here, **without giving multiple event TPs**. If no expert intervals exist, time coverage is N/A.
- Precision/recall/F1 denominators of zero yield JSON `null` (N/A), not guessed perfect scores or true negatives.

## Activity validation (separate path)

Pass `agent_kind="activity"`, `activity_labels`, `expert_activities`, `predicted_activities`, review and prediction coverage, verified prediction generation, and the normal well/section fields. Each labeled segment is `{id, activity, start, end}`. Both timelines must be **exhaustive, non-overlapping and restricted to reviewed time**. Partially reviewed/ambiguous time should be excluded from the reviewed manifest rather than forced to a class. Reports contain time-weighted accuracy and duration-based confusion/precision/recall/F1 per activity — not event TP/FP/FN.

This module does **not** automatically repair the dormant `manual_activity_tags=[]` Python code path or infer activities from `Dragged Tag` display labels. An adapter must reliably obtain expert activities and the class names from the dashboard context.

## Important limits and unfinished integration

1. **The standalone validator does not repair section-wide agent windowing.** Confirm history-dependent detections across 12-hour window boundaries, stitch/merge safely as appropriate to the specific agent, and compare against continuous processing before setting `prediction_generation` to verified. A `prediction_coverage` manifest by itself cannot prove that the algorithm output is complete or correct.
2. **The standalone validator does not freeze the React viewport dependent Hit/Miss table.** Its outputs are authoritative only for inputs proven complete. Keep the old live table a *navigation aid*, not a performance report.
3. **The standalone validator does not change the React results deduplication.** A precise fix requires the current source, the row schema, and a saved-session compatibility check. Do not assume that an expert display label is a stable ID.
4. **The standalone validator does not update/deprecate `score_percent` or `accepted` in stored sessions.** Keep these as legacy fields; do not interpret them as precision/recall/F1.
5. Evaluation scope is one chosen agent and one well/section. For symptom agents the contract assumes selected-agent tags, not a multiclass mixture.
6. The caller is responsible for supplying truthful provenance (`predictions_complete` and `prediction_generation`); the code cannot validate a claim of completeness without raw data and a checked detection pipeline.
7. Synthetic unit tests do not guarantee behavior in the deployed application. Run end-to-end tests with original drilling data and real saved tag sessions before release.

## Suggested full-integration steps after a current repository ZIP is available

- Add a **read-only export adapter** from session JSON and well-section context to the normalized schema. Do not change session storage.
- Produce a verified complete prediction set for each reviewed window and the selected agent, preserving warmup/state across boundaries, with a regression comparison to continuous evaluation.
- Add one separate `Generate validation report` entry point, clearly distinguished from live Hit Results. Do not mutate old fields.
- Implement (and test) stable tag-ID handling in `normalizeRowsForServer()` without changing existing Excel headers or replay format.
- Verify vertical sizing after the audited height patch on Streamlit, plus scrolling while a tag remains in the saved ledger.

## Exit codes

- `0`: complete evaluated report.
- `3`: report generated but boundary predictions are unresolved; definitive FP/Precision/F1 withheld.
- `2`: invalid / incomplete / not evaluable input, or unsafe output overwrite.

The CLI refuses to overwrite an existing output report or its input.
