import pandas as pd
import numpy as np

from agents.activity_agents import build_activity_summary, classify_activities
from agents.symptom_agents import build_selected_symptom_agent


def build_sections_by_well(catalog: dict) -> dict[str, list[str]]:
    sections_by_well = {}

    for entry in catalog["sections"]:
        well = entry["well"]
        section = str(entry["section_in"])
        sections_by_well.setdefault(well, []).append(section)

    return sections_by_well


def flatten_selected_params(track_params: list[list[str]]) -> list[str]:
    seen = []

    for group in track_params:
        for item in group:
            if item not in seen:
                seen.append(item)

    return seen


def build_label_to_column_map(
    discovered_params: list[str],
    parameter_aliases: dict[str, list[str]],
) -> dict[str, str]:
    discovered_set = set(discovered_params)
    label_to_column = {}

    for label, aliases in parameter_aliases.items():
        for alias in aliases:
            if alias in discovered_set:
                label_to_column[label] = alias
                break

    return label_to_column


def build_available_param_labels(label_to_column: dict[str, str]) -> list[str]:
    return list(dict.fromkeys(label_to_column.keys()))


def make_context_key(selected_well: str, selected_sections: tuple[str, ...]) -> str:
    return f"{selected_well}__{'_'.join(selected_sections)}"


def build_parameter_catalog_df(
    label_to_column: dict[str, str],
    parameter_catalog: dict,
) -> pd.DataFrame:
    rows = []

    for label, raw_col in label_to_column.items():
        meta = parameter_catalog.get(label, {})
        rows.append(
            {
                "Parameter": label,
                "Raw mnemonic": raw_col,
                "Meaning": meta.get("meaning", ""),
                "Unit": meta.get("unit", ""),
                "Logical min": meta.get("logical_min", ""),
                "Logical max": meta.get("logical_max", ""),
            }
        )

    columns = ["Parameter", "Raw mnemonic", "Meaning", "Unit", "Logical min", "Logical max"]

    if not rows:
        return pd.DataFrame(columns=columns)

    return pd.DataFrame(rows, columns=columns).sort_values("Parameter").reset_index(drop=True)


def build_requested_columns(
    selected_labels: list[str],
    required_activity_labels: list[str],
    required_symptom_labels: list[str],
    label_to_column: dict[str, str],
) -> list[str]:
    selected_columns = [
        label_to_column[label]
        for label in selected_labels
        if label in label_to_column
    ]

    activity_columns = [
        label_to_column[label]
        for label in required_activity_labels
        if label in label_to_column
    ]

    symptom_columns = [
        label_to_column[label]
        for label in required_symptom_labels
        if label in label_to_column
    ]

    return list(dict.fromkeys(selected_columns + activity_columns + symptom_columns))


def prepare_track_plot_inputs(
    track_param_labels: list[list[str]],
    label_to_column: dict[str, str],
    track_colors: list[list[str]],
) -> tuple[list[list[str]], list[list[str]], list[list[str]]]:
    track_params_real = [
        [label_to_column[label] for label in track if label in label_to_column]
        for track in track_param_labels
    ]

    return (
        track_params_real + [[]],
        track_param_labels + [[]],
        track_colors + [[]],
    )


def empty_activity_result(df: pd.DataFrame) -> dict:
    return {
        "intervals": [],
        "summary_df": pd.DataFrame(),
        "labels": pd.Series(dtype="object"),
        "selected_activity": "All activities",
        "features": pd.DataFrame(index=df.index),
    }


def empty_symptom_result(df: pd.DataFrame, selected_symptom: str) -> dict:
    return {
        "intervals": [],
        "selected_symptom": selected_symptom,
        "features": pd.DataFrame(index=df.index),
    }


def run_activity_agent(
    df: pd.DataFrame,
    label_to_column: dict[str, str],
    activity_ui: dict,
) -> dict:
    if not activity_ui["enabled"]:
        return empty_activity_result(df)

    activity_labels, activity_features, activity_intervals = classify_activities(
        df=df,
        column_map=label_to_column,
        cfg=activity_ui["config"],
    )

    return {
        "intervals": activity_intervals,
        "summary_df": build_activity_summary(activity_labels),
        "labels": activity_labels,
        "selected_activity": activity_ui["selected_activity"],
        "features": activity_features,
    }


def run_symptom_agent(
    df: pd.DataFrame,
    label_to_column: dict[str, str],
    symptom_ui: dict,
    activity_ui: dict,
    activity_cfg: dict,
) -> dict:
    if not symptom_ui["enabled"] or not activity_ui["enabled"]:
        return empty_symptom_result(df, symptom_ui["selected_symptom"])

    symptom_features, symptom_intervals = build_selected_symptom_agent(
        df=df,
        column_map=label_to_column,
        symptom_name=symptom_ui["selected_symptom"],
        symptom_cfg=symptom_ui["config"],
        activity_features=activity_cfg["features"],
        activity_labels=activity_cfg["labels"],
    )

    return {
        "intervals": symptom_intervals,
        "selected_symptom": symptom_ui["selected_symptom"],
        "features": symptom_features,
    }

