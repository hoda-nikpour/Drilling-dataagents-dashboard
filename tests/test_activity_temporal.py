import pandas as pd

from agents.activity_temporal import (
    TemporalActivityConfig,
    priority_activity_from_flags,
    resolve_activity_temporally,
)


def test_priority_order_preserved_when_multiple_rules_fire():
    df = pd.DataFrame(
        {
            "connection": [True, False],
            "drilling": [True, True],
            "reaming": [True, False],
        }
    )
    result = priority_activity_from_flags(
        df,
        {
            "MakingConnection": "connection",
            "Drilling": "drilling",
            "Reaming": "reaming",
        },
    )
    assert result.tolist() == ["MakingConnection", "Drilling"]


def test_one_sample_activity_flicker_is_suppressed():
    df = pd.DataFrame(
        {"raw": ["Drilling", "Drilling", "Reaming", "Drilling", "Drilling"]}
    )
    out = resolve_activity_temporally(
        df,
        raw_activity_col="raw",
        config=TemporalActivityConfig(confirm_samples=2, override_confirm_samples=4, max_backdate_samples=10),
    )
    assert out["activity_resolved"].tolist() == ["Drilling"] * 5


def test_reaming_to_tripping_out_is_confirmed_and_backdated():
    df = pd.DataFrame(
        {"raw": ["Reaming", "Reaming", "TrippingOut", "TrippingOut", "TrippingOut"]}
    )
    out = resolve_activity_temporally(
        df,
        raw_activity_col="raw",
        config=TemporalActivityConfig(confirm_samples=3, override_confirm_samples=6, max_backdate_samples=10),
    )
    assert out["activity_resolved"].tolist() == [
        "Reaming",
        "Reaming",
        "TrippingOut",
        "TrippingOut",
        "TrippingOut",
    ]
    assert out.loc[2, "activity_transition_status"] == "confirmed_backdated"


def test_tripping_in_to_conditioning_is_allowed():
    df = pd.DataFrame({"raw": ["TrippingIn", "Conditioning", "Conditioning"]})
    out = resolve_activity_temporally(
        df,
        raw_activity_col="raw",
        config=TemporalActivityConfig(confirm_samples=2, override_confirm_samples=5, max_backdate_samples=10),
    )
    assert out["activity_resolved"].tolist() == ["TrippingIn", "Conditioning", "Conditioning"]
