import pandas as pd
import plotly.graph_objects as go


def _add_section_boundaries(fig: go.Figure, section_ranges: list[dict], t_min_view, t_max_view):
    if not section_ranges or t_min_view is None or t_max_view is None:
        return

    total_ns = float((t_max_view - t_min_view).value)
    if total_ns <= 0:
        return

    def to_paper_y(t):
        frac = float((t - t_min_view).value) / total_ns
        return 1.0 - max(0.0, min(1.0, frac))

    for i, sr in enumerate(section_ranges):
        if i > 0:
            y_line = to_paper_y(sr["t_min"])
            if 0.01 < y_line < 0.99:
                fig.add_shape(
                    type="line",
                    x0=0,
                    x1=1,
                    xref="paper",
                    y0=y_line,
                    y1=y_line,
                    yref="paper",
                    line=dict(dash="dash", color="rgba(70,70,70,0.30)", width=1),
                    layer="above",
                )

        mid = sr["t_min"] + (sr["t_max"] - sr["t_min"]) / 2
        y_mid = max(0.02, min(0.98, to_paper_y(mid)))

        fig.add_annotation(
            xref="paper",
            yref="paper",
            x=0.006,
            y=y_mid,
            text=sr["label"],
            textangle=-90,
            showarrow=False,
            font=dict(size=9, color="#333"),
            bgcolor="rgba(255,255,255,0.65)",
            borderpad=2,
            xanchor="center",
            yanchor="middle",
        )


def _axis_name(base: str, axis_number: int) -> str:
    """
    Plotly axis reference names:
    axis 1 -> x / y
    axis 2 -> x2 / y2
    axis 3 -> x3 / y3
    axis 4 -> x4 / y4
    """
    return base if axis_number == 1 else f"{base}{axis_number}"


def _add_reference_line(fig: go.Figure, reference_time):
    """
    Add one continuous horizontal reference line across all 4 tracks.

    This uses:
    - xref='paper' so the line spans the full chart width
    - yref='y' because all subplot y-axes share the same datetime range
    """
    if reference_time is None:
        return

    reference_time = pd.Timestamp(reference_time)

    fig.add_shape(
        type="line",
        xref="paper",
        yref="y",
        x0=0,
        x1=1,
        y0=reference_time,
        y1=reference_time,
        line=dict(
            color="rgba(255, 0, 0, 0.95)",
            width=3,
            dash="solid",
        ),
        layer="above",
    )

    fig.add_annotation(
        xref="paper",
        yref="y",
        x=1.0,
        y=reference_time,
        text=reference_time.strftime("%Y-%m-%d %H:%M:%S"),
        showarrow=False,
        xanchor="right",
        yanchor="bottom",
        font=dict(size=10, color="rgba(255, 0, 0, 0.95)"),
        bgcolor="rgba(255,255,255,0.85)",
        bordercolor="rgba(255,0,0,0.45)",
        borderwidth=1,
    )