def _merge_alias_dicts(*alias_dicts: dict[str, list[str]]) -> dict[str, list[str]]:
    """
    Merge alias dictionaries while preserving priority order.

    Later dictionaries are added after earlier dictionaries unless the same
    alias already exists.
    """
    merged: dict[str, list[str]] = {}

    for alias_dict in alias_dicts:
        if not alias_dict:
            continue

        for label, aliases in alias_dict.items():
            merged.setdefault(label, [])

            for alias in aliases:
                if alias not in merged[label]:
                    merged[label].append(alias)

    return merged


def build_context_parameter_aliases(
    selected_well: str,
    selected_sections: tuple[str, ...],
    global_aliases: dict[str, list[str]],
    well_aliases: dict[str, dict[str, list[str]]] | None = None,
    section_aliases: dict[tuple[str, str], dict[str, list[str]]] | None = None,
) -> dict[str, list[str]]:
    """
    Build aliases for the selected well/sections.

    Priority:
    1. Section-specific aliases, if defined.
    2. Well-specific aliases, if defined.
    3. Global aliases as fallback.

    This lets F-10, F-15, and 34-10-C47 use different raw mnemonics while the
    rest of the dashboard continues to use logical names such as Bit Depth,
    Well Depth, MFI, SPP, etc.
    """
    well_aliases = well_aliases or {}
    section_aliases = section_aliases or {}

    section_specific: dict[str, list[str]] = {}

    for sec in selected_sections:
        key = (selected_well, str(sec))
        overrides = section_aliases.get(key, {})

        for label, aliases in overrides.items():
            section_specific.setdefault(label, [])

            for alias in aliases:
                if alias not in section_specific[label]:
                    section_specific[label].append(alias)

    return _merge_alias_dicts(
        section_specific,
        well_aliases.get(selected_well, {}),
        global_aliases,
    )


def build_label_to_column_map(
    discovered_params: list[str],
    parameter_aliases: dict[str, list[str]],
) -> dict[str, str]:
    """
    Map logical dashboard parameter names to raw dataframe columns.

    This version is schema-based: it chooses the first alias that exists in the
    selected parquet files. The diagnostic table below checks whether the chosen
    column also has valid and physically reasonable values.
    """
    discovered_set = set(discovered_params)
    label_to_column = {}

    for label, aliases in parameter_aliases.items():
        for alias in aliases:
            if alias in discovered_set:
                label_to_column[label] = alias
                break

    return label_to_column


def build_mapping_diagnostic_df(
    df: pd.DataFrame,
    label_to_column: dict[str, str],
    parameter_catalog: dict,
) -> pd.DataFrame:
    """
    Diagnostic table to confirm that each logical parameter is really connected
    to a sensible raw curve.

    This is very important for well-log data because different wells can use
    different mnemonic conventions.
    """
    rows = []

    n_rows = len(df)

    for label, raw_col in label_to_column.items():
        meta = parameter_catalog.get(label, {})
        logical_min = meta.get("logical_min", np.nan)
        logical_max = meta.get("logical_max", np.nan)

        if raw_col not in df.columns:
            rows.append(
                {
                    "Parameter": label,
                    "Raw mnemonic": raw_col,
                    "Valid %": 0.0,
                    "Min": np.nan,
                    "P50": np.nan,
                    "Max": np.nan,
                    "Logical min": logical_min,
                    "Logical max": logical_max,
                    "Status": "Missing raw column",
                }
            )
            continue

        s = pd.to_numeric(df[raw_col], errors="coerce")
        valid = s.dropna()
        valid_pct = (len(valid) / n_rows * 100.0) if n_rows > 0 else 0.0

        status_flags = []

        if valid.empty:
            status_flags.append("All NaN")

        if valid_pct < 10.0:
            status_flags.append("Very sparse")

        if not valid.empty:
            s_min = float(valid.min())
            s_med = float(valid.median())
            s_max = float(valid.max())

        if pd.notna(logical_min) and s_min < float(logical_min):
            status_flags.append("Has values below logical min")

        if pd.notna(logical_max) and s_max > float(logical_max):
            status_flags.append("Has values above logical max")

            # Important special checks.
            if label in {"Bit Depth", "Well Depth"}:
                if s_max < 100.0:
                    status_flags.append("Suspicious depth: too small")
                if s_max > 10000.0:
                    status_flags.append("Suspicious depth: too large / unit issue")

            if label == "BPOS":
                if s_max > 200.0:
                    status_flags.append("Suspicious BPOS: too large")

            if label == "RPMB":
                if s_max > 500.0:
                    status_flags.append("Suspicious RPM: too large")

            if label == "WOB":
                if s_min < -50.0 or s_max > 500.0:
                    status_flags.append("Suspicious WOB range")

            if label == "MFI":
                if s_max > 20000.0:
                    status_flags.append("Suspicious flow range / unit issue")

        else:
            s_min = np.nan
            s_med = np.nan
            s_max = np.nan

        rows.append(
            {
                "Parameter": label,
                "Raw mnemonic": raw_col,
                "Valid %": round(valid_pct, 1),
                "Min": s_min,
                "P50": s_med,
                "Max": s_max,
                "Logical min": logical_min,
                "Logical max": logical_max,
                "Status": "OK" if not status_flags else "; ".join(status_flags),
            }
        )

    columns = [
        "Parameter",
        "Raw mnemonic",
        "Valid %",
        "Min",
        "P50",
        "Max",
        "Logical min",
        "Logical max",
        "Status",
    ]

    return pd.DataFrame(rows, columns=columns).sort_values("Parameter").reset_index(drop=True)