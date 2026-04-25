import pandas as pd


def _build_dual_time_ticks(t_min_view, t_max_view, n_ticks: int = 12):
    if t_min_view is None or t_max_view is None:
        return None, None

    vals = pd.date_range(start=t_min_view, end=t_max_view, periods=n_ticks)
    texts = [
        f"{ts.strftime('%d-%b-%y')}&nbsp;&nbsp;&nbsp;{ts.strftime('%H:%M:%S')}"
        for ts in vals
    ]
    return vals, texts