"""Exact copy of app.py production temporal activity resolver for optional OFFLINE runs.

This module is separate to avoid importing Streamlit app.py (which executes UI
code at import). Regression tests require the resolver AST to stay in sync.
Existing online app.py and agents are NOT changed by this patch.
"""
from __future__ import annotations
import pandas as pd
from agents.activity_temporal import TemporalActivityConfig, resolve_activity_temporally
from agents.activity_agents import intervals_from_label_series, build_activity_summary

_PRODUCTION_TEMPORAL_ACTIVITY_CONFIG = TemporalActivityConfig(
    confirm_samples=3,
    override_confirm_samples=8,
    max_backdate_samples=30,
)


def _apply_temporal_activity_resolution(
    df: pd.DataFrame,
    activity_cfg: dict,
) -> dict:
    """
    Replace instantaneous activity labels with temporally resolved labels.

    The original activity classifier is kept unchanged. Its output is stored
    as ``activity_raw``. The temporal resolver then:

    1. checks state transitions,
    2. requires confirmation,
    3. suppresses short activity flicker,
    4. backdates confirmed transitions,
    5. exposes the corrected activity to downstream event agents.

    A COPY of activity_cfg is returned so the original dictionary is not
    unexpectedly mutated elsewhere.
    """

    if not isinstance(activity_cfg, dict):
        return activity_cfg

    labels = activity_cfg.get("labels")

    if labels is None:
        return activity_cfg

    # Preserve the dataframe index exactly.
    if isinstance(labels, pd.Series):
        raw_labels = labels.reindex(df.index).copy()
    else:
        try:
            raw_labels = pd.Series(labels, index=df.index)
        except (TypeError, ValueError):
            return activity_cfg

    if raw_labels.empty or raw_labels.notna().sum() == 0:
        return activity_cfg

    raw_labels = raw_labels.fillna("Other").astype(str)

    # The temporal resolver only needs the raw activity sequence.
    temporal_input = pd.DataFrame(
        {
            "__activity_raw": raw_labels,
        },
        index=df.index,
    )

    resolved_df = resolve_activity_temporally(
        temporal_input,
        raw_activity_col="__activity_raw",
        config=_PRODUCTION_TEMPORAL_ACTIVITY_CONFIG,
    )

    resolved_labels = (
        resolved_df["activity_resolved"]
        .reindex(df.index)
        .fillna(raw_labels)
    )

    # --------------------------------------------------------
    # Keep both versions available for debugging/validation.
    # --------------------------------------------------------
    df["activity_raw"] = raw_labels
    df["activity_resolved"] = resolved_labels

    if "activity_transition_status" in resolved_df.columns:
        df["activity_transition_status"] = (
            resolved_df["activity_transition_status"].reindex(df.index)
        )

    if "activity_is_provisional" in resolved_df.columns:
        df["activity_is_provisional"] = (
            resolved_df["activity_is_provisional"]
            .reindex(df.index)
            .fillna(False)
            .astype(bool)
        )

    # IMPORTANT:
    # From this point onward, "activity" means the corrected activity.
    df["activity"] = resolved_labels

    # --------------------------------------------------------
    # run_symptom_agent() receives activity_cfg, not only df.
    # Therefore replace activity_cfg["labels"] as well.
    # --------------------------------------------------------

    resolved_cfg = dict(activity_cfg)

    # Keep original instantaneous labels for debugging/comparison.
    resolved_cfg["labels_raw"] = raw_labels
#test
    # Production activity is now the confirmed/backdated result.
    resolved_cfg["labels"] = resolved_labels

    # Rebuild the activity intervals FROM THE RESOLVED LABELS.
    # This prevents the dashboard from displaying intervals that were
    # calculated from the old instantaneous activity classification.
    resolved_cfg["intervals"] = intervals_from_label_series(
        resolved_labels,
        min_samples=1,
    )

    # Rebuild the summary from the resolved labels as well.
    resolved_cfg["summary_df"] = build_activity_summary(
        resolved_labels
    )

    # Make the feature dataframe consistent with the corrected activity.
    features = resolved_cfg.get("features")
    if isinstance(features, pd.DataFrame):
        features = features.copy()
        features["activity_raw"] = raw_labels
        features["activity"] = resolved_labels
        resolved_cfg["features"] = features

    resolved_cfg["temporal_resolution_applied"] = True

    return resolved_cfg
