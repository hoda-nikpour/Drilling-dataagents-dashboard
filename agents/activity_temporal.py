"""Temporal activity-state resolver for drilling activity agents.

This module is intentionally additive: it sits *after* the existing instantaneous
rule engine.  The existing priority order still resolves simultaneous rules; this
module then adds:

1. a configurable state-transition graph,
2. temporal confirmation (hysteresis) to suppress one-sample flicker,
3. retrospective/back-dated correction once enough future samples confirm a state.

The output ``activity_resolved`` should be used by downstream event agents instead
of the instantaneous/raw activity.  That is what makes event generation consistent
with retrospectively corrected activities.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, MutableSequence, Sequence

import numpy as np
import pandas as pd


ACTIVITY_PRIORITY: tuple[str, ...] = (
    "MakingConnection",
    "Drilling",
    "Reaming",
    "TrippingIn",
    "TrippingOut",
    "Conditioning",
    "Circulating",
    "Other",
)

ALL_ACTIVITIES = frozenset(ACTIVITY_PRIORITY)

# A deliberately permissive "likely transitions" graph.  It captures the examples
# in the review (Reaming -> TrippingOut and TrippingIn -> Conditioning/Circulating)
# without pretending that every rig/well uses exactly the same operational sequence.
# A sustained disallowed transition can still be accepted via override confirmation.
DEFAULT_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "MakingConnection": frozenset(
        {"MakingConnection", "Drilling", "Reaming", "Conditioning", "Circulating", "Other"}
    ),
    "Drilling": frozenset(
        {"Drilling", "MakingConnection", "Reaming", "Conditioning", "Circulating", "TrippingOut", "Other"}
    ),
    "Reaming": frozenset(
        {
            "Reaming",
            "Drilling",
            "MakingConnection",
            "TrippingOut",
            "TrippingIn",
            "Conditioning",
            "Circulating",
            "Other",
        }
    ),
    "TrippingIn": frozenset(
        {
            "TrippingIn",
            "Reaming",
            "Drilling",
            "MakingConnection",
            "Conditioning",
            "Circulating",
            "Other",
        }
    ),
    "TrippingOut": frozenset(
        {"TrippingOut", "Reaming", "TrippingIn", "Conditioning", "Circulating", "Other"}
    ),
    "Conditioning": frozenset(ALL_ACTIVITIES),
    "Circulating": frozenset(ALL_ACTIVITIES),
    "Other": frozenset(ALL_ACTIVITIES),
}


@dataclass(frozen=True)
class TemporalActivityConfig:
    """Configuration for retrospective activity-state resolution.

    Parameters
    ----------
    confirm_samples:
        Consecutive samples required for a transition listed in the state graph.
        For 1 Hz data, 3 means roughly three seconds of confirmation.
    override_confirm_samples:
        Consecutive samples required for a transition not in the state graph.  This
        prevents the graph from permanently blocking a legitimate but unusual state.
    max_backdate_samples:
        Maximum number of samples rewritten when a transition is finally confirmed.
        Set >= ``override_confirm_samples`` if you want the full pending interval
        reclassified after confirmation.
    unknown_as_other:
        Convert missing/unrecognised raw activity labels to ``Other``.  If False,
        unrecognised labels raise ValueError.
    """

    confirm_samples: int = 3
    override_confirm_samples: int = 8
    max_backdate_samples: int = 30
    unknown_as_other: bool = True

    def __post_init__(self) -> None:
        if self.confirm_samples < 1:
            raise ValueError("confirm_samples must be >= 1")
        if self.override_confirm_samples < self.confirm_samples:
            raise ValueError("override_confirm_samples must be >= confirm_samples")
        if self.max_backdate_samples < 1:
            raise ValueError("max_backdate_samples must be >= 1")


def normalize_activity(value: object, *, unknown_as_other: bool = True) -> str:
    """Return a canonical activity label used by the state resolver."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "Other"
    text = str(value).strip()
    if text in ALL_ACTIVITIES:
        return text

    # Common formatting variants from dashboards/CSV files.
    compact = "".join(ch for ch in text.lower() if ch.isalnum())
    aliases = {
        "makingconnection": "MakingConnection",
        "connection": "MakingConnection",
        "drilling": "Drilling",
        "reaming": "Reaming",
        "trippingin": "TrippingIn",
        "tripin": "TrippingIn",
        "trippingout": "TrippingOut",
        "tripout": "TrippingOut",
        "conditioning": "Conditioning",
        "circulating": "Circulating",
        "other": "Other",
    }
    if compact in aliases:
        return aliases[compact]
    if unknown_as_other:
        return "Other"
    raise ValueError(f"Unknown activity label: {value!r}")


