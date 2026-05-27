"""
dashboard.py — Dashboard de visualização de dados F&I (Google Drive → Excel)

Camadas:
  Dados:         load_data(), _fetch_bytes(), _normalize(), _build_download_url()
  Processamento: calc_kpis(), _pct_filled(), apply_filters()
  UI:            render_dashboard() → _render_kpis(), _render_filters(),
                                      _render_charts(), _render_table()
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

# ─── Mapeamento de colunas ────────────────────────────────────────────────────

_COL_MAP: dict[str, str] = {
    "PROPOSTA": "proposta",
    "EQUIPE": "equipe",
    "D. PAGTO": "data_pagto",
    "DATA": "data_pagto",
    "DATA PAGTO": "data_pagto",
    "CPF/CNPJ": "cpf_cnpj",
    "CLIENTE": "cliente",
    "VALOR DO VEICULO": "valor_veiculo",
    "VALOR VEÍCULO": "valor_veiculo",
    "VALOR VEICULO": "valor_veiculo",
    "ENTRADA": "entrada",
    "VALOR FINANCIADO": "valor_financiado",
    "SPF": "spf",
    "APP": "app",
    "GAP": "gap",
    "FRANQ": "franquia",
    "FRANQUIA": "franquia",
    "GE": "ge",
    "PROTEGE": "protege",
    "PRAZO": "prazo",
    "TAXA": "taxa",
    "N/S": "tipo_veiculo",
    "SEMPRE NV": "sempre_novo",
    "SEMPRE NOVO": "sempre_novo",
    "PESO TABELA": "peso_tabela",
    "VENDEDOR": "vendedor",
    "RETORNO": "retorno",
    "RETORNO3": "retorno",
    "PONTOS POR CONTRATOS": "pontos",
    "PONTOS": "pontos",
    "LOJA": "loja",
}

# ─── Constantes de UI ─────────────────────────────────────────────────────────

_VW_BLUE = "#001E50"
_PALETTE = [
    "#001E50", "#0040B0", "#00B0F0", "#1EBE5D",
    "#FF6B35", "#9B59B6", "#F39C12", "#E74C3C",
]
_CHART_LAYOUT = dict(
    template="plotly_white",
    height=320,
    margin=dict(l=10, r=10, t=30, b=10),
)

# ─── Camada de Dados ──────────────────────────────────────────────────────────


def _extract_drive_id(url: str) -> Optional[str]:
    """Extrai o ID do arquivo de qualquer formato de URL do Google Drive."""
    patterns = [
        r"/file/d/([a-zA-Z0-9_-]+)",
        r"/spreadsheets/d/([a-zA-Z0-9_-]+)",
        r"[?&]id=([a-zA-Z0-9_-]+)",
        r"/d/([a-zA-Z0-9_-]+)",
    ]
    for pattern in patterns:
        m = re.search(pattern, url)
        if m:
            return m.group(1)
    return None


def _build_download_url(raw_url: str) -> str:
    """Converte qualquer URL do Google Drive para URL de download direto."""
    if "docs.google.com/spreadsheets" in raw_url:
        file_id = _extract_drive_id(raw_url)
        if file_id:
            return f"https://docs.google.com/spreadsheets/d/{file_id}/export?format=xlsx"
    if "drive.google.com/uc" in raw_url and "export=download" in raw_url:
        return raw_url
    file_id = _extract_drive_id(raw_url)
    if file_id:
        return f"https://drive.google.com/uc?export=download&id={file_id}"
    return raw_url


@st.cache_data(ttl=300, show_spinner=False)
def _fetch_bytes(download_url: str) -> bytes:
    """Baixa os bytes do arquivo com cache de 5 minutos."""
    resp = requests.get(download_url, timeout=20, allow_redirects=True)
    content_type = resp.headers.get("Content-Type", "")
    if "text/html" in content_type:
        raise ValueError(
            "❌ O link retornou uma página HTML em vez do arquivo. "
            "Verifique se o arquivo está compartilhado publicamente no Google Drive "
            "(Compartilhar → Qualquer pessoa com o link → Visualizador)."
        )
    resp.raise_for_status()
    return resp.content


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza o DataFrame: renomeia colunas, converte tipos e limpa dados."""
    # Strip + upper nos nomes das colunas
    df.columns = [str(c).strip().upper() for c in df.columns]

    # Renomeia usando _COL_MAP
    df = df.rename(columns=_COL_MAP)

    # Remove linhas completamente nulas
    df = df.dropna(how="all")

    # Converte colunas numéricas
    numeric_cols = ["valor_veiculo", "entrada", "valor_financiado", "retorno", "pontos", "taxa", "prazo"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Converte data_pagto
    if "data_pagto" in df.columns:
        df["data_pagto"] = pd.to_datetime(df["data_pagto"], dayfirst=True, errors="coerce")

    # Remove linhas onde proposta E cliente são ambos NaN
    has_proposta = "proposta" in df.columns
    has_cliente = "cliente" in df.columns
    if has_proposta and has_cliente:
        mask = df["proposta"].isna() & df["cliente"].isna()
        df = df[~mask]
    elif has_proposta:
        df = df[df["proposta"].notna()]
    elif has_cliente:
        df = df[df["cliente"].notna()]

    return df.reset_index(drop=True)


def load_data(gdrive_url: str) -> tuple[Optional[pd.DataFrame], str]:
    """
    Carrega dados do Google Drive e retorna (df, "") ou (None, "mensagem de erro").
    """
    try:
        download_url = _build_download_url(gdrive_url)
        raw_bytes = _fetch_bytes(download_url)
        df = pd.read_excel(raw_bytes, header=0)
        df = _normalize(df)
        if df.empty:
            return None, "❌ A planilha está vazia ou não contém dados válidos após a normalização."
        return df, ""
    except requests.ConnectionError:
        return None, "❌ Sem conexão com a internet. Verifique sua rede e tente novamente."
    except requests.Timeout:
        return None, "❌ Timeout (20s) ao tentar baixar o arquivo. O servidor demorou demais para responder."
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else 0
        if status == 403:
            return None, (
                "❌ Acesso negado (403). O arquivo não está compartilhado publicamente. "
                "No Google Drive: Compartilhar → Qualquer pessoa com o link → Visualizador."
            )
        if status == 404:
            return None, "❌ Arquivo não encontrado (404). Verifique se o link está correto e o arquivo existe."
        return None, f"❌ Erro HTTP {status}: {e}"
    except ValueError as e:
        return None, str(e)
    except Exception as e:
        return None, f"❌ Erro inesperado: {e}"


# ─── Camada de Processamento ──────────────────────────────────────────────────


def _pct_filled(df: pd.DataFrame, col: str) -> float:
    """Retorna % de linhas onde col não é nulo/vazio/0."""
    if col not in df.columns or len(df) == 0:
        return 0.0
    series = df[col]
    filled = series.apply(
        lambda x: x is not None
        and not (isinstance(x, float) and pd.isna(x))
        and str(x).strip() not in ("", "0")
        and x != 0
    )
    return round(filled.sum() / len(df) * 100, 1)


def calc_kpis(df: pd.DataFrame) -> dict:
    """Calcula KPIs principais do DataFrame."""
    total_contratos = len(df)
    total_retorno = df["retorno"].sum() if "retorno" in df.columns else 0.0
    total_pontos = df["pontos"].sum() if "pontos" in df.columns else 0.0
    total_vf = df["valor_financiado"].sum() if "valor_financiado" in df.columns else 0.0
    vf_medio = df["valor_financiado"].mean() if "valor_financiado" in df.columns else 0.0
    n_vendedores = df["vendedor"].nunique() if "vendedor" in df.columns else 0

    return {
        "total_contratos": total_contratos,
        "total_retorno": total_retorno,
        "total_pontos": total_pontos,
        "total_vf": total_vf,
        "vf_medio": vf_medio if not pd.isna(vf_medio) else 0.0,
        "n_vendedores": n_vendedores,
        "pct_spf": _pct_filled(df, "spf"),
        "pct_app": _pct_filled(df, "app"),
        "pct_gap": _pct_filled(df, "gap"),
        "pct_ge": _pct_filled(df, "ge"),
        "pct_protege": _pct_filled(df, "protege"),
    }


def apply_filters(
    df: pd.DataFrame,
    equipes: list,
    vendedores: list,
    date_range: tuple,
    tipo_veiculo: str,
) -> pd.DataFrame:
    """Aplica filtros ao DataFrame."""
    result = df.copy()

    if equipes and "equipe" in result.columns:
        result = result[result["equipe"].isin(equipes)]

    if vendedores and "vendedor" in result.columns:
        result = result[result["vendedor"].isin(vendedores)]

    if date_range and len(date_range) == 2 and "data_pagto" in result.columns:
        d_min, d_max = date_range
        if d_min is not None:
            result = result[result["data_pagto"].isna() | (result["data_pagto"] >= pd.Timestamp(d_min))]
        if d_max is not None:
            result = result[result["data_pagto"].isna() | (result["data_pagto"] <= pd.Timestamp(d_max))]

    if tipo_veiculo and tipo_veiculo != "Todos" and "tipo_veiculo" in result.columns:
        letra = tipo_veiculo[tipo_veiculo.find("(") + 1] if "(" in tipo_veiculo else tipo_veiculo[0]
        result = result[result["tipo_veiculo"] == letra]

    return result.reset_index(drop=True)


# ─── Camada de UI ─────────────────────────────────────────────────────────────


def _render_kpis(df: pd.DataFrame) -> None:
    """Renderiza os KPIs principais em 5 colunas."""
    kpis = calc_kpis(df)
    with st.container(border=True):
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Total Contratos", f"{kpis['total_contratos']:,}")
        c2.metric("Retorno Total", f"R$ {kpis['total_retorno']:,.0f}")
        c3.metric("Total Pontos", f"{kpis['total_pontos']:,.1f}")
        c4.metric("VF Total", f"R$ {kpis['total_vf']:,.0f}")
        c5.metric("VF Médio", f"R$ {kpis['vf_medio']:,.0f}")


def _render_filters(df: pd.DataFrame) -> pd.DataFrame:
    """Renderiza os filtros e retorna o DataFrame filtrado."""
    with st.expander("🔍 Filtros", expanded=False):
        col1, col2, col3 = st.columns(3)

        with col1:
            equipe_opts = sorted(df["equipe"].dropna().unique().tolist()) if "equipe" in df.columns else []
            sel_equipes = st.multiselect("Equipe", options=equipe_opts, key="dash_flt_equipe")

        with col2:
            vend_opts = sorted(df["vendedor"].dropna().unique().tolist()) if "vendedor" in df.columns else []
            sel_vendedores = st.multiselect("Vendedor", options=vend_opts, key="dash_flt_vendedor")

        with col3:
            tipo_opts = ["Todos", "Novo (N)", "Seminovo (S)"]
            sel_tipo = st.radio("Tipo", options=tipo_opts, key="dash_flt_tipo", horizontal=True)

        date_range = (None, None)
        if "data_pagto" in df.columns:
            valid_dates = df["data_pagto"].dropna()
            if not valid_dates.empty:
                min_date = valid_dates.min().date()
                max_date = valid_dates.max().date()
                col_d1, col_d2 = st.columns(2)
                with col_d1:
                    d_from = st.date_input(
                        "Data início",
                        value=min_date,
                        min_value=min_date,
                        max_value=max_date,
                        key="dash_flt_date_from",
                    )
                with col_d2:
                    d_to = st.date_input(
                        "Data fim",
                        value=max_date,
                        min_value=min_date,
                        max_value=max_date,
                        key="dash_flt_date_to",
                    )
                date_range = (d_from, d_to)

    return apply_filters(df, sel_equipes, sel_vendedores, date_range, sel_tipo)


def _render_charts(df: pd.DataFrame) -> None:
    """Renderiza os 6 gráficos do dashboard."""

    # ── Linha 1 ──────────────────────────────────────────────────────────────
    col_l1, col_r1 = st.columns(2)

    with col_l1:
        with st.container(border=True):
            st.markdown("**Retorno por Equipe**")
            if "equipe" in df.columns and "retorno" in df.columns:
                grp = (
                    df.groupby("equipe", as_index=False)["retorno"]
                    .sum()
                    .sort_values("retorno", ascending=False)
                )
                fig = px.bar(
                    grp,
                    x="equipe",
                    y="retorno",
                    color_discrete_sequence=[_VW_BLUE],
                    labels={"equipe": "Equipe", "retorno": "Retorno (R$)"},
                )
                fig.update_layout(**_CHART_LAYOUT)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Sem dados de equipe/retorno.")

    with col_r1:
        with st.container(border=True):
            st.markdown("**Contratos por Equipe**")
            if "equipe" in df.columns:
                grp = df.groupby("equipe", as_index=False).size().rename(columns={"size": "contratos"})
                fig = go.Figure(
                    go.Pie(
                        labels=grp["equipe"],
                        values=grp["contratos"],
                        hole=0.5,
                        marker=dict(colors=_PALETTE),
                    )
                )
                fig.update_layout(**_CHART_LAYOUT)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Sem dados de equipe.")

    # ── Linha 2 ──────────────────────────────────────────────────────────────
    col_l2, col_r2 = st.columns(2)

    with col_l2:
        with st.container(border=True):
            st.markdown("**Top 10 Vendedores · Retorno**")
            if "vendedor" in df.columns and "retorno" in df.columns:
                top10 = (
                    df.groupby("vendedor", as_index=False)["retorno"]
                    .sum()
                    .sort_values("retorno", ascending=False)
                    .head(10)
                )
                fig = px.bar(
                    top10,
                    x="retorno",
                    y="vendedor",
                    orientation="h",
                    color_discrete_sequence=[_VW_BLUE],
                    labels={"vendedor": "", "retorno": "Retorno (R$)"},
                )
                fig.update_layout(**_CHART_LAYOUT, yaxis=dict(autorange="reversed"))
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Sem dados de vendedor/retorno.")

    with col_r2:
        with st.container(border=True):
            st.markdown("**Contratos por Dia**")
            if "data_pagto" in df.columns:
                daily = (
                    df.dropna(subset=["data_pagto"])
                    .groupby(df["data_pagto"].dt.date)
                    .size()
                    .reset_index(name="contratos")
                )
                daily.rename(columns={"data_pagto": "data"}, inplace=True)
                if not daily.empty:
                    fig = px.line(
                        daily,
                        x="data",
                        y="contratos",
                        color_discrete_sequence=[_VW_BLUE],
                        labels={"data": "Data", "contratos": "Contratos"},
                    )
                    fig.update_layout(**_CHART_LAYOUT)
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("Sem dados de data válidos.")
            else:
                st.info("Sem dados de data.")

    # ── Linha 3 ──────────────────────────────────────────────────────────────
    col_l3, col_r3 = st.columns(2)

    with col_l3:
        with st.container(border=True):
            st.markdown("**Penetração de Produtos (%)**")
            kpis = calc_kpis(df)
            produtos = {
                "SPF": kpis["pct_spf"],
                "APP": kpis["pct_app"],
                "GAP": kpis["pct_gap"],
                "GE": kpis["pct_ge"],
                "Protege": kpis["pct_protege"],
            }
            col_map = {"SPF": "spf", "APP": "app", "GAP": "gap", "GE": "ge", "Protege": "protege"}
            produtos_presentes = {k: v for k, v in produtos.items() if col_map[k] in df.columns}
            if produtos_presentes:
                pen_df = pd.DataFrame(
                    {"Produto": list(produtos_presentes.keys()), "Penetração (%)": list(produtos_presentes.values())}
                ).sort_values("Penetração (%)", ascending=True)
                fig = px.bar(
                    pen_df,
                    x="Penetração (%)",
                    y="Produto",
                    orientation="h",
                    color_discrete_sequence=["#0040B0"],
                    labels={"Produto": "", "Penetração (%)": "%"},
                )
                fig.update_layout(**_CHART_LAYOUT)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Sem dados de produtos.")

    with col_r3:
        with st.container(border=True):
            st.markdown("**Novo vs Seminovo**")
            if "tipo_veiculo" in df.columns:
                tv = df["tipo_veiculo"].value_counts().reset_index()
                tv.columns = ["tipo", "count"]
                label_map = {"N": "Novo", "S": "Seminovo", "U": "Usado"}
                tv["tipo"] = tv["tipo"].map(lambda x: label_map.get(str(x).upper(), str(x)))
                fig = go.Figure(
                    go.Pie(
                        labels=tv["tipo"],
                        values=tv["count"],
                        marker=dict(colors=_PALETTE[:len(tv)]),
                    )
                )
                fig.update_layout(**_CHART_LAYOUT)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Sem dados de tipo de veículo.")


def _render_table(df: pd.DataFrame) -> None:
    """Renderiza a tabela de resumo por vendedor."""
    st.markdown("#### 📋 Resumo por Vendedor")

    if "vendedor" not in df.columns:
        st.info("Sem dados de vendedor.")
        return

    agg: dict = {"proposta": "count"}
    if "retorno" in df.columns:
        agg["retorno"] = "sum"
    if "pontos" in df.columns:
        agg["pontos"] = "sum"
    if "valor_financiado" in df.columns:
        agg["valor_financiado"] = "mean"

    resumo = df.groupby("vendedor", as_index=False).agg(agg)
    rename_map = {"proposta": "Contratos"}
    if "retorno" in agg:
        rename_map["retorno"] = "Retorno"
    if "pontos" in agg:
        rename_map["pontos"] = "Pontos"
    if "valor_financiado" in agg:
        rename_map["valor_financiado"] = "VF Médio"
    resumo = resumo.rename(columns=rename_map)
    resumo = resumo.rename(columns={"vendedor": "Vendedor"})

    sort_col = "Retorno" if "Retorno" in resumo.columns else "Contratos"
    resumo = resumo.sort_values(sort_col, ascending=False)

    fmt: dict = {}
    if "Retorno" in resumo.columns:
        fmt["Retorno"] = lambda x: f"R$ {x:,.0f}"
    if "VF Médio" in resumo.columns:
        fmt["VF Médio"] = lambda x: f"R$ {x:,.0f}" if not pd.isna(x) else "-"
    if "Pontos" in resumo.columns:
        fmt["Pontos"] = lambda x: f"{x:.1f}"

    st.dataframe(
        resumo.style.format(fmt),
        use_container_width=True,
        hide_index=True,
    )


def render_dashboard(gdrive_url_default: str = "") -> None:
    """Ponto de entrada principal do dashboard."""
    st.markdown("""
    <div class="section-title">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none"
             stroke="#001e50" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="3" width="7" height="7"/>
            <rect x="14" y="3" width="7" height="7"/>
            <rect x="14" y="14" width="7" height="7"/>
            <rect x="3" y="14" width="7" height="7"/>
        </svg>
        <span>Dashboard F&amp;I</span>
    </div>
    """, unsafe_allow_html=True)

    col_url, col_btn = st.columns([5, 1])
    with col_url:
        gdrive_url = st.text_input(
            "Link da planilha no Google Drive",
            value=st.session_state.get("dash_gdrive_url", gdrive_url_default),
            placeholder="https://drive.google.com/...",
            label_visibility="collapsed",
            key="dash_gdrive_url",
        )
    with col_btn:
        if st.button("🔄 Atualizar", use_container_width=True, key="dash_refresh"):
            _fetch_bytes.clear()
            st.session_state["_dash_last_updated"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            st.rerun()

    last_upd = st.session_state.get("_dash_last_updated")
    if last_upd:
        st.caption(f"Última atualização: {last_upd}")

    if not gdrive_url or not gdrive_url.strip():
        st.info(
            "ℹ️ Informe o link da planilha do Google Drive acima para carregar o Dashboard. "
            "O arquivo deve estar compartilhado publicamente (Compartilhar → Qualquer pessoa com o link)."
        )
        return

    with st.spinner("⏳ Carregando dados do Dashboard…"):
        df, err = load_data(gdrive_url.strip())

    if err:
        st.error(err)
        st.stop()

    if df is None or df.empty:
        st.warning("Nenhum dado encontrado na planilha.")
        st.stop()

    if "_dash_last_updated" not in st.session_state:
        st.session_state["_dash_last_updated"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    _render_kpis(df)
    st.divider()
    filtered_df = _render_filters(df)
    _render_charts(filtered_df)
    st.divider()
    _render_table(filtered_df)
