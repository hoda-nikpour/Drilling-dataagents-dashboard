import pandas as pd


def get_default_time_range(df: pd.DataFrame):
    """
    Return the full available time range from a dataframe index.
    The dataframe must use a DatetimeIndex.
    """
    if df.empty:
        return None

    return (df.index.min().to_pydatetime(), df.index.max().to_pydatetime())


def calculate_zoom_percent(t_min_all, t_max_all, selected_start, selected_end) -> float:
    """
    Streamlit time slider behavior:
    - Full range means 0% zoom.
    - Smaller selected range means higher zoom.
    """
    total_sec = (pd.Timestamp(t_max_all) - pd.Timestamp(t_min_all)).total_seconds()
    selected_sec = (pd.Timestamp(selected_end) - pd.Timestamp(selected_start)).total_seconds()

    if total_sec <= 0:
        return 0.0

    zoom_percent = 100.0 - (selected_sec / total_sec * 100.0)
    return max(0.0, min(100.0, zoom_percent))


def apply_time_filter(df: pd.DataFrame, time_range) -> pd.DataFrame:
    """
    Slice dataframe using the selected time range.
    This mirrors the filtering done after the Streamlit slider.
    """
    if df.empty or time_range is None:
        return df.copy()

    start, end = time_range
    return df.loc[pd.Timestamp(start) : pd.Timestamp(end)].copy()


def build_time_filter_result(df: pd.DataFrame, time_range) -> dict:
    """
    Combined time-filter result for testing and future app orchestration.
    """
    default_range = get_default_time_range(df)

    if default_range is None:
        return {
            "df_filtered": df.copy(),
            "time_range": None,
            "zoom_percent": 0.0,
            "default_time_range": None,
        }

    selected_range = time_range or default_range
    df_filtered = apply_time_filter(df, selected_range)

    zoom_percent = calculate_zoom_percent(
        t_min_all=default_range[0],
        t_max_all=default_range[1],
        selected_start=selected_range[0],
        selected_end=selected_range[1],
    )

    return {
        "df_filtered": df_filtered,
        "time_range": selected_range,
        "zoom_percent": zoom_percent,
        "default_time_range": default_range,
    }