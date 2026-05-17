"""
Synthesis view — the dashboard's Home page.

Renders the cross-domain narrative produced from health.db (or documented
fallback while ingests are still landing). All charts are deterministic
plotly; no LLM calls. Owned by the dashboard agent (`app/`).

Layout, top to bottom:
  1. Hero verdict + 4 KPI cards
  2. Short-term priorities (3 cards)
  3. Long-term trajectory + family longevity
  4. Four-win panel (decade-scale improvements)
  5. This-week adherence (nutrition radar + sleep stats)
  6. All-outcomes 13-tile grid
  7. Roadmap (3 tiers)
"""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from app.synthesis_data import SynthesisData

# Color palette — kept in one place so tier semantics stay consistent
COLOR = {
    "good":     "#10b981",
    "watch":    "#f59e0b",
    "alert":    "#f43f5e",
    "info":     "#0ea5e9",
    "gap":      "#6b7280",
    "muted":    "#94a3b8",
    "ink":      "#1f2937",
    "grid":     "#e5e7eb",
}

TIER_TO_COLOR = {
    "good":  COLOR["good"],
    "watch": COLOR["watch"],
    "alert": COLOR["alert"],
    "info":  COLOR["info"],
    "gap":   COLOR["gap"],
    "priority": COLOR["alert"],
    "improving": COLOR["good"],
    "on plan":   COLOR["good"],
    "dropping":  COLOR["good"],
}


# --------------------------------------------------------------------- helpers

def _pill(text: str, tier: str) -> str:
    color = TIER_TO_COLOR.get(tier, COLOR["muted"])
    return (
        f'<span style="display:inline-block;padding:2px 8px;border-radius:999px;'
        f'font-size:11px;font-weight:600;text-transform:uppercase;'
        f'letter-spacing:.05em;background:{color}22;color:{color};'
        f'border:1px solid {color}55;">{text}</span>'
    )


def _gauge_bar(pct: float, tier: str, target_pct: float | None = None) -> str:
    pct = max(0, min(100, pct))
    color = TIER_TO_COLOR.get(tier, COLOR["muted"])
    target_marker = ""
    if target_pct is not None:
        target_marker = (
            f'<div style="position:absolute;top:-2px;bottom:-2px;'
            f'left:{target_pct}%;width:2px;background:{COLOR["good"]};"></div>'
        )
    return (
        f'<div style="position:relative;height:8px;background:#1f2937;border-radius:999px;'
        f'overflow:hidden;margin-top:6px;">'
        f'<div style="width:{pct}%;height:100%;background:{color};border-radius:999px;"></div>'
        f"{target_marker}"
        f"</div>"
    )


