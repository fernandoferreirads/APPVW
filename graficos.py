"""
graficos.py — Gráficos Nativos F&I
Visualizações interativas construídas diretamente do BIGBASE via Plotly.

Cada gráfico replica fielmente os gráficos da planilha 'BIG DASHBOARD F&I',
com a vantagem de serem interativos, filtráveis e sem dependência de sessão Excel.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from comissao import load_bigbase

# ─── Persistência AAK ────────────────────────────────────────────────────────
_AAK_FILE = Path(__file__).parent / "credentials" / "aak_data.json"

# Valores históricos consolidados (base fixa — sobrescritos por entradas manuais)
_AAK_DEFAULTS: dict[str, int] = {
    "2025-10": 192,
    "2025-11": 186,
    "2025-12": 181,
    "2026-01": 207,
    "2026-02": 195,
    "2026-03": 231,
    "2026-04": 214,
}

# ─── Paleta fiel ao Excel ──────────────────────────────────────────────────────
_AZUL_NV    = "#4472C4"   # azul Excel (barras principais)
_LARANJA_SN = "#ED7D31"   # laranja Excel (SN / linha AAK / barra tendência)
_VW_BLUE    = "#001E50"

_MESES_PT = {
    1: "JANEIRO", 2: "FEVEREIRO", 3: "MARÇO",    4: "ABRIL",
    5: "MAIO",    6: "JUNHO",     7: "JULHO",     8: "AGOSTO",
    9: "SETEMBRO",10: "OUTUBRO",  11: "NOVEMBRO", 12: "DEZEMBRO",
}

# ─── Helpers de data ──────────────────────────────────────────────────────────

def _meses_range(n: int = 6) -> list[tuple[int, int, str]]:
    """n-1 meses completos + mês vigente, do mais antigo ao mais recente."""
    hoje = datetime.now()
    meses: list[tuple[int, int, str]] = []
    m, y = hoje.month, hoje.year
    for _ in range(n):
        meses.append((y, m, _MESES_PT[m]))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return list(reversed(meses))


def _meses_completos(n: int = 7) -> list[tuple[int, int, str]]:
    """Últimos n meses COMPLETOS (sem o mês vigente), do mais antigo ao mais recente."""
    hoje = datetime.now()
    meses: list[tuple[int, int, str]] = []
    m, y = hoje.month - 1, hoje.year
    if m == 0:
        m, y = 12, y - 1
    for _ in range(n):
        meses.append((y, m, _MESES_PT[m]))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return list(reversed(meses))


def _periodo_atual() -> pd.Period:
    return pd.Period(datetime.now(), "M")


def _str_df(df: pd.DataFrame) -> pd.DataFrame:
    """Força StringDtype em todas as colunas — impede pyarrow de inferir int64."""
    return df.astype(pd.StringDtype())


def _aak_load() -> dict[str, int]:
    """
    Carrega AAK: começa com _AAK_DEFAULTS (histórico fixo) e sobrepõe
    com os valores salvos em aak_data.json (entradas manuais do usuário).
    """
    data = dict(_AAK_DEFAULTS)
    try:
        if _AAK_FILE.exists():
            saved = {k: int(v) for k, v in json.loads(_AAK_FILE.read_text()).items()}
            data.update(saved)
    except Exception:
        pass
    return data


def _aak_save(data: dict[str, int]) -> None:
    """Salva {YYYY-MM: int} em credentials/aak_data.json."""
    _AAK_FILE.parent.mkdir(parents=True, exist_ok=True)
    _AAK_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def _fig_sem_dados(msg: str, height: int = 300) -> go.Figure:
    """Figura vazia com mensagem centralizada."""
    fig = go.Figure()
    fig.add_annotation(
        text=msg, xref="paper", yref="paper", x=0.5, y=0.5,
        showarrow=False, font=dict(size=13, color="#6b7280"),
    )
    fig.update_layout(
        template="plotly_white", height=height,
        xaxis=dict(visible=False), yaxis=dict(visible=False),
    )
    return fig


# ─── Gráfico 1 — Contratos NV vs SN por Mês ──────────────────────────────────

def _chart_contratos_nv_sn(df: pd.DataFrame) -> tuple[go.Figure, pd.DataFrame]:
    """Barras empilhadas: CONTRATOS NV (azul) vs CONTRATOS SN (laranja)."""
    meses = _meses_range(6)
    hoje  = _periodo_atual()

    if "tipo_veiculo" not in df.columns:
        return _fig_sem_dados(
            "Coluna tipo_veiculo não encontrada — clique em 🔄 para recarregar"
        ), pd.DataFrame()

    df_tipo = df[
        df["tipo_veiculo"].fillna("").str.strip().str.upper().isin(["N", "S"])
    ].copy()
    df_tipo["_periodo"] = df_tipo["data_pagto"].dt.to_period("M") \
        if "data_pagto" in df_tipo.columns else pd.NaT

    nv_vals: list[int] = []
    sn_vals: list[int] = []
    for (y, m, _) in meses:
        period = pd.Period(year=y, month=m, freq="M")
        sub    = df_tipo[df_tipo["_periodo"] == period]
        nv_vals.append(int((sub["tipo_veiculo"].str.upper() == "N").sum()))
        sn_vals.append(int((sub["tipo_veiculo"].str.upper() == "S").sum()))

    labels = [nome for (_, _, nome) in meses]

    # Tendência M.A — média dos 3 últimos meses completos
    idx_comp = [i for i, (y, m, _) in enumerate(meses)
                if pd.Period(year=y, month=m, freq="M") < hoje]
    if idx_comp:
        ult3  = idx_comp[-3:]
        ma_nv = round(sum(nv_vals[i] for i in ult3) / len(ult3))
        ma_sn = round(sum(sn_vals[i] for i in ult3) / len(ult3))
    else:
        ma_nv = ma_sn = 0

    labels.append("TENDÊNCIA M.A")
    nv_vals.append(ma_nv)
    sn_vals.append(ma_sn)

    df_tabela = _str_df(pd.DataFrame({
        "": ["CONTRATOS SN", "CONTRATOS NV"],
        **{labels[i]: [str(sn_vals[i]), str(nv_vals[i])] for i in range(len(labels))},
    }))

    total_vals = [nv + sn for nv, sn in zip(nv_vals, sn_vals)]
    y_max      = max(max(total_vals, default=0) * 1.18, 300)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="CONTRATOS NV", x=labels, y=nv_vals,
        marker_color=_AZUL_NV,
        text=[str(v) if v > 0 else "" for v in nv_vals],
        textposition="inside", insidetextanchor="middle",
        textfont=dict(color="white", size=12),
        hovertemplate="<b>%{x}</b><br>NV: %{y}<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        name="CONTRATOS SN", x=labels, y=sn_vals,
        marker_color=_LARANJA_SN,
        text=[str(v) if v > 0 else "" for v in sn_vals],
        textposition="inside", insidetextanchor="middle",
        textfont=dict(color="white", size=12),
        hovertemplate="<b>%{x}</b><br>SN: %{y}<extra></extra>",
    ))
    fig.update_layout(
        barmode="stack", template="plotly_white", height=440,
        plot_bgcolor="white", paper_bgcolor="white", bargap=0.28,
        yaxis=dict(dtick=50, range=[0, y_max], showgrid=True,
                   gridcolor="#e5e7eb", zeroline=False),
        xaxis=dict(showgrid=False, tickfont=dict(size=11)),
        legend=dict(orientation="h", yanchor="bottom", y=-0.22,
                    xanchor="left", x=0, font=dict(size=12),
                    traceorder="reversed"),
        margin=dict(l=20, r=20, t=20, b=70),
        hoverlabel=dict(bgcolor="white", font_size=13),
    )
    return fig, df_tabela


# ─── Gráfico 7 — Contratos + AAK ─────────────────────────────────────────────

# Número de meses exibidos no gráfico (completos + mês vigente)
_AAK_N_MESES = 9   # 8 completos + mês atual → abrange ~out/25 – jun/26

def _chart_contratos_aak(
    df: pd.DataFrame,
    aak_manual: dict[str, int] | None = None,
) -> tuple[go.Figure, pd.DataFrame]:
    """
    Barra azul  : CONTRATOS TT (eixo esq.)
    Linha laranja: AAK por mês  (eixo esq., mesmo range das barras)
    Linha verde  : PENETRATION = NV / AAK × 100 (eixo dir., %)
    Tendência M.A: barra laranja + pontos para as linhas.
    aak_manual  : {YYYY-MM: int} carregado de credentials/aak_data.json.
    """
    meses = _meses_range(_AAK_N_MESES)
    hoje  = _periodo_atual()

    if "tipo_veiculo" not in df.columns or "data_pagto" not in df.columns:
        return _fig_sem_dados(
            "Colunas necessárias não encontradas no BIGBASE"
        ), pd.DataFrame()

    df_w = df.copy()
    df_w["_periodo"] = df_w["data_pagto"].dt.to_period("M")

    nv_vals:  list[int] = []
    tt_vals:  list[int] = []
    aak_vals: list[int] = []

    for (y, m, _) in meses:
        period     = pd.Period(year=y, month=m, freq="M")
        period_str = f"{y:04d}-{m:02d}"
        sub        = df_w[df_w["_periodo"] == period]
        tv         = sub["tipo_veiculo"].fillna("").str.strip().str.upper()

        nv_vals.append(int((tv == "N").sum()))
        tt_vals.append(len(sub))

        if aak_manual and period_str in aak_manual:
            aak_vals.append(int(aak_manual[period_str]))
        else:
            aak_vals.append(0)   # sem valor manual → zero (sinaliza dado faltante)

    labels = [nome for (_, _, nome) in meses]

    # ── Tendência M.A — média dos 3 últimos meses COMPLETOS ──────────────────
    idx_comp = [i for i, (y, m, _) in enumerate(meses)
                if pd.Period(year=y, month=m, freq="M") < hoje]
    if idx_comp:
        ult3   = idx_comp[-3:]
        ma_tt  = round(sum(tt_vals[i]  for i in ult3) / len(ult3))
        ma_nv  = round(sum(nv_vals[i]  for i in ult3) / len(ult3))
        ma_aak = round(sum(aak_vals[i] for i in ult3) / len(ult3))
    else:
        ma_tt = ma_nv = ma_aak = 0

    labels.append("TENDÊNCIA\nM.A")
    tt_vals.append(ma_tt)
    nv_vals.append(ma_nv)
    aak_vals.append(ma_aak)

    label_tabela = [lbl.replace("\n", " ") for lbl in labels]

    # PENETRATION = NV / AAK × 100
    penet: list[float] = [
        round(nv / aak * 100, 1) if aak > 0 else 0.0
        for nv, aak in zip(nv_vals, aak_vals)
    ]

    df_tabela = _str_df(pd.DataFrame({
        "": ["CONTRATOS TT", "AAK", "PENETRATION"],
        **{label_tabela[i]: [
            str(tt_vals[i]),
            str(aak_vals[i]),
            f"{penet[i]:.0f}%",
        ] for i in range(len(label_tabela))},
    }))

    # ── Escalas ──────────────────────────────────────────────────────────────
    y_max = max(
        max(tt_vals,  default=0),
        max(aak_vals, default=0),
    ) * 1.30
    y_max = max(y_max, 300)

    penet_max = max(max(penet, default=0) * 1.30, 130)

    # ── Cores: tendência = laranja, resto = azul ──────────────────────────────
    bar_colors = [_AZUL_NV] * (len(labels) - 1) + [_LARANJA_SN]

    fig = go.Figure()

    # Barras CONTRATOS TT
    fig.add_trace(go.Bar(
        name="CONTRATOS TT", x=labels, y=tt_vals, yaxis="y",
        marker_color=bar_colors,
        text=[str(v) if v > 0 else "" for v in tt_vals],
        textposition="outside",
        textfont=dict(size=10, color="#222"),
        hovertemplate="<b>%{x}</b><br>TT: %{y}<extra></extra>",
    ))

    # Linha AAK (eixo esquerdo — mesma escala das barras)
    fig.add_trace(go.Scatter(
        name="AAK", x=labels, y=aak_vals, yaxis="y",
        mode="lines+markers+text",
        line=dict(color=_LARANJA_SN, width=2.5),
        marker=dict(size=6, color=_LARANJA_SN),
        text=[str(v) if v > 0 else "" for v in aak_vals],
        textposition="top center",
        textfont=dict(size=9, color=_LARANJA_SN),
        hovertemplate="<b>%{x}</b><br>AAK: %{y}<extra></extra>",
    ))

    # Linha PENETRATION (eixo direito, %)
    fig.add_trace(go.Scatter(
        name="PENETRATION", x=labels, y=penet, yaxis="y2",
        mode="lines+markers+text",
        line=dict(color="#70AD47", width=2.5, dash="dash"),
        marker=dict(size=6, color="#70AD47"),
        text=[f"{v:.0f}%" if v > 0 else "" for v in penet],
        textposition="top center",
        textfont=dict(size=9, color="#70AD47"),
        hovertemplate="<b>%{x}</b><br>Penetration: %{y:.1f}%<extra></extra>",
    ))

    fig.update_layout(
        barmode       = "group",
        template      = "plotly_white",
        height        = 460,
        plot_bgcolor  = "white",
        paper_bgcolor = "white",
        bargap        = 0.32,
        yaxis  = dict(range=[0, y_max], showgrid=True, gridcolor="#e5e7eb",
                      zeroline=False, tickfont=dict(size=11)),
        yaxis2 = dict(overlaying="y", side="right",
                      range=[0, penet_max],
                      ticksuffix="%",
                      showgrid=False, zeroline=False, tickfont=dict(size=11)),
        xaxis  = dict(showgrid=False, tickfont=dict(size=10)),
        legend = dict(orientation="h", yanchor="bottom", y=-0.25,
                      xanchor="left", x=0, font=dict(size=12)),
        margin     = dict(l=20, r=60, t=30, b=80),
        hoverlabel = dict(bgcolor="white", font_size=13),
    )

    return fig, df_tabela


# ─── Helper genérico — Qtd + % AAK (reutilizado por GE, SPF, etc.) ──────────

def _chart_produto(
    df: pd.DataFrame,
    col: str,
    titulo: str,
    filtro: str | None = None,
    y_min_floor: int = 50,
) -> tuple[go.Figure, pd.DataFrame]:
    """
    Barras azuis (Qtd, eixo esq.) + linha laranja (% AAK, eixo dir.).
    % AAK = Qtd produto / total contratos do mês × 100.
    TENDÊNCIA M.A = barra laranja (média 3 meses completos).

    filtro: se informado, conta apenas as linhas cujo valor da coluna
            seja igual a esse texto (case-insensitive). Ex.: "SEGURO VW".
            Se None, conta qualquer valor não-vazio.
    """
    meses = _meses_completos(7)

    if col not in df.columns or "data_pagto" not in df.columns:
        return _fig_sem_dados(
            f"Coluna '{col}' ou 'data_pagto' não encontrada no BIGBASE"
        ), pd.DataFrame()

    df_w = df.copy()
    df_w["_periodo"] = df_w["data_pagto"].dt.to_period("M")

    qtd:      list[int]   = []
    total_ct: list[int]   = []

    for (y, m, _) in meses:
        period = pd.Period(year=y, month=m, freq="M")
        sub    = df_w[df_w["_periodo"] == period]
        vals   = sub[col].fillna("").astype(str).str.strip()
        if filtro:
            ok = vals[vals.str.contains(filtro, case=False, na=False, regex=False)]
        else:
            ok = vals[~vals.isin(["", "nan", "None"])]
        qtd.append(len(ok))
        total_ct.append(len(sub))

    pct_aak: list[float] = [
        round(q / t * 100, 1) if t > 0 else 0.0
        for q, t in zip(qtd, total_ct)
    ]

    labels = [nome for (_, _, nome) in meses]

    if len(qtd) >= 3:
        ma_qtd = round(sum(qtd[-3:])    / 3)
        ma_pct = round(sum(pct_aak[-3:]) / 3, 1)
    elif qtd:
        ma_qtd, ma_pct = qtd[-1], pct_aak[-1]
    else:
        ma_qtd = ma_pct = 0

    labels.append("TENDÊNCIA\nM.A")
    label_tabela = [lbl.replace("\n", " ") for lbl in labels]
    qtd.append(ma_qtd)
    pct_aak.append(ma_pct)

    bar_colors = [_AZUL_NV] * (len(labels) - 1) + [_LARANJA_SN]

    df_tabela = _str_df(pd.DataFrame({
        "": ["Qtd", "% AAK"],
        **{label_tabela[i]: [str(qtd[i]), f"{pct_aak[i]:.0f}%"]
           for i in range(len(label_tabela))},
    }))

    y_max_qtd = max(max(qtd, default=0) * 1.20, y_min_floor)
    y_max_pct = max(max(pct_aak, default=0) * 1.20, 140)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name         = "Qtd",
        x            = labels,
        y            = qtd,
        marker_color = bar_colors,
        yaxis        = "y",
        text         = ["" if i < len(labels) - 1 else str(ma_qtd)
                        for i in range(len(labels))],
        textposition = "outside",
        textfont     = dict(size=12, color=_LARANJA_SN, family="Inter, sans-serif"),
        hovertemplate= "<b>%{x}</b><br>Qtd: %{y}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        name         = "% AAK",
        x            = labels,
        y            = pct_aak,
        mode         = "lines+markers",
        yaxis        = "y2",
        line         = dict(color=_LARANJA_SN, width=2.5),
        marker       = dict(size=6, color=_LARANJA_SN, symbol="circle"),
        hovertemplate= "<b>%{x}</b><br>% AAK: %{y:.1f}%<extra></extra>",
    ))
    fig.update_layout(
        template      = "plotly_white",
        height        = 440,
        plot_bgcolor  = "white",
        paper_bgcolor = "white",
        bargap        = 0.28,
        yaxis  = dict(title="", side="left",  dtick=20, range=[0, y_max_qtd],
                      showgrid=True, gridcolor="#e5e7eb", zeroline=False,
                      tickfont=dict(size=11)),
        yaxis2 = dict(title="", side="right", overlaying="y",
                      range=[0, y_max_pct], dtick=20,
                      ticksuffix="%", showgrid=False, zeroline=False,
                      tickfont=dict(size=11)),
        xaxis  = dict(showgrid=False, tickfont=dict(size=11)),
        legend = dict(orientation="h", yanchor="bottom", y=-0.22,
                      xanchor="left", x=0, font=dict(size=12)),
        margin     = dict(l=20, r=50, t=20, b=70),
        hoverlabel = dict(bgcolor="white", font_size=13),
    )
    return fig, df_tabela


# ─── Gráfico 2 — Garantias (Qtd + % AAK) ────────────────────────────────────

def _chart_garantias(df: pd.DataFrame) -> tuple[go.Figure, pd.DataFrame]:
    """GE produzidas — delega ao helper genérico."""
    return _chart_produto(df, col="ge", titulo="GARANTIAS")


# ─── Gráfico 3 — Seguros (Qtd + % AAK) ──────────────────────────────────────

def _chart_seguros(df: pd.DataFrame) -> tuple[go.Figure, pd.DataFrame]:
    """Seguros VW — coluna N (app, pos. 13), filtra apenas 'SEGURO VW'."""
    return _chart_produto(df, col="app", titulo="SEGUROS", filtro="SEGURO VW", y_min_floor=200)


# ─── Gráfico 4 — Protege (Qtd + % AAK) ──────────────────────────────────────

def _chart_protege(df: pd.DataFrame) -> tuple[go.Figure, pd.DataFrame]:
    """VW Protege — coluna S (protege, pos. 18)."""
    return _chart_produto(df, col="protege", titulo="PROTEGE", y_min_floor=50)


# ─── Gráfico 6 — Total Pontos ────────────────────────────────────────────────

def _chart_pontos(df: pd.DataFrame) -> tuple[go.Figure, pd.DataFrame]:
    """
    Total de Pontos por mês — SOMA da coluna 'pontos' (valores decimais).
    Barras azuis por mês + barra laranja TENDÊNCIA M.A.
    Sem linha % AAK — gráfico de barras simples.
    """
    meses = _meses_completos(7)

    if "pontos" not in df.columns or "data_pagto" not in df.columns:
        return _fig_sem_dados(
            "Coluna 'pontos' ou 'data_pagto' não encontrada no BIGBASE"
        ), pd.DataFrame()

    df_w = df.copy()
    df_w["_periodo"]    = df_w["data_pagto"].dt.to_period("M")
    df_w["_pontos_num"] = pd.to_numeric(df_w["pontos"], errors="coerce").fillna(0.0)

    totais: list[float] = []

    for (y, m, _) in meses:
        period = pd.Period(year=y, month=m, freq="M")
        sub    = df_w[df_w["_periodo"] == period]
        totais.append(round(float(sub["_pontos_num"].sum()), 2))

    labels = [nome for (_, _, nome) in meses]

    # Tendência M.A — média dos últimos 3 meses completos
    if len(totais) >= 3:
        ma = round(sum(totais[-3:]) / 3, 2)
    elif totais:
        ma = totais[-1]
    else:
        ma = 0.0

    labels.append("TENDÊNCIA\nM.A")
    label_tabela = [lbl.replace("\n", " ") for lbl in labels]
    totais.append(ma)

    bar_colors = [_AZUL_NV] * (len(labels) - 1) + [_LARANJA_SN]

    # Formata com vírgula decimal (padrão brasileiro)
    def _fmt(v: float) -> str:
        return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    df_tabela = _str_df(pd.DataFrame({
        "": ["Pontos"],
        **{label_tabela[i]: [_fmt(totais[i])] for i in range(len(label_tabela))},
    }))

    y_max = max(max(totais, default=0) * 1.18, 500)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name         = "Pontos",
        x            = labels,
        y            = totais,
        marker_color = bar_colors,
        text         = [_fmt(v) for v in totais],
        textposition = "outside",
        textfont     = dict(size=11, color="#1a1a2e"),
        hovertemplate= "<b>%{x}</b><br>Pontos: %{text}<extra></extra>",
    ))

    fig.update_layout(
        template      = "plotly_white",
        height        = 440,
        plot_bgcolor  = "white",
        paper_bgcolor = "white",
        bargap        = 0.28,
        yaxis  = dict(dtick=50, range=[0, y_max], showgrid=True,
                      gridcolor="#e5e7eb", zeroline=False, tickfont=dict(size=11)),
        xaxis  = dict(showgrid=False, tickfont=dict(size=11)),
        legend = dict(orientation="h", yanchor="bottom", y=-0.22,
                      xanchor="left", x=0, font=dict(size=12)),
        margin     = dict(l=20, r=20, t=20, b=70),
        hoverlabel = dict(bgcolor="white", font_size=13),
    )

    return fig, df_tabela


# ─── Gráfico 8 — Pontos por Contrato ────────────────────────────────────────

_META_PPC = 1.5   # meta fixa pontos por contrato

def _chart_pontos_por_contrato(df: pd.DataFrame) -> tuple[go.Figure, pd.DataFrame]:
    """
    PONTOS POR CONTRATO = sum(pontos) / (NV + SN) por mês.
    Barras azuis (MÉDIA) + barra laranja (TENDÊNCIA M.A) + linha laranja (META = 1.5).
    """
    meses = _meses_completos(7)

    cols_req = {"pontos", "tipo_veiculo", "data_pagto"}
    if not cols_req.issubset(df.columns):
        return _fig_sem_dados(
            "Colunas necessárias (pontos, tipo_veiculo, data_pagto) não encontradas"
        ), pd.DataFrame()

    df_w = df.copy()
    df_w["_periodo"]    = df_w["data_pagto"].dt.to_period("M")
    df_w["_pontos_num"] = pd.to_numeric(df_w["pontos"], errors="coerce").fillna(0.0)

    medias: list[float] = []

    for (y, m, _) in meses:
        period = pd.Period(year=y, month=m, freq="M")
        sub    = df_w[df_w["_periodo"] == period]
        total_pontos = float(sub["_pontos_num"].sum())
        tv = sub["tipo_veiculo"].astype(str).str.upper()
        tt = len(tv[tv.str.startswith("N", na=False)]) + len(tv[tv.str.startswith("S", na=False)])
        medias.append(round(total_pontos / tt, 2) if tt > 0 else 0.0)

    labels = [nome for (_, _, nome) in meses]

    # Tendência M.A — média dos últimos 3 meses completos
    tend = round(sum(medias[-3:]) / 3, 2) if len(medias) >= 3 else (medias[-1] if medias else 0.0)

    labels.append("TENDÊNCIA\nM.A")
    label_tabela = [lbl.replace("\n", " ") for lbl in labels]
    medias.append(tend)

    bar_colors = [_AZUL_NV] * (len(labels) - 1) + [_LARANJA_SN]
    y_max = max(max(medias, default=0) * 1.18, _META_PPC * 1.5)

    fig = go.Figure()

    # Barras MÉDIA
    fig.add_trace(go.Bar(
        name          = "MÉDIA",
        x             = labels,
        y             = medias,
        marker_color  = bar_colors,
        text          = [f"{v:.2f}" for v in medias],
        textposition  = "outside",
        textfont      = dict(size=11, color="#1a1a2e"),
        hovertemplate = "<b>%{x}</b><br>Pontos/Contrato: %{text}<extra></extra>",
    ))

    # Linha horizontal META
    fig.add_trace(go.Scatter(
        name          = "META",
        x             = labels,
        y             = [_META_PPC] * len(labels),
        mode          = "lines",
        line          = dict(color=_LARANJA_SN, width=2.5),
        hovertemplate = "META: %{y:.1f}<extra></extra>",
    ))

    fig.update_layout(
        template      = "plotly_white",
        height        = 440,
        plot_bgcolor  = "white",
        paper_bgcolor = "white",
        bargap        = 0.28,
        yaxis = dict(
            dtick      = 0.20,
            range      = [0, y_max],
            showgrid   = True,
            gridcolor  = "#e5e7eb",
            zeroline   = False,
            tickformat = ".2f",
            tickfont   = dict(size=11),
        ),
        xaxis  = dict(showgrid=False, tickfont=dict(size=11)),
        legend = dict(orientation="h", yanchor="bottom", y=-0.22,
                      xanchor="left", x=0, font=dict(size=12)),
        margin     = dict(l=20, r=20, t=20, b=70),
        hoverlabel = dict(bgcolor="white", font_size=13),
    )

    df_tabela = _str_df(pd.DataFrame({
        "": ["MÉDIA", "META"],
        **{label_tabela[i]: [
            f"{medias[i]:.2f}",
            f"{_META_PPC:.1f}",
        ] for i in range(len(label_tabela))},
    }))

    return fig, df_tabela


# ─── Gráfico 4 — SPF (barras agrupadas Total vs Plus) ────────────────────────

def _chart_spf(df: pd.DataFrame) -> tuple[go.Figure, pd.DataFrame]:
    """
    Barras agrupadas: Total SPF (azul) vs SPF Plus (laranja).
    Coluna M (spf, pos. 12).
    Total SPF = qualquer valor não-vazio; SPF Plus = contém 'PLUS'.
    Tabela com 4 linhas: Total Spfs, Spf Plus, % AAK, Aak Plus.
    """
    meses = _meses_completos(7)

    if "spf" not in df.columns or "data_pagto" not in df.columns:
        return _fig_sem_dados(
            "Coluna 'spf' ou 'data_pagto' não encontrada no BIGBASE"
        ), pd.DataFrame()

    df_w = df.copy()
    df_w["_periodo"] = df_w["data_pagto"].dt.to_period("M")

    total_spf: list[int] = []
    spf_plus:  list[int] = []
    total_ct:  list[int] = []

    for (y, m, _) in meses:
        period = pd.Period(year=y, month=m, freq="M")
        sub    = df_w[df_w["_periodo"] == period]
        vals   = sub["spf"].fillna("").astype(str).str.strip()

        nao_vazio = vals[~vals.isin(["", "nan", "None"])]
        total_spf.append(len(nao_vazio))

        plus = vals[vals.str.contains("PLUS", case=False, na=False, regex=False)]
        spf_plus.append(len(plus))

        total_ct.append(len(sub))

    pct_aak  = [round(q / t * 100, 1) if t > 0 else 0.0
                for q, t in zip(total_spf, total_ct)]
    pct_plus = [round(q / t * 100, 1) if t > 0 else 0.0
                for q, t in zip(spf_plus,  total_ct)]

    labels = [nome for (_, _, nome) in meses]

    # Tendência M.A (média 3 meses completos)
    if len(total_spf) >= 3:
        ma_total = round(sum(total_spf[-3:]) / 3)
        ma_plus  = round(sum(spf_plus[-3:])  / 3)
        ma_pct   = round(sum(pct_aak[-3:])   / 3, 1)
        ma_pct_p = round(sum(pct_plus[-3:])  / 3, 1)
    elif total_spf:
        ma_total, ma_plus   = total_spf[-1], spf_plus[-1]
        ma_pct,   ma_pct_p  = pct_aak[-1],  pct_plus[-1]
    else:
        ma_total = ma_plus = ma_pct = ma_pct_p = 0

    labels.append("TENDÊNCIA\nM.A")
    label_tabela = [lbl.replace("\n", " ") for lbl in labels]
    total_spf.append(ma_total)
    spf_plus.append(ma_plus)
    pct_aak.append(ma_pct)
    pct_plus.append(ma_pct_p)

    df_tabela = _str_df(pd.DataFrame({
        "": ["Total Spfs", "Spf Plus", "% AAK", "Aak Plus"],
        **{label_tabela[i]: [
            str(total_spf[i]),
            str(spf_plus[i]),
            f"{pct_aak[i]:.0f}%",
            f"{pct_plus[i]:.0f}%",
        ] for i in range(len(label_tabela))},
    }))

    y_max = max(max(total_spf, default=0) * 1.35, 100)

    fig = go.Figure()

    fig.add_trace(go.Bar(
        name         = "Total Spfs",
        x            = labels,
        y            = total_spf,
        marker_color = _AZUL_NV,
        text         = [str(v) if v > 0 else "" for v in total_spf],
        textposition = "outside",
        textfont     = dict(size=11, color="#1a1a2e"),
        hovertemplate= "<b>%{x}</b><br>Total Spfs: %{y}<extra></extra>",
    ))

    fig.add_trace(go.Bar(
        name         = "Spf Plus",
        x            = labels,
        y            = spf_plus,
        marker_color = _LARANJA_SN,
        text         = [str(v) if v > 0 else "" for v in spf_plus],
        textposition = "outside",
        textfont     = dict(size=11, color="#1a1a2e"),
        hovertemplate= "<b>%{x}</b><br>Spf Plus: %{y}<extra></extra>",
    ))

    fig.update_layout(
        barmode       = "group",
        template      = "plotly_white",
        height        = 440,
        plot_bgcolor  = "white",
        paper_bgcolor = "white",
        bargap        = 0.25,
        bargroupgap   = 0.05,
        yaxis  = dict(range=[0, y_max], showgrid=True, gridcolor="#e5e7eb",
                      zeroline=False, tickfont=dict(size=11)),
        xaxis  = dict(showgrid=False, tickfont=dict(size=11)),
        legend = dict(orientation="h", yanchor="bottom", y=-0.22,
                      xanchor="left", x=0, font=dict(size=12)),
        margin     = dict(l=20, r=20, t=20, b=70),
        hoverlabel = dict(bgcolor="white", font_size=13),
    )

    return fig, df_tabela


# ─── Exportação PDF ───────────────────────────────────────────────────────────

def _gerar_pdf(df: pd.DataFrame, aak_manual: dict) -> bytes:
    """
    Gera um PDF landscape A4 com os 7 gráficos F&I.
    Requer: kaleido (renderiza imagens) + reportlab (monta o PDF).
    """
    import io as _io

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        Image as RLImage,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    PAGE = landscape(A4)          # 841.9 × 595.3 pt
    LM = RM = 1.4 * cm
    TM = BM = 1.6 * cm
    CW = PAGE[0] - LM - RM        # largura do conteúdo ≈ 792 pt

    buf = _io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=PAGE,
        leftMargin=LM, rightMargin=RM,
        topMargin=TM, bottomMargin=BM,
    )

    styles  = getSampleStyleSheet()
    h_style = ParagraphStyle(
        "TituloGraf",
        parent=styles["Heading2"],
        fontSize=12,
        textColor=colors.HexColor("#001e50"),
        spaceBefore=0,
        spaceAfter=4,
    )

    # ── Configura kaleido para ambientes containerizados (Streamlit Cloud) ───
    # kaleido 0.2.1 embute o Chromium mas precisa de --no-sandbox em Docker/Linux
    try:
        import plotly.io as _pio
        _pio.kaleido.scope.chromium_args = (
            "--disable-gpu",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-software-rasterizer",
        )
    except Exception:
        pass

    # ── Coleta todas as figuras ───────────────────────────────────────────────
    graficos = [
        ("CONTRATOS NV vs SN", _chart_contratos_nv_sn(df)),
        ("GARANTIAS",          _chart_garantias(df)),
        ("SEGUROS",            _chart_seguros(df)),
        ("SPF",                _chart_spf(df)),
        ("PROTEGE",            _chart_protege(df)),
        ("TOTAL PONTOS",          _chart_pontos(df)),
        ("PONTOS POR CONTRATO",   _chart_pontos_por_contrato(df)),
        ("CONTRATOS E AAK",       _chart_contratos_aak(df, aak_manual=aak_manual or {})),
    ]

    story = []

    # ── Capa ──────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 4.5 * cm))
    story.append(Paragraph(
        "Graficos F&amp;I - Banco Volkswagen CCB",
        ParagraphStyle(
            "Capa", parent=styles["Title"],
            fontSize=22, textColor=colors.HexColor("#001e50"), alignment=1,
        ),
    ))
    story.append(Spacer(1, 0.6 * cm))
    story.append(Paragraph(
        f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        ParagraphStyle(
            "DataCapa", parent=styles["Normal"],
            fontSize=11, textColor=colors.grey, alignment=1,
        ),
    ))
    story.append(PageBreak())

    IMG_H = CW * 420 / 1200   # altura mantendo aspect-ratio 1200×420

    for titulo, (fig, tbl) in graficos:
        story.append(Paragraph(titulo, h_style))

        # Renderiza o gráfico como PNG via kaleido
        try:
            img_bytes = fig.to_image(format="png", width=1200, height=420, scale=2)
            story.append(RLImage(_io.BytesIO(img_bytes), width=CW, height=IMG_H))
        except Exception as _img_e:
            story.append(
                Paragraph(f"[imagem indisponivel: {_img_e}]", styles["Normal"])
            )

        story.append(Spacer(1, 0.2 * cm))

        # Tabela de dados abaixo do gráfico
        if not tbl.empty:
            cols = list(tbl.columns)
            rows = []
            for row in tbl.itertuples(index=False, name=None):
                rows.append([
                    "" if str(v) in ("<NA>", "nan", "None") else str(v)
                    for v in row
                ])

            n      = len(cols)
            first  = 2.6 * cm
            rest   = (CW - first) / (n - 1) if n > 1 else CW
            col_ws = [first] + [rest] * (n - 1)

            t_rl = Table([cols] + rows, colWidths=col_ws, repeatRows=1)
            ts_rl = TableStyle([
                ("BACKGROUND",    (0, 0), (-1, 0),  colors.HexColor("#001e50")),
                ("TEXTCOLOR",     (0, 0), (-1, 0),  colors.white),
                ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
                ("FONTSIZE",      (0, 0), (-1, -1), 7),
                ("ALIGN",         (1, 0), (-1, -1), "CENTER"),
                ("ALIGN",         (0, 0), (0, -1),  "LEFT"),
                ("GRID",          (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
                ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING",    (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ])
            for i in range(1, len(rows) + 1):
                bg = colors.white if i % 2 == 1 else colors.HexColor("#f3f4f6")
                ts_rl.add("BACKGROUND", (0, i), (-1, i), bg)
            t_rl.setStyle(ts_rl)
            story.append(t_rl)

        story.append(PageBreak())

    doc.build(story)
    return buf.getvalue()


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
        st.info("🔑 Faça login com sua conta Microsoft nas **Configurações**.")
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
            st.session_state.pop("_pdf_bytes", None)   # invalida PDF em cache
            st.rerun()

    if "tipo_veiculo" not in df.columns or df["tipo_veiculo"].isna().all():
        st.warning(
            "⚠️ Coluna **tipo_veiculo** não encontrada no BIGBASE carregado. "
            "Se você renomeou a coluna no Excel, clique em **🔄** para recarregar."
        )

    st.divider()

    # ── Exportar todos os gráficos em PDF ─────────────────────────────────────
    _pdf_col1, _pdf_col2, _ = st.columns([1.3, 1.5, 7])
    with _pdf_col1:
        if st.button("📄 Gerar PDF", key="btn_gerar_pdf", use_container_width=True):
            with st.spinner("Gerando PDF... aguarde"):
                try:
                    st.session_state["_pdf_bytes"] = _gerar_pdf(df, _aak_load())
                except Exception as _e_pdf:
                    st.error(f"❌ Erro ao gerar PDF: {_e_pdf}")
                    import traceback as _tb_pdf
                    st.code(_tb_pdf.format_exc(), language="python")
    with _pdf_col2:
        if st.session_state.get("_pdf_bytes"):
            st.download_button(
                "📥 Baixar PDF",
                data=st.session_state["_pdf_bytes"],
                file_name=f"graficos_fi_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                mime="application/pdf",
                key="btn_dl_pdf",
                use_container_width=True,
            )

    st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)

    # ═══════════════════════════════════════════════════════════════════════════
    # Gráfico 1 — Contratos NV vs SN
    # ═══════════════════════════════════════════════════════════════════════════
    with st.container(border=True):
        st.markdown(
            "<p style='font-size:1rem;font-weight:700;color:#001e50;"
            "text-align:center;margin-bottom:2px'>CONTRATOS</p>",
            unsafe_allow_html=True,
        )
        st.caption("Últimos 5 meses completos + mês vigente + Tendência M.A (média 3M)")

        fig1, tbl1 = _chart_contratos_nv_sn(df)
        st.plotly_chart(fig1, use_container_width=True)
        if not tbl1.empty:
            st.dataframe(tbl1, use_container_width=True, hide_index=True,
                         column_config={"": st.column_config.TextColumn("", width="medium")})

    st.markdown("<div style='height:1.5rem'></div>", unsafe_allow_html=True)

    # ═══════════════════════════════════════════════════════════════════════════
    # Gráfico 2 — Garantias (Qtd + % AAK)
    # ═══════════════════════════════════════════════════════════════════════════
    try:
        with st.container(border=True):
            st.markdown(
                "<p style='font-size:1rem;font-weight:700;color:#001e50;"
                "text-align:center;margin-bottom:2px'>GARANTIAS</p>",
                unsafe_allow_html=True,
            )
            st.caption("Qtd de GE produzidas (barras, eixo esq.) · % AAK = GE / total contratos (linha, eixo dir.)")

            fig2, tbl2 = _chart_garantias(df)
            st.plotly_chart(fig2, use_container_width=True)
            if not tbl2.empty:
                st.dataframe(tbl2, use_container_width=True, hide_index=True,
                             column_config={"": st.column_config.TextColumn("", width="medium")})
    except Exception as _e_gar:
        st.error(f"❌ Erro ao renderizar GARANTIAS: {_e_gar}")
        import traceback
        st.code(traceback.format_exc(), language="python")

    st.markdown("<div style='height:1.5rem'></div>", unsafe_allow_html=True)

    # ═══════════════════════════════════════════════════════════════════════════
    # Gráfico 3 — Seguros (Qtd + % AAK)
    # ═══════════════════════════════════════════════════════════════════════════
    try:
        with st.container(border=True):
            st.markdown(
                "<p style='font-size:1rem;font-weight:700;color:#001e50;"
                "text-align:center;margin-bottom:2px'>SEGUROS</p>",
                unsafe_allow_html=True,
            )
            st.caption("Qtd de Seguro VW produzidos (barras, eixo esq.) · % AAK = Seguro VW / total contratos (linha, eixo dir.)")

            fig3, tbl3 = _chart_seguros(df)
            st.plotly_chart(fig3, use_container_width=True)
            if not tbl3.empty:
                st.dataframe(tbl3, use_container_width=True, hide_index=True,
                             column_config={"": st.column_config.TextColumn("", width="medium")})
    except Exception as _e_seg:
        st.error(f"❌ Erro ao renderizar SEGUROS: {_e_seg}")
        import traceback
        st.code(traceback.format_exc(), language="python")

    st.markdown("<div style='height:1.5rem'></div>", unsafe_allow_html=True)

    # ═══════════════════════════════════════════════════════════════════════════
    # Gráfico 4 — SPF (barras agrupadas Total vs Plus)
    # ═══════════════════════════════════════════════════════════════════════════
    try:
        with st.container(border=True):
            st.markdown(
                "<p style='font-size:1rem;font-weight:700;color:#001e50;"
                "text-align:center;margin-bottom:2px'>SPF</p>",
                unsafe_allow_html=True,
            )
            st.caption("Total SPF (azul) vs SPF Plus (laranja) · % AAK = Qtd / total contratos")

            fig4, tbl4 = _chart_spf(df)
            st.plotly_chart(fig4, use_container_width=True)
            if not tbl4.empty:
                st.dataframe(tbl4, use_container_width=True, hide_index=True,
                             column_config={"": st.column_config.TextColumn("", width="medium")})
    except Exception as _e_spf:
        st.error(f"❌ Erro ao renderizar SPF: {_e_spf}")
        import traceback
        st.code(traceback.format_exc(), language="python")

    st.markdown("<div style='height:1.5rem'></div>", unsafe_allow_html=True)

    # ═══════════════════════════════════════════════════════════════════════════
    # Gráfico 5 — Protege (Qtd + % AAK)
    # ═══════════════════════════════════════════════════════════════════════════
    try:
        with st.container(border=True):
            st.markdown(
                "<p style='font-size:1rem;font-weight:700;color:#001e50;"
                "text-align:center;margin-bottom:2px'>PROTEGE</p>",
                unsafe_allow_html=True,
            )
            st.caption("Qtd de VW Protege produzidos (barras, eixo esq.) · % AAK = Protege / total contratos (linha, eixo dir.)")

            fig5, tbl5 = _chart_protege(df)
            st.plotly_chart(fig5, use_container_width=True)
            if not tbl5.empty:
                st.dataframe(tbl5, use_container_width=True, hide_index=True,
                             column_config={"": st.column_config.TextColumn("", width="medium")})
    except Exception as _e_pro:
        st.error(f"❌ Erro ao renderizar PROTEGE: {_e_pro}")
        import traceback
        st.code(traceback.format_exc(), language="python")

    st.markdown("<div style='height:1.5rem'></div>", unsafe_allow_html=True)

    # ═══════════════════════════════════════════════════════════════════════════
    # Gráfico 6 — Total Pontos
    # ═══════════════════════════════════════════════════════════════════════════
    try:
        with st.container(border=True):
            st.markdown(
                "<p style='font-size:1rem;font-weight:700;color:#001e50;"
                "text-align:center;margin-bottom:2px'>TOTAL PONTOS</p>",
                unsafe_allow_html=True,
            )
            st.caption("Soma total de pontos por mês · TENDÊNCIA M.A = média dos últimos 3 meses completos")

            fig6, tbl6 = _chart_pontos(df)
            st.plotly_chart(fig6, use_container_width=True)
            if not tbl6.empty:
                st.dataframe(tbl6, use_container_width=True, hide_index=True,
                             column_config={"": st.column_config.TextColumn("", width="medium")})
    except Exception as _e_pts:
        st.error(f"❌ Erro ao renderizar TOTAL PONTOS: {_e_pts}")
        import traceback
        st.code(traceback.format_exc(), language="python")

    st.markdown("<div style='height:1.5rem'></div>", unsafe_allow_html=True)

    # ═══════════════════════════════════════════════════════════════════════════
    # Gráfico 8 — Pontos por Contrato
    # ═══════════════════════════════════════════════════════════════════════════
    try:
        with st.container(border=True):
            st.markdown(
                "<p style='font-size:1rem;font-weight:700;color:#001e50;"
                "text-align:center;margin-bottom:2px'>PONTOS POR CONTRATO</p>",
                unsafe_allow_html=True,
            )
            st.caption("Média de pontos por contrato (barras) · META = 1,5 (linha laranja)")

            fig8, tbl8 = _chart_pontos_por_contrato(df)
            st.plotly_chart(fig8, use_container_width=True)
            if not tbl8.empty:
                st.dataframe(tbl8, use_container_width=True, hide_index=True,
                             column_config={"": st.column_config.TextColumn("", width="medium")})
    except Exception as _e_ppc:
        st.error(f"❌ Erro ao renderizar PONTOS POR CONTRATO: {_e_ppc}")
        import traceback
        st.code(traceback.format_exc(), language="python")

    st.markdown("<div style='height:1.5rem'></div>", unsafe_allow_html=True)

    # ═══════════════════════════════════════════════════════════════════════════
    # Gráfico 7 — Contratos + AAK
    # ═══════════════════════════════════════════════════════════════════════════
    try:
        import traceback as _tb7
        _aak_atual = _aak_load()

        with st.container(border=True):
            st.markdown(
                "<p style='font-size:1rem;font-weight:700;color:#001e50;"
                "text-align:center;margin-bottom:2px'>CONTRATOS E AAK</p>",
                unsafe_allow_html=True,
            )
            st.caption("Contratos TT (barras) · AAK (linha laranja) · PENETRATION = NV÷AAK (linha verde, eixo dir.)")

            # ── Entrada manual de AAK ─────────────────────────────────────────
            try:
                _meses_aak = _meses_range(_AAK_N_MESES)
                with st.expander("✏️ Valores AAK — entrada manual"):
                    _df_aak = pd.DataFrame({
                        "Mes":      [nome for (_, _, nome) in _meses_aak],
                        "periodo":  [f"{y:04d}-{m:02d}" for (y, m, _) in _meses_aak],
                        "AAK":      [int(_aak_atual.get(f"{y:04d}-{m:02d}", 0))
                                     for (y, m, _) in _meses_aak],
                    })
                    _editado = st.data_editor(
                        _df_aak[["Mes", "AAK"]],
                        disabled=["Mes"],
                        use_container_width=True,
                        hide_index=True,
                        key="aak_editor",
                        column_config={
                            "AAK": st.column_config.NumberColumn(
                                "AAK", min_value=0, step=1
                            ),
                        },
                    )
                    if st.button("💾 Salvar AAK", key="btn_salvar_aak"):
                        for i in range(len(_editado)):
                            _aak_atual[_df_aak["periodo"].iloc[i]] = int(_editado["AAK"].iloc[i])
                        _aak_save(_aak_atual)
                        st.success("✅ AAK salvo com sucesso!")
                        st.rerun()
            except Exception as _e_exp:
                st.warning(f"⚠️ Expander AAK: {_e_exp}")
                st.code(_tb7.format_exc(), language="python")

            # ── Gráfico e tabela ──────────────────────────────────────────────
            fig7, tbl7 = _chart_contratos_aak(df, aak_manual=_aak_atual)
            st.plotly_chart(fig7, use_container_width=True)
            if not tbl7.empty:
                st.dataframe(tbl7, use_container_width=True, hide_index=True,
                             column_config={"": st.column_config.TextColumn("", width="medium")})

    except Exception as _e_aak:
        import traceback as _tb7
        st.error(f"❌ Erro CONTRATOS E AAK: {_e_aak}")
        st.code(_tb7.format_exc(), language="python")
