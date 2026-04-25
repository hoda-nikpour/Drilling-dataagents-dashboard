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


def _add_reference_line(fig: go.Figure, reference_time):
    fig.add_shape(
        type="line",
        x0=0,
        x1=1,
        xref="paper",
        y0=reference_time,
        y1=reference_time,
        yref="y",
        line=dict(color="rgba(255,0,0,0.55)", width=2),
    )