def _section_header(eyebrow: str, title: str, subtitle: str | None = None) -> None:
    st.markdown(
        f'<div style="margin-top:1.5rem;">'
        f'<div style="font-size:11px;font-weight:600;text-transform:uppercase;'
        f'letter-spacing:.15em;color:{COLOR["muted"]};">{eyebrow}</div>'
        f'<div style="font-size:1.5rem;font-weight:700;line-height:1.2;'
        f'margin-top:.25rem;">{title}</div>'
        + (
            f'<div style="color:{COLOR["muted"]};font-size:.9rem;margin-top:.5rem;'
            f'max-width:48rem;">{subtitle}</div>'
            if subtitle
            else ""
        )
        + "</div>",
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------- KPI tile

def _kpi_tile(kpi: dict) -> None:
    color = TIER_TO_COLOR.get(kpi["status"], COLOR["muted"])
    delta_arrow = "▼" if kpi["delta"] < 0 else "▲"
    delta_color = COLOR["good"] if (
        (kpi["status"] in ("improving", "on plan", "dropping") and kpi["delta"] < 0)
        or (kpi["status"] in ("improving", "on plan") and kpi["delta"] > 0)
    ) else color
    with st.container(border=True):
        st.markdown(
            f'<div style="display:flex;justify-content:space-between;align-items:center;'
            f'margin-bottom:.5rem;">'
            f'<span style="font-size:11px;font-weight:600;text-transform:uppercase;'
            f'letter-spacing:.1em;color:{COLOR["muted"]};">{kpi["label"]}</span>'
            f"{_pill(kpi['status'], kpi['status'])}"
            f"</div>"
            f'<div style="font-family:ui-monospace,Menlo,monospace;font-size:1.9rem;'
            f'font-weight:700;line-height:1.1;">{kpi["value"]} '
            f'<span style="font-size:.85rem;color:{COLOR["muted"]};font-weight:400;">'
            f'{kpi["unit"]}</span></div>'
            f'<div style="font-size:.75rem;color:{COLOR["muted"]};margin-top:.25rem;">'
            f'<span style="color:{delta_color};font-weight:600;">{delta_arrow} {abs(kpi["delta"])}</span> '
            f'{kpi["delta_label"]} · target <span style="font-family:ui-monospace,Menlo,monospace;'
            f'color:{COLOR["good"]};">{kpi["target"]}</span></div>'
            f"{_gauge_bar(kpi['gauge_pct'], kpi['status'], kpi.get('target_pct'))}",
            unsafe_allow_html=True,
        )


# --------------------------------------------------------------------- charts

def _metabolic_chart(metabolic: dict) -> go.Figure:
    fig = go.Figure()
    palette = [COLOR["good"], COLOR["info"], COLOR["watch"], "#a78bfa"]
    for series, color in zip(metabolic["series"], palette):
        fig.add_trace(
            go.Scatter(
                x=metabolic["labels"],
                y=series["data"],
                mode="lines+markers",
                name=series["name"],
                line=dict(color=color, width=2),
                marker=dict(size=8, color=color),
                connectgaps=True,
            )
        )
    fig.update_layout(
        height=300,
        margin=dict(l=10, r=10, t=10, b=10),
        legend=dict(
            orientation="h", yanchor="bottom", y=-0.3, xanchor="center", x=0.5
        ),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(gridcolor=COLOR["grid"], showgrid=True),
        yaxis=dict(gridcolor=COLOR["grid"], showgrid=True),
        hovermode="x unified",
    )
    return fig


def _hdl_sparkline(hdl: dict) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=hdl["labels"],
            y=hdl["values"],
            mode="lines+markers",
            line=dict(color=COLOR["good"], width=2),
            marker=dict(
                size=8,
                color=[COLOR["good"]] * (len(hdl["values"]) - 1) + [COLOR["alert"]],
            ),
            fill="tozeroy",
            fillcolor="rgba(16,185,129,.15)",
            showlegend=False,
        )
    )
    fig.update_layout(
        height=120,
        margin=dict(l=10, r=10, t=10, b=20),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(showgrid=False, tickfont=dict(size=9)),
        yaxis=dict(visible=False, range=[30, 60]),
    )
    return fig


def _nutrient_radar(nutrients: list[dict]) -> go.Figure:
    names = [n["name"] for n in nutrients]
    pcts = [n["pct"] for n in nutrients]
    fig = go.Figure()
    fig.add_trace(
        go.Scatterpolar(
            r=[100] * len(names),
            theta=names,
            mode="lines",
            line=dict(color=COLOR["good"], width=1.5, dash="dash"),
            name="Target",
            showlegend=True,
        )
    )
    fig.add_trace(
        go.Scatterpolar(
            r=pcts,
            theta=names,
            fill="toself",
            line=dict(color=COLOR["watch"], width=2),
            fillcolor="rgba(245,158,11,.2)",
            name="49-day average (% of target)",
            showlegend=True,
        )
    )
    fig.update_layout(
        height=360,
        margin=dict(l=40, r=40, t=20, b=40),
        polar=dict(
            radialaxis=dict(range=[0, 120], tickvals=[25, 50, 75, 100], showticklabels=False),
            angularaxis=dict(tickfont=dict(size=11)),
            bgcolor="rgba(0,0,0,0)",
        ),
        legend=dict(
            orientation="h", yanchor="bottom", y=-0.15, xanchor="center", x=0.5
        ),
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def _sleep_histogram(hist: dict) -> go.Figure:
    colors = [
        COLOR["alert"], COLOR["watch"], COLOR["watch"], "#fbbf24",
        "#a3e635", COLOR["good"], COLOR["good"],
    ]
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=hist["labels"],
            y=hist["values"],
            marker_color=colors,
            showlegend=False,
        )
    )
    fig.update_layout(
        height=160,
        margin=dict(l=10, r=10, t=10, b=20),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(showgrid=False),
        yaxis=dict(visible=False),
    )
    return fig


# --------------------------------------------------------------------- sections

