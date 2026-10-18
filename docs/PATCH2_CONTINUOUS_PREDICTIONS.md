# Patch 2: continuous predictions for independent validation

**Base:** uploaded Git archive from commit `0a6d784`. **Apply after the independent validation-engine commit.**

Adds `services/validation_continuous.py` and its focused tests only. It does **not** modify `app.py`, agent algorithms, the React viewer, 12-hour dashboard navigation, or existing JSON/Excel exports.

Rather than claiming that independently evaluated 12-hour windows are state-preserving, the new helper evaluates the entire selected section *once* with the same activity, temporal-resolution and symptom agent functions. It checks that the loaded time index exactly matches the selected section's complete time index. A resource guard (300,000 samples) prevents an unbounded automatic full-section computation in Streamlit. It also constructs prediction coverage from actual sample timestamps, excluding gaps longer than an explicitly supplied maximum gap. Requires an explicitly confirmed UTC offset and sample cadence; never invents them. When normalizing sampled model intervals for evaluation, it extends `end` by one **verified sample cadence** because the existing model utilities store the **last included sample timestamp** in their `end` field; raw agent outputs are preserved.

**IMPORTANT:** Patch 2 is a library, not a dashboard feature on its own; Patch 3 adds the opt-in UI integration. It does not repair the *legacy* window-by-window agent-interval table. The continuous-validation report is separated from that table. Sections larger than the guard cannot be scored in-app with these patches; increasing the guard without checking available RAM is unsafe. No full-production-data runtime test was possible in the patch-build environment.

Tests: `python3 -m unittest discover -s tests -p 'test_validation_continuous.py' -v`.

## Independent safety audit (18 Oct 2026)

- The timestamp index must be unique, sorted, and nonmissing. Duplicated clock times, including overlaps between selected sections, are **not evaluable** without a supported row-identity policy.
- Cadence and allowed-gap inputs must be finite positive numbers.
- A continuous detector must **not** carry state through a gap larger than the configured maximum gap. The `assert_unbroken_prediction_state` guard refuses multi-span coverage until a verified gap-aware reset/split runner is available; the panel also currently requires a single selected section.
- Coverage is inferred from data timestamps plus a user-confirmed cadence and gap policy; the operator must still verify data quality and timezones. Source-data quality cannot be proven by index equality alone.
