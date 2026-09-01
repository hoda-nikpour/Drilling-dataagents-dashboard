from __future__ import annotations

from copy import deepcopy

import numpy as np
import pandas as pd


def _merge_rule(base: dict | None, override: dict | None) -> dict:
    merged = deepcopy(base or {})
    for key, value in (override or {}).items():
        merged[key] = value
    return merged


def build_context_cleaning_rules(
    selected_well: str,
    selected_sections: tuple[str, ...],
    global_rules: dict[str, dict],
    well_rules: dict[str, dict[str, dict]] | None = None,
    section_rules: dict[tuple[str, str], dict[str, dict]] | None = None,
) -> dict[str, dict]:
    """
    Build cleaning rules for the selected well/sections.

    Priority:
    1. Global cleaning rule
    2. Well-specific override
    3. Section-specific override
    """
    well_rules = well_rules or {}
    section_rules = section_rules or {}

    context_rules = deepcopy(global_rules)

    for label, override in well_rules.get(selected_well, {}).items():
        context_rules[label] = _merge_rule(context_rules.get(label, {}), override)

    for sec in selected_sections:
        key = (selected_well, str(sec))
        for label, override in section_rules.get(key, {}).items():
            context_rules[label] = _merge_rule(context_rules.get(label, {}), override)

    return context_rules


def _safe_clean_col_name(raw_col: str) -> str:
    return f"{raw_col}__clean"


def _safe_quality_col_name(raw_col: str) -> str:
    return f"{raw_col}__quality"


def _clean_one_series(
    raw: pd.Series,
    rule: dict,
) -> tuple[pd.Series, pd.Series, dict]:
    s_raw = pd.to_numeric(raw, errors="coerce")
    s_clean = s_raw.copy()

    quality = pd.Series("ok", index=raw.index, dtype="object")
    quality.loc[s_raw.isna()] = "missing"

    # Convert inf values to NaN.
    inf_mask = np.isinf(s_clean)
    if inf_mask.any():
        s_clean.loc[inf_mask] = np.nan
        quality.loc[inf_mask] = "infinite_invalid"

    hard_min = rule.get("hard_min")
    hard_max = rule.get("hard_max")
    zero_drift_min = rule.get("zero_drift_min")
    clip_small_negative_to_zero = bool(rule.get("clip_small_negative_to_zero", False))

    # Small negative zero drift:
    # Example: WOB=-0.3 becomes 0.0, not invalid.
    zero_drift_mask = pd.Series(False, index=raw.index)

    if (
        clip_small_negative_to_zero
        and zero_drift_min is not None
    ):
        zero_drift_mask = (
            s_clean.notna()
            & (s_clean < 0.0)
            & (s_clean >= float(zero_drift_min))
        )

        s_clean.loc[zero_drift_mask] = 0.0
        quality.loc[zero_drift_mask] = "zero_drift_corrected"

    below_hard_min = pd.Series(False, index=raw.index)
    above_hard_max = pd.Series(False, index=raw.index)

    if hard_min is not None:
        below_hard_min = s_clean.notna() & (s_clean < float(hard_min))
        s_clean.loc[below_hard_min] = np.nan
        quality.loc[below_hard_min] = "below_hard_min_invalid"

    if hard_max is not None:
        above_hard_max = s_clean.notna() & (s_clean > float(hard_max))
        s_clean.loc[above_hard_max] = np.nan
        quality.loc[above_hard_max] = "above_hard_max_invalid"

    summary = {
        "Raw non-null": int(s_raw.notna().sum()),
        "Clean non-null": int(s_clean.notna().sum()),
        "Missing": int((quality == "missing").sum()),
        "Zero drift corrected": int((quality == "zero_drift_corrected").sum()),
        "Below hard min invalid": int((quality == "below_hard_min_invalid").sum()),
        "Above hard max invalid": int((quality == "above_hard_max_invalid").sum()),
        "Infinite invalid": int((quality == "infinite_invalid").sum()),
    }

    return s_clean, quality, summary