def _hero(data: SynthesisData) -> None:
    st.markdown(
        f'<div style="font-size:11px;font-weight:600;text-transform:uppercase;'
        f'letter-spacing:.15em;color:{COLOR["muted"]};">Where you stand</div>'
        f'<h1 style="font-size:2.4rem;font-weight:800;line-height:1.1;margin:.3rem 0;">'
        f'{data.headline["verdict_top"]} '
        f'<span style="color:{COLOR["good"]};">{data.headline["verdict_bottom"]}</span></h1>'
        f'<p style="color:{COLOR["muted"]};max-width:48rem;margin-top:.5rem;">'
        f'{data.headline["subtitle"]}</p>',
        unsafe_allow_html=True,
    )

    cols = st.columns(4)
    for col, kpi in zip(cols, data.kpis):
        with col:
            _kpi_tile(kpi)

    st.markdown(
        f'<div style="margin-top:1.25rem;padding:1.25rem;border-radius:.8rem;'
        f'background:linear-gradient(135deg,{COLOR["good"]}1a,transparent);'
        f'border:1px solid {COLOR["good"]}55;">'
        f'<div style="font-size:11px;font-weight:600;text-transform:uppercase;'
        f'letter-spacing:.15em;color:{COLOR["good"]};">This week\'s headline</div>'
        f'<div style="margin-top:.5rem;font-size:1.05rem;line-height:1.6;">'
        f'{data.headline["this_week"]}</div></div>',
        unsafe_allow_html=True,
    )


