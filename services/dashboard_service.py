import pandas as pd

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