def priority_activity_from_flags(
    df: pd.DataFrame,
    flag_columns: Mapping[str, str],
    *,
    priority: Sequence[str] = ACTIVITY_PRIORITY,
    output_col: str = "activity_priority",
) -> pd.Series:
    """Resolve simultaneous boolean activity rules using the existing A9 priority.

    Parameters
    ----------
    df:
        Input dataframe containing boolean rule-result columns.
    flag_columns:
        Mapping ``activity -> dataframe column``. Example::

            {
                "MakingConnection": "rule_connection",
                "Drilling": "rule_drilling",
                ...
            }

    Returns
    -------
    pandas.Series
        One instantaneous activity per row.  If no supplied rule is true, ``Other``.
    """
    missing = [col for col in flag_columns.values() if col not in df.columns]
    if missing:
        raise KeyError(f"Missing rule columns: {missing}")

    result = pd.Series("Other", index=df.index, dtype="object", name=output_col)
    undecided = pd.Series(True, index=df.index)

    for activity in priority:
        if activity == "Other":
            continue
        col = flag_columns.get(activity)
        if col is None:
            continue
        mask = df[col].fillna(False).astype(bool) & undecided
        result.loc[mask] = activity
        undecided.loc[mask] = False

    return result


def _validate_transition_map(
    transitions: Mapping[str, Iterable[str]],
) -> dict[str, frozenset[str]]:
    clean: dict[str, frozenset[str]] = {}
    for source in ALL_ACTIVITIES:
        targets = transitions.get(source, {source, "Other"})
        normalised_targets = frozenset(normalize_activity(v, unknown_as_other=False) for v in targets)
        clean[source] = normalised_targets | {source}
    return clean


def resolve_activity_temporally(
    df: pd.DataFrame,
    *,
    raw_activity_col: str,
    config: TemporalActivityConfig | None = None,
    transitions: Mapping[str, Iterable[str]] | None = None,
    output_col: str = "activity_resolved",
) -> pd.DataFrame:
    """Apply state transitions, confirmation and retrospective backdating.

    Notes
    -----
    This is an *offline/short-latency* resolver because confirmation uses future
    samples.  In a live dashboard the most recent ``confirm_samples - 1`` rows are
    naturally provisional.  Re-running this function as new rows arrive updates
    those provisional rows and therefore provides the requested reconsideration.
    """
    if raw_activity_col not in df.columns:
        raise KeyError(f"{raw_activity_col!r} is not present in dataframe")

    cfg = config or TemporalActivityConfig()
    graph = _validate_transition_map(transitions or DEFAULT_ALLOWED_TRANSITIONS)

    out = df.copy()
    raw = [
        normalize_activity(v, unknown_as_other=cfg.unknown_as_other)
        for v in out[raw_activity_col].tolist()
    ]

    n = len(raw)
    if n == 0:
        out[output_col] = pd.Series(dtype="object")
        out["activity_transition_status"] = pd.Series(dtype="object")
        out["activity_is_provisional"] = pd.Series(dtype=bool)
        return out

    resolved: MutableSequence[str] = [raw[0]] * n
    status: MutableSequence[str] = ["initial"] + ["held"] * (n - 1)
    provisional = np.zeros(n, dtype=bool)

    committed = raw[0]
    pending_state: str | None = None
    pending_start: int | None = None
    pending_count = 0

    for i in range(1, n):
        proposed = raw[i]


        if proposed == committed:
            # A previously proposed transition was not confirmed.
            # Clear its provisional flags because later data rejected it.
            if pending_start is not None:
                for j in range(pending_start, i):
                    provisional[j] = False
                    status[j] = "rejected_unconfirmed"

            resolved[i] = committed
            status[i] = "stable"
            pending_state = None
            pending_start = None
            pending_count = 0
            continue

        

        is_likely = proposed in graph.get(committed, frozenset())
        required = cfg.confirm_samples if is_likely else cfg.override_confirm_samples

        if pending_state != proposed:
            # A different unconfirmed transition has appeared.
            # The previous candidate is therefore rejected.
            if pending_state is not None and pending_start is not None:
                for j in range(pending_start, i):
                    provisional[j] = False
                    status[j] = "rejected_unconfirmed"

            pending_state = proposed
            pending_start = i
            pending_count = 1
        else:
            pending_count += 1

        resolved[i] = committed
        provisional[i] = True
        status[i] = "pending_likely" if is_likely else "pending_override"

        if pending_count >= required:
            assert pending_start is not None
            # Back-date only as far as configured.  Normally max_backdate_samples is
            # larger than the confirmation window, so the full pending interval moves.
            earliest_backdate = max(pending_start, i - cfg.max_backdate_samples + 1)
            for j in range(earliest_backdate, i + 1):
                resolved[j] = proposed
                provisional[j] = False
                status[j] = "confirmed_backdated"

            committed = proposed
            pending_state = None
            pending_start = None
            pending_count = 0

    out[output_col] = pd.Series(resolved, index=out.index, dtype="object")
    out["activity_transition_status"] = pd.Series(status, index=out.index, dtype="object")
    out["activity_is_provisional"] = pd.Series(provisional, index=out.index, dtype=bool)
    return out


def transition_table(
    transitions: Mapping[str, Iterable[str]] | None = None,
) -> pd.DataFrame:
    """Return the state graph as an adjacency table for display/debugging."""
    graph = _validate_transition_map(transitions or DEFAULT_ALLOWED_TRANSITIONS)
    rows = []
    for source in ACTIVITY_PRIORITY:
        for target in ACTIVITY_PRIORITY:
            rows.append(
                {
                    "from_activity": source,
                    "to_activity": target,
                    "likely_transition": target in graph[source],
                }
            )
    return pd.DataFrame(rows)