def apply_cleaning_layer(
    df: pd.DataFrame,
    label_to_column: dict[str, str],
    cleaning_rules: dict[str, dict],
    required_activity_labels: list[str] | None = None,
    required_symptom_labels: list[str] | None = None,
) -> tuple[pd.DataFrame, dict[str, str], pd.DataFrame]:
    """
    Preserve raw columns and use pre-cleaned standalone-module
    columns when available.

    If a pre-cleaned pair is not available, fall back to the
    dashboard's existing cleaning rules.

    Returns:
    - df_out: dataframe with clean/quality columns
    - clean_label_to_column: logical label -> cleaned column
    - cleaning_summary_df: per-parameter cleaning summary
    """

    df_out = df.copy()

    clean_label_to_column: dict[str, str] = {}
    rows = []

    # Temporary verification lists.
    verify_reused = []
    verify_mixed = []
    verify_fallback = []

    for label, raw_col in label_to_column.items():

        if raw_col not in df_out.columns:
            continue

        rule = cleaning_rules.get(label, {})

        clean_col = _safe_clean_col_name(raw_col)
        quality_col = _safe_quality_col_name(raw_col)

        # ------------------------------------------
        # Detect standalone cleaner output
        # ------------------------------------------
        has_clean_col = clean_col in df_out.columns
        has_quality_col = quality_col in df_out.columns

        if has_clean_col != has_quality_col:
            raise RuntimeError(
                f"[VERIFY FAILED] {label} / {raw_col}: "
                f"clean exists={has_clean_col}, "
                f"quality exists={has_quality_col}"
            )

        if has_clean_col and has_quality_col:

            supplied_clean = pd.to_numeric(
                df_out[clean_col],
                errors="coerce",
            )

            supplied_quality = (
                df_out[quality_col]
                .astype("object")
            )

            # Rows processed by the standalone module
            # have a populated quality/status value.
            precleaned_mask = (
                supplied_quality.notna()
                & supplied_quality
                .astype(str)
                .str.strip()
                .ne("")
            )

        else:

            supplied_clean = None
            supplied_quality = None

            precleaned_mask = pd.Series(
                False,
                index=df_out.index,
            )

        # ==========================================
        # CASE 1
        # All rows already cleaned by standalone
        # ==========================================
        if (
            len(precleaned_mask) > 0
            and precleaned_mask.all()
        ):

            clean_series = supplied_clean.copy()
            quality_series = supplied_quality.copy()

            verify_reused.append(
                f"{label}:{int(precleaned_mask.sum())}"
            )

        # ==========================================
        # CASE 2
        # Mixed standalone-cleaned + legacy rows
        # ==========================================
        elif precleaned_mask.any():

            clean_series = supplied_clean.copy()
            quality_series = supplied_quality.copy()

            legacy_mask = ~precleaned_mask

            fallback_clean, fallback_quality, _ = (
                _clean_one_series(
                    raw=df_out.loc[legacy_mask, raw_col],
                    rule=rule,
                )
            )

            clean_series.loc[legacy_mask] = fallback_clean
            quality_series.loc[legacy_mask] = fallback_quality

            verify_mixed.append(
                f"{label}:"
                f"standalone={int(precleaned_mask.sum())},"
                f"fallback={int(legacy_mask.sum())}"
            )

        # ==========================================
        # CASE 3
        # Old/raw-only Parquet
        # ==========================================
        else:

            clean_series, quality_series, _ = (
                _clean_one_series(
                    raw=df_out[raw_col],
                    rule=rule,
                )
            )

            verify_fallback.append(label)

        # Final clean values used by plots + agents.
        df_out[clean_col] = clean_series.astype("float32")
        df_out[quality_col] = quality_series

        # ------------------------------------------
        # Build summary from whichever data actually
        # won: standalone output or dashboard fallback
        # ------------------------------------------
        q = quality_series.fillna("").astype(str)

        summary = {
            "Raw non-null": int(
                pd.to_numeric(
                    df_out[raw_col],
                    errors="coerce",
                ).notna().sum()
            ),
            "Clean non-null": int(
                pd.to_numeric(
                    clean_series,
                    errors="coerce",
                ).notna().sum()
            ),
            "Missing": int(
                q.str.contains(
                    "missing",
                    regex=False,
                ).sum()
            ),
            "Zero drift corrected": int(
                q.str.contains(
                    "zero_drift_corrected",
                    regex=False,
                ).sum()
            ),
            "Below hard min invalid": int(
                q.str.contains(
                    "below_hard_min_invalid",
                    regex=False,
                ).sum()
            ),
            "Above hard max invalid": int(
                q.str.contains(
                    "above_hard_max_invalid",
                    regex=False,
                ).sum()
            ),
            "Infinite invalid": int(
                q.str.contains(
                    "infinite_invalid",
                    regex=False,
                ).sum()
            ),
        }

        # IMPORTANT:
        # Keep dashboard logical mapping unchanged.
        clean_label_to_column[label] = clean_col

        raw_valid = pd.to_numeric(
            df_out[raw_col],
            errors="coerce",
        ).dropna()

        clean_valid = pd.to_numeric(
            df_out[clean_col],
            errors="coerce",
        ).dropna()

        rows.append(
            {
                "Parameter": label,
                "Raw mnemonic": raw_col,
                "Clean column": clean_col,
                "Quality column": quality_col,
                "Raw min": (
                    float(raw_valid.min())
                    if not raw_valid.empty
                    else np.nan
                ),
                "Raw P50": (
                    float(raw_valid.median())
                    if not raw_valid.empty
                    else np.nan
                ),
                "Raw max": (
                    float(raw_valid.max())
                    if not raw_valid.empty
                    else np.nan
                ),
                "Clean min": (
                    float(clean_valid.min())
                    if not clean_valid.empty
                    else np.nan
                ),
                "Clean P50": (
                    float(clean_valid.median())
                    if not clean_valid.empty
                    else np.nan
                ),
                "Clean max": (
                    float(clean_valid.max())
                    if not clean_valid.empty
                    else np.nan
                ),
                "Hard min": rule.get("hard_min", ""),
                "Hard max": rule.get("hard_max", ""),
                **summary,
            }
        )

    # -------------------------------------------------
    # TEMPORARY VERIFICATION
    # -------------------------------------------------
    print(
        "[VERIFY CLEANING] "
        f"reused={verify_reused} | "
        f"mixed={verify_mixed} | "
        f"dashboard_fallback={verify_fallback}"
    )

    # ----------------------------------------------
    # Existing dashboard agent-input validity masks
    # ----------------------------------------------
    required_activity_labels = (
        required_activity_labels or []
    )

    required_symptom_labels = (
        required_symptom_labels or []
    )

    if required_activity_labels:

        mask = pd.Series(
            True,
            index=df_out.index,
        )

        for label in required_activity_labels:

            clean_col = clean_label_to_column.get(label)

            if (
                clean_col is None
                or clean_col not in df_out.columns
            ):
                mask &= False
            else:
                mask &= df_out[clean_col].notna()

        df_out["dq_activity_inputs_ok"] = mask

    if required_symptom_labels:

        mask = pd.Series(
            True,
            index=df_out.index,
        )

        for label in required_symptom_labels:

            clean_col = clean_label_to_column.get(label)

            if (
                clean_col is None
                or clean_col not in df_out.columns
            ):
                mask &= False
            else:
                mask &= df_out[clean_col].notna()

        df_out["dq_symptom_inputs_ok"] = mask

    summary_df = pd.DataFrame(rows)

    if not summary_df.empty:
        summary_df = (
            summary_df
            .sort_values("Parameter")
            .reset_index(drop=True)
        )

    return (
        df_out,
        clean_label_to_column,
        summary_df,
    )