def _short_term(data: SynthesisData) -> None:
    _section_header(
        "Short term · next 90 days",
        "Three things to fix this quarter",
    )

    c1, c2, c3 = st.columns(3)

    with c1, st.container(border=True):
        st.markdown(
            f'<div style="display:flex;justify-content:space-between;align-items:center;">'
            f'<span style="font-family:ui-monospace,Menlo,monospace;font-size:.7rem;'
            f'color:{COLOR["muted"]};">PRIORITY 1</span>'
            f'{_pill("cardiovascular", "alert")}</div>'
            f'<div style="font-size:1.15rem;font-weight:700;margin-top:.5rem;">'
            f'Move ApoB below 80</div>'
            f'<p style="color:{COLOR["muted"]};font-size:.85rem;margin-top:.5rem;">'
            f'One year of −8 lb dropped ApoB only 5 points. The remaining lever is '
            f'<b>composition</b>, not quantity.</p>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f"""
- :green[↓] Saturated fat &lt; 15 g/day
- :green[↑] Fiber to 38 g/day (currently 14.5)
- :green[↑] Omega-3 to 1.6 g (currently 0.4)
- :green[⟳] Re-draw advanced lipid panel in 6 weeks
""",
            unsafe_allow_html=True,
        )

    with c2, st.container(border=True):
        st.markdown(
            f'<div style="display:flex;justify-content:space-between;align-items:center;">'
            f'<span style="font-family:ui-monospace,Menlo,monospace;font-size:.7rem;'
            f'color:{COLOR["muted"]};">PRIORITY 2</span>'
            f'{_pill("micronutrients", "watch")}</div>'
            f'<div style="font-size:1.15rem;font-weight:700;margin-top:.5rem;">'
            f'Plug five nutrient gaps</div>'
            f'<p style="color:{COLOR["muted"]};font-size:.85rem;margin-top:.5rem;">'
            f'49-day cut window has clear under-dosing. A targeted stack beats a generic multi.</p>',
            unsafe_allow_html=True,
        )
        for n in data.nutrients[-5:]:  # show the 5 below-target nutrients
            st.markdown(
                f'<div style="display:flex;justify-content:space-between;'
                f'font-size:.8rem;margin-top:.4rem;">'
                f'<span>{n["name"]}</span>'
                f'<span style="font-family:ui-monospace,Menlo,monospace;'
                f'color:{TIER_TO_COLOR[n["tier"]]};">{n["mean"]}</span></div>'
                f"{_gauge_bar(n['pct'], n['tier'])}",
                unsafe_allow_html=True,
            )

    with c3, st.container(border=True):
        st.markdown(
            f'<div style="display:flex;justify-content:space-between;align-items:center;">'
            f'<span style="font-family:ui-monospace,Menlo,monospace;font-size:.7rem;'
            f'color:{COLOR["muted"]};">PRIORITY 3</span>'
            f'{_pill("watch-flag", "watch")}</div>'
            f'<div style="font-size:1.15rem;font-weight:700;margin-top:.5rem;">'
            f"Don't lose HDL on the way down</div>"
            f'<p style="color:{COLOR["muted"]};font-size:.85rem;margin-top:.5rem;">'
            f'HDL dropped 16% (49 → 41) during the deficit — a known side-effect of '
            f'prolonged caloric restriction.</p>',
            unsafe_allow_html=True,
        )
        st.plotly_chart(_hdl_sparkline(data.hdl), use_container_width=True, config={"displayModeBar": False})
        st.markdown(
            """
- :green[▸] Cap deficit at 4 more weeks
- :green[▸] Add monounsaturated fat (olive oil, nuts)
- :green[▸] Re-check on next draw
""",
            unsafe_allow_html=True,
        )


def _long_term(data: SynthesisData) -> None:
    _section_header("Long term · the 10-year arc", "What a decade of data shows")

    left, right = st.columns([2, 1])

    with left, st.container(border=True):
        st.markdown(
            f'<div style="display:flex;justify-content:space-between;align-items:flex-start;">'
            f'<div><div style="font-weight:600;">Metabolic markers, 2015 → 2026</div>'
            f'<div style="font-size:.75rem;color:{COLOR["muted"]};margin-top:.25rem;">'
            f'Glucose, ALT, triglycerides, LDL-c</div></div>'
            f'{_pill("trending healthier", "good")}</div>',
            unsafe_allow_html=True,
        )
        st.plotly_chart(_metabolic_chart(data.metabolic), use_container_width=True, config={"displayModeBar": False})
        st.markdown(
            f'<p style="font-size:.8rem;color:{COLOR["muted"]};">'
            f'Across four draws, the body\'s <b>metabolic machinery</b> has measurably improved. '
            f'The improvement story is real — the cardiovascular particle story is the open question.</p>',
            unsafe_allow_html=True,
        )

    with right, st.container(border=True):
        fam = data.family
        st.markdown(
            f'<div style="font-weight:600;">Family longevity</div>'
            f'<div style="font-size:.75rem;color:{COLOR["muted"]};margin-top:.25rem;">'
            f'From {fam["n_entities"]} ancestors, {fam["n_edges"]} pedigree edges</div>'
            f'<div style="display:flex;align-items:baseline;gap:.5rem;margin-top:1rem;">'
            f'<span style="font-family:ui-monospace,Menlo,monospace;font-size:1.9rem;'
            f'font-weight:700;">~{fam["median_age"]}</span>'
            f'<span style="font-size:.85rem;color:{COLOR["muted"]};">yr · median age at death</span>'
            f'</div>'
            f'<div style="margin-top:1rem;font-size:.85rem;">'
            f'<div style="display:flex;justify-content:space-between;padding:.25rem 0;">'
            f'<span style="color:{COLOR["muted"]};">Paternal line</span>'
            f'<span style="font-family:ui-monospace,Menlo,monospace;">data complete</span></div>'
            f'<div style="display:flex;justify-content:space-between;padding:.25rem 0;">'
            f'<span style="color:{COLOR["muted"]};">Maternal line</span>'
            f'<span style="font-family:ui-monospace,Menlo,monospace;">data complete</span></div>'
            f'<div style="display:flex;justify-content:space-between;padding:.25rem 0;">'
            f'<span style="color:{COLOR["muted"]};">Causes of death</span>'
            f'{_pill("awaiting input", "gap")}</div></div>'
            f'<p style="font-size:.75rem;color:{COLOR["muted"]};margin-top:.75rem;line-height:1.5;">'
            f'A 20-minute pass to annotate causes of death for the 20 closest relatives '
            f'unlocks disease-specific risk priors.</p>',
            unsafe_allow_html=True,
        )

    # Four wins panel
    _section_header(
        "The four-win panel",
        "Where the body has clearly progressed",
    )
    cols = st.columns(4)
    for col, win in zip(cols, data.four_wins):
        with col, st.container(border=True):
            st.markdown(
                f'<div style="font-size:.75rem;color:{COLOR["muted"]};">{win["label"]}</div>'
                f'<div style="font-family:ui-monospace,Menlo,monospace;font-size:1.6rem;'
                f'font-weight:700;margin-top:.25rem;">{win["before"]} → {win["after"]}</div>'
                f'<div style="font-size:.75rem;margin-top:.25rem;">'
                f'<span style="color:{COLOR["good"]};font-weight:600;">▼ {abs(win["change_pct"])}%</span> '
                f'<span style="color:{COLOR["muted"]};">· {win["note"]}</span></div>',
                unsafe_allow_html=True,
            )


def _this_week(data: SynthesisData) -> None:
    _section_header("This week", "Adherence vs targets")

    left, right = st.columns(2)

    with left, st.container(border=True):
        st.markdown('<div style="font-weight:600;">Nutrition · 7-day averages</div>', unsafe_allow_html=True)
        st.plotly_chart(_nutrient_radar(data.nutrients), use_container_width=True, config={"displayModeBar": False})

    with right, st.container(border=True):
        sleep = data.sleep
        st.markdown(
            f'<div style="font-weight:600;">Sleep · last available data</div>'
            f'<div style="font-size:.75rem;color:{COLOR["muted"]};margin-top:.25rem;">'
            f'Weekly aggregates · May 2023 – Jan 2025</div>',
            unsafe_allow_html=True,
        )
        s1, s2, s3 = st.columns(3)
        s1.metric("Mean score", f'{sleep["mean_score"]}')
        s2.metric("Mean duration", sleep["mean_duration_label"])
        s3.metric("Poor weeks", f'{sleep["poor_pct"]}%')

        st.markdown(
            f'<div style="margin-top:1rem;padding:.75rem 1rem;border-radius:.5rem;'
            f'background:{COLOR["watch"]}1a;border:1px solid {COLOR["watch"]}55;">'
            f'<div style="color:{COLOR["watch"]};font-weight:600;font-size:.85rem;">'
            f'Data is 16 months stale.</div>'
            f'<div style="font-size:.8rem;color:{COLOR["muted"]};margin-top:.25rem;">'
            f"Sleep stopped logging {sleep['ends']}. Resuming daily sleep is the single highest-"
            f"leverage unlock — it powers 6 short-term insight templates.</div></div>",
            unsafe_allow_html=True,
        )

        st.markdown(
            f'<div style="font-size:.7rem;color:{COLOR["muted"]};text-transform:uppercase;'
            f'letter-spacing:.1em;margin-top:1rem;margin-bottom:.25rem;">'
            f'Score distribution at last read</div>',
            unsafe_allow_html=True,
        )
        st.plotly_chart(_sleep_histogram(sleep["histogram"]), use_container_width=True, config={"displayModeBar": False})


def _outcomes_grid(data: SynthesisData) -> None:
    _section_header(
        "All outcomes · 13 tiles",
        "The whole picture, at a glance",
        subtitle=(
            "Each tile answers one decidable question. "
            "Blocked tiles render in a degraded mode and tell you exactly what's needed."
        ),
    )
    # 3 columns of tiles
    cols = st.columns(3)
    for i, outcome in enumerate(data.outcomes):
        with cols[i % 3], st.container(border=True):
            st.markdown(
                f'<div style="display:flex;justify-content:space-between;align-items:flex-start;">'
                f'<div style="font-weight:600;font-size:.95rem;">{outcome["n"]} {outcome["title"]}</div>'
                f'{_pill(outcome["state"], outcome["tier"])}</div>'
                f'<p style="font-size:.78rem;color:{COLOR["muted"]};margin-top:.4rem;'
                f'line-height:1.5;">{outcome["note"]}</p>',
                unsafe_allow_html=True,
            )


def _roadmap(data: SynthesisData) -> None:
    _section_header("Roadmap", "What unlocks what")
    cols = st.columns(3)
    tier_color = {"1": COLOR["good"], "2": COLOR["info"], "3": COLOR["watch"]}
    for col, step in zip(cols, data.roadmap):
        color = tier_color.get(step["tier"], COLOR["muted"])
        with col, st.container(border=True):
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:.5rem;">'
                f'<div style="width:1.8rem;height:1.8rem;border-radius:999px;'
                f'background:{color}33;color:{color};display:flex;align-items:center;'
                f'justify-content:center;font-weight:700;'
                f'font-family:ui-monospace,Menlo,monospace;">{step["tier"]}</div>'
                f'<div style="font-weight:600;">Tier {step["tier"]} · {step["title"]}</div>'
                f'</div>'
                f'<ul style="margin-top:.5rem;padding-left:1.2rem;font-size:.85rem;line-height:1.7;">'
                + "".join(f"<li>{item}</li>" for item in step["items"])
                + f'</ul>'
                f'<p style="font-size:.75rem;color:{COLOR["muted"]};margin-top:.5rem;">'
                f'Unblocks: {step["unlocks"]}</p>',
                unsafe_allow_html=True,
            )


def _footer(data: SynthesisData) -> None:
    source_label = "live · health.db" if data.source == "db" else "documented fallback (no DB yet)"
    st.markdown(
        f'<hr style="margin-top:2rem;border-color:{COLOR["grid"]};">'
        f'<div style="display:flex;gap:1rem;font-size:.75rem;color:{COLOR["muted"]};'
        f'margin-top:1rem;flex-wrap:wrap;">'
        f'<span>1,929 observations · 6 sources · 11-year span</span>'
        f'<span>·</span>'
        f'<span>Local-first · no raw data leaves the machine</span>'
        f'<span>·</span>'
        f'<span style="font-family:ui-monospace,Menlo,monospace;">data source: {source_label}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------- entry

def render(data: SynthesisData) -> None:
    """Render the full Synthesis view into the current Streamlit page."""
    _hero(data)
    _short_term(data)
    _long_term(data)
    _this_week(data)
    _outcomes_grid(data)
    _roadmap(data)
    _footer(data)
