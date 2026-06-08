"""
graficos.py — Gráficos Nativos F&I
Visualizações interativas construídas diretamente do BIGBASE via Plotly.

Cada gráfico é um reflexo fiel dos gráficos existentes na planilha "BIG DASHBOARD F&I",
com a vantagem de serem interativos, filtráveis e sem dependência de sessão Excel.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from comissao import load_bigbase

# ─── Paleta fiel ao Excel ──────────────────────────────────────────────────────
_AZUL_NV      = "#4472C4"   # azul Excel (CONTRATOS NV)
_LARANJA_SN   = "#ED7D31"   # laranja Excel (CONTRATOS SN)
_VW_BLUE      = "#001E50"

_MESES_PT = {
    1: "JANEIRO", 2: "FEVEREIRO", 3: "MARÇO",    4: "ABRIL",
    5: "MAIO",    6: "JUNHO",     7: "JULHO",     8: "AGOSTO",
    9: "SETEMBRO",10: "OUTUBRO",  11: "NOVEMBRO", 12: "DEZEMBRO",
}

# ─── Helpers de data ──────────────────────────────────────────────────────────

def _meses_range(n: int = 6) -> list[tuple[int, int, str]]:
    """
    Retorna lista de (ano, mes, 'NOME') dos últimos n-1 meses completos
    + mês vigente, do mais antigo ao mais recente.
    """
    hoje = datetime.now()
    meses: list[tuple[int, int, str]] = []
    m, y = hoje.month, hoje.year
    for _ in range(n):
        meses.append((y, m, _MESES_PT[m]))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return list(reversed(meses))


def _periodo_atual() -> pd.Period:
    return pd.Period(datetime.now(), "M")


# ─── Gráfico 1 — Contratos NV vs SN por Mês ──────────────────────────────────

def _chart_contratos_nv_sn(df: pd.DataFrame) -> tuple[go.Figure, pd.DataFrame]:
    """
    Barras empilhadas: CONTRATOS NV (azul) vs CONTRATOS SN (laranja).
    Reproduz fielmente o gráfico da aba 'BIG DASHBOARD F&I'.

    Retorna (fig, df_tabela) para exibir a tabela resumo abaixo do gráfico.
    """
    meses = _meses_range(6)
    hoje  = _periodo_atual()

    # Coluna tipo_veiculo pode não existir se BIGBASE ainda não foi recarregado
    if "tipo_veiculo" not in df.columns:
        fig_vazio = go.Figure()
        fig_vazio.add_annotation(
            text="Coluna tipo_veiculo não encontrada — clique em 🔄 para recarregar o BIGBASE",
            xref="paper", yref="paper", x=0.5, y=0.5,
            showarrow=False,
            font=dict(size=14, color="#6b7280"),
        )
        fig_vazio.update_layout(
            template="plotly_white", height=300,
            xaxis=dict(visible=False), yaxis=dict(visible=False),
        )
        return fig_vazio, pd.DataFrame()

    # Filtra apenas N e S (ignora vazio, 0, etc.)
    df_tipo = df[
        df["tipo_veiculo"].fillna("").str.strip().str.upper().isin(["N", "S"])
    ].copy()

    if "data_pagto" in df_tipo.columns:
        df_tipo["_periodo"] = df_tipo["data_pagto"].dt.to_period("M")
    else:
        df_tipo["_periodo"] = pd.NaT

    nv_vals: list[int] = []
    sn_vals: list[int] = []

    for (y, m, _) in meses:
        period = pd.Period(year=y, month=m, freq="M")
        sub    = df_tipo[df_tipo["_periodo"] == period]
        nv_vals.append(int((sub["tipo_veiculo"].str.upper() == "N").sum()))
        sn_vals.append(int((sub["tipo_veiculo"].str.upper() == "S").sum()))

    labels = [nome for (_, _, nome) in meses]

    # ── Tendência M.A — média dos 3 últimos meses completos ──────────────────
    idx_completos = [
        i for i, (y, m, _) in enumerate(meses)
        if pd.Period(year=y, month=m, freq="M") < hoje
    ]
    if len(idx_completos) >= 1:
        ult3 = idx_completos[-3:]
        ma_nv = round(sum(nv_vals[i] for i in ult3) / len(ult3))
        ma_sn = round(sum(sn_vals[i] for i in ult3) / len(ult3))
    else:
        ma_nv = ma_sn = 0

    labels.append("TENDÊNCIA M.A")
    nv_vals.append(ma_nv)
    sn_vals.append(ma_sn)

    # ── Tabela resumo (igual à legenda da planilha) ───────────────────────────
    df_tabela = pd.DataFrame({
        "":            ["CONTRATOS SN", "CONTRATOS NV"],
        **{labels[i]: [sn_vals[i], nv_vals[i]] for i in range(len(labels))},
    })

    # ── Figura ────────────────────────────────────────────────────────────────
    total_vals = [nv + sn for nv, sn in zip(nv_vals, sn_vals)]
    y_max      = max(max(total_vals, default=0) * 1.18, 300)

    fig = go.Figure()

    # Barra NV (azul) — adicionada PRIMEIRO → fica na base
    fig.add_trace(go.Bar(
        name         = "CONTRATOS NV",
        x            = labels,
        y            = nv_vals,
        marker_color = _AZUL_NV,
        text         = [str(v) if v > 0 else "" for v in nv_vals],
        textposition = "inside",
        textfont     = dict(color="white", size=12, family="Inter, sans-serif"),
        insidetextanchor = "middle",
        hovertemplate= "<b>%{x}</b><br>NV: %{y}<extra></extra>",
    ))

    # Barra SN (laranja) — empilhada em cima
    fig.add_trace(go.Bar(
        name         = "CONTRATOS SN",
        x            = labels,
        y            = sn_vals,
        marker_color = _LARANJA_SN,
        text         = [str(v) if v > 0 else "" for v in sn_vals],
        textposition = "inside",
        textfont     = dict(color="white", size=12, family="Inter, sans-serif"),
        insidetextanchor = "middle",
        hovertemplate= "<b>%{x}</b><br>SN: %{y}<extra></extra>",
    ))

    fig.update_layout(
        barmode      = "stack",
        template     = "plotly_white",
        height       = 440,
        plot_bgcolor = "white",
        paper_bgcolor= "white",
        bargap       = 0.28,
        yaxis = dict(
            dtick      = 50,
            range      = [0, y_max],
            showgrid   = True,
            gridcolor  = "#e5e7eb",
            gridwidth  = 1,
            zeroline   = False,
            tickfont   = dict(size=11),
        ),
        xaxis = dict(
            showgrid   = False,
            tickfont   = dict(size=11),
        ),
        legend = dict(
            orientation = "h",
            yanchor     = "bottom",
            y           = -0.22,
            xanchor     = "left",
            x           = 0,
            font        = dict(size=12),
            traceorder  = "reversed",   # SN em cima, NV embaixo — igual ao Excel
        ),
        margin = dict(l=20, r=20, t=20, b=70),
        hoverlabel = dict(bgcolor="white", font_size=13),
    )

    return fig, df_tabela


# ─── Render principal ─────────────────────────────────────────────────────────

def render_graficos(client_id: str = "", sharing_url: str = "") -> None:
    """Ponto de entrada da aba Gráficos — chamado pelo app.py."""

    st.markdown("""
    <div class="section-title">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none"
             stroke="#001e50" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="18" y1="20" x2="18" y2="10"/>
            <line x1="12" y1="20" x2="12" y2="4"/>
            <line x1="6"  y1="20" x2="6"  y2="14"/>
        </svg>
        <span>Gráficos F&amp;I</span>
    </div>
    """, unsafe_allow_html=True)

    # ── Pré-requisitos ────────────────────────────────────────────────────────
    if st.session_state.get("_msal_auth_status") != "authenticated":
        st.info("🔑 Faça login com sua conta Microsoft nas **Configurações** para visualizar os gráficos.")
        return
    if not sharing_url:
        st.info("⚙️ Configure o **Link do Excel — Dashboard** nas **Configurações**.")
        return

    # ── Carrega BIGBASE (cache compartilhado com aba Comissão) ────────────────
    with st.spinner("⏳ Carregando BIGBASE…"):
        df, err = load_bigbase(client_id, sharing_url)

    if err:
        st.error(err)
        col_r, _ = st.columns([1, 5])
        with col_r:
            if st.button("🔄 Tentar novamente", key="graf_retry"):
                st.session_state.pop("_comm_df_bigbase", None)
                st.session_state.pop("_comm_ts_bigbase", None)
                st.rerun()
        return

    if df is None or df.empty:
        st.warning("Nenhum dado encontrado na aba BIGBASE.")
        return

    # ── Barra de status ───────────────────────────────────────────────────────
    ts = st.session_state.get("_comm_ts_bigbase")
    col_info, col_btn = st.columns([8, 1])
    with col_info:
        st.caption(
            f"📊 BIGBASE · **{len(df):,}** registros"
            + (f" · atualizado às **{datetime.fromtimestamp(ts).strftime('%H:%M:%S')}**" if ts else "")
        )
    with col_btn:
        if st.button("🔄", key="graf_reload", help="Recarregar BIGBASE"):
            st.session_state.pop("_comm_df_bigbase", None)
            st.session_state.pop("_comm_ts_bigbase", None)
            st.rerun()

    # Aviso se tipo_veiculo não foi encontrado — provavelmente cache desatualizado
    if "tipo_veiculo" not in df.columns or df["tipo_veiculo"].isna().all():
        st.warning(
            "⚠️ Coluna **tipo_veiculo** não encontrada no BIGBASE carregado. "
            "Se você acabou de renomear a coluna no Excel, clique em **🔄** acima para recarregar."
        )

    st.divider()

    # ═════════════════════════════════════════════════════════════════════════
    # Gráfico 1 — Contratos NV vs SN
    # ═════════════════════════════════════════════════════════════════════════
    with st.container(border=True):
        st.markdown(
            "<p style='font-size:1rem;font-weight:600;color:#001e50;margin-bottom:4px'>"
            "Contratos por Tipo — Novos vs Seminovos</p>",
            unsafe_allow_html=True,
        )
        st.caption("Últimos 5 meses completos + mês vigente + Tendência (média móvel 3M)")

        fig1, df_tabela = _chart_contratos_nv_sn(df)
        st.plotly_chart(fig1, use_container_width=True)

        # Tabela resumo abaixo do gráfico (replica a legenda da planilha)
        st.dataframe(
            df_tabela,
            use_container_width=True,
            hide_index=True,
            column_config={
                "": st.column_config.TextColumn("", width="medium"),
            },
        )
