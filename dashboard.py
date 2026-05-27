"""
dashboard.py — Dashboard F&I via Microsoft Graph API (OneDrive / Excel Online)

Camadas:
  Dados:         load_data() · _get_ms_token() · _get_ids() · _list_worksheets()
                 _read_ws() · _normalize()
  Processamento: calc_kpis() · _pct_filled() · apply_filters()
  UI:            render_dashboard() → _render_kpis() · _render_filters()
                                      _render_charts() · _render_table()

A autenticação reutiliza o token Microsoft já armazenado em st.session_state
pela tela de Configurações — nenhum login adicional necessário.
O cache de IDs (drive_id / item_id / ws_id) compartilha o mesmo namespace
usado pelo módulo principal, evitando chamadas redundantes ao Graph.
"""

from __future__ import annotations

import base64
import time
from datetime import datetime
from urllib.parse import quote as _url_quote

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

# ─── Mapeamento de colunas (header da planilha → nome interno) ────────────────

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

_MESES_PT = {
    1: "JANEIRO", 2: "FEVEREIRO", 3: "MARÇO", 4: "ABRIL",
    5: "MAIO", 6: "JUNHO", 7: "JULHO", 8: "AGOSTO",
    9: "SETEMBRO", 10: "OUTUBRO", 11: "NOVEMBRO", 12: "DEZEMBRO",
}


def _nome_aba_atual() -> str:
    now = datetime.now()
    return f"{_MESES_PT[now.month]} {now.year}"


# ─── Camada de Dados — Microsoft Graph API ────────────────────────────────────

def _get_ms_token(client_id: str) -> str:
    """Retorna access token válido; renova via refresh_token se necessário."""
    token = st.session_state.get("_ms_token")
    exp   = st.session_state.get("_ms_token_exp", 0)
    if token and time.time() < exp - 60:
        return token

    refresh = st.session_state.get("_ms_refresh_token")
    if refresh:
        r = requests.post(
            "https://login.microsoftonline.com/common/oauth2/v2.0/token",
            data={
                "grant_type":    "refresh_token",
                "client_id":     client_id,
                "refresh_token": refresh,
                "scope":         "https://graph.microsoft.com/Files.ReadWrite",
            },
            timeout=15,
        )
        d = r.json()
        if "access_token" in d:
            st.session_state["_ms_token"]         = d["access_token"]
            st.session_state["_ms_token_exp"]     = time.time() + d.get("expires_in", 3600)
            st.session_state["_ms_refresh_token"] = d.get("refresh_token", refresh)
            return d["access_token"]

    raise Exception(
        "Não autenticado. Faça login com sua conta Microsoft nas Configurações (🔑)."
    )


def _get_ids(token: str, sharing_url: str) -> tuple[str, str]:
    """Resolve sharing URL → (drive_id, item_id). Reutiliza cache do app principal."""
    # Tenta reutilizar qualquer entrada de cache existente
    for key, val in list(st.session_state.items()):
        if key.startswith("_xl_ids_") and isinstance(val, (tuple, list)) and len(val) == 3:
            return val[0], val[1]

    encoded = base64.urlsafe_b64encode(sharing_url.encode()).decode().rstrip("=")
    r = requests.get(
        f"https://graph.microsoft.com/v1.0/shares/u!{encoded}/driveItem",
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    r.raise_for_status()
    d = r.json()
    return d["parentReference"]["driveId"], d["id"]


def _list_worksheets(token: str, sharing_url: str) -> list[str]:
    """Retorna lista de nomes de todas as abas do arquivo Excel."""
    drive_id, item_id = _get_ids(token, sharing_url)
    r = requests.get(
        f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}"
        f"/workbook/worksheets",
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    r.raise_for_status()
    return [ws["name"] for ws in r.json().get("value", [])]


def _get_ws_id(token: str, drive_id: str, item_id: str, aba: str) -> str:
    """Retorna ws_id para a aba especificada; usa cache quando disponível."""
    cache_key = f"_xl_ids_{aba}"
    cached = st.session_state.get(cache_key)
    if cached and len(cached) == 3:
        return cached[2]

    r = requests.get(
        f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}"
        f"/workbook/worksheets",
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    r.raise_for_status()
    for ws in r.json().get("value", []):
        if ws["name"] == aba:
            ws_id = ws["id"]
            st.session_state[cache_key] = (drive_id, item_id, ws_id)
            return ws_id
    raise Exception(f"Aba '{aba}' não encontrada no arquivo.")


def _read_ws(token: str, drive_id: str, item_id: str, ws_id: str) -> list[list]:
    """Lê todos os valores da aba via usedRange (reutiliza sessão Excel se ativa)."""
    headers = {"Authorization": f"Bearer {token}"}
    session_id = st.session_state.get(f"_xl_sess_{item_id}", "")
    if session_id:
        headers["workbook-session-id"] = session_id

    base = (
        f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}"
        f"/workbook/worksheets/{_url_quote(ws_id)}"
    )
    r = requests.get(
        f"{base}/usedRange?$select=values",
        headers=headers,
        timeout=30,
    )
    r.raise_for_status()
    return r.json().get("values", [])


def load_data(client_id: str, sharing_url: str, aba: str) -> tuple[pd.DataFrame | None, str]:
    """
    Carrega e normaliza os dados da aba especificada.
    Cache manual de 5 minutos em session_state (TTL por aba).
    Retorna (df, "") em caso de sucesso ou (None, "mensagem") em caso de erro.
    """
    cache_key = f"_dash_df_{aba}"
    ts_key    = f"_dash_ts_{aba}"

    cached_df = st.session_state.get(cache_key)
    cached_ts = st.session_state.get(ts_key, 0)
    if cached_df is not None and time.time() - cached_ts < 300:
        return cached_df, ""

    try:
        token    = _get_ms_token(client_id)
        drive_id, item_id = _get_ids(token, sharing_url)
        ws_id    = _get_ws_id(token, drive_id, item_id, aba)
        values   = _read_ws(token, drive_id, item_id, ws_id)

        if not values or len(values) < 2:
            return None, f"⚠️ A aba '{aba}' está vazia ou sem dados."

        df = pd.DataFrame(values[1:], columns=[str(c).strip() for c in values[0]])
        df = _normalize(df)

        if df.empty:
            return None, f"⚠️ Nenhum dado válido encontrado na aba '{aba}'."

        st.session_state[cache_key] = df
        st.session_state[ts_key]    = time.time()
        return df, ""

    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else 0
        msgs = {
            401: "❌ Token expirado (401). Reconecte sua conta Microsoft nas Configurações.",
            403: "❌ Sem permissão (403). Verifique se sua conta tem acesso ao arquivo.",
            404: "❌ Arquivo não encontrado (404). Verifique o link do OneDrive.",
        }
        return None, msgs.get(status, f"❌ Erro HTTP {status}.")
    except requests.ConnectionError:
        return None, "❌ Sem conexão com a internet."
    except requests.Timeout:
        return None, "❌ Timeout ao tentar ler o arquivo (30s)."
    except Exception as e:
        return None, f"❌ {e}"


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza colunas, tipos e remove linhas degeneradas."""
    df.columns = [str(c).strip().upper() for c in df.columns]
    df = df.rename(columns=_COL_MAP)
    df = df.dropna(how="all")

    for col in ("valor_veiculo", "entrada", "valor_financiado", "retorno", "pontos", "taxa", "prazo"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "data_pagto" in df.columns:
        df["data_pagto"] = pd.to_datetime(df["data_pagto"], dayfirst=True, errors="coerce")

    has_p = "proposta" in df.columns
    has_c = "cliente"  in df.columns
    if has_p and has_c:
        df = df[~(df["proposta"].isna() & df["cliente"].isna())]
    elif has_p:
        df = df[df["proposta"].notna()]
    elif has_c:
        df = df[df["cliente"].notna()]

    return df.reset_index(drop=True)


# ─── Camada de Processamento ──────────────────────────────────────────────────

def _pct_filled(df: pd.DataFrame, col: str) -> float:
    if col not in df.columns or len(df) == 0:
        return 0.0
    filled = df[col].apply(
        lambda x: x is not None
        and not (isinstance(x, float) and pd.isna(x))
        and str(x).strip() not in ("", "0")
        and x != 0
    )
    return round(filled.sum() / len(df) * 100, 1)


def calc_kpis(df: pd.DataFrame) -> dict:
    vf_medio = df["valor_financiado"].mean() if "valor_financiado" in df.columns else 0.0
    return {
        "total_contratos": len(df),
        "total_retorno":   df["retorno"].sum()          if "retorno"          in df.columns else 0.0,
        "total_pontos":    df["pontos"].sum()            if "pontos"           in df.columns else 0.0,
        "total_vf":        df["valor_financiado"].sum()  if "valor_financiado" in df.columns else 0.0,
        "vf_medio":        vf_medio if not pd.isna(vf_medio) else 0.0,
        "n_vendedores":    df["vendedor"].nunique()      if "vendedor"         in df.columns else 0,
        "pct_spf":     _pct_filled(df, "spf"),
        "pct_app":     _pct_filled(df, "app"),
        "pct_gap":     _pct_filled(df, "gap"),
        "pct_ge":      _pct_filled(df, "ge"),
        "pct_protege": _pct_filled(df, "protege"),
    }


def apply_filters(
    df: pd.DataFrame,
    equipes: list,
    vendedores: list,
    date_range: tuple,
    tipo_veiculo: str,
) -> pd.DataFrame:
    result = df.copy()
    if equipes   and "equipe"   in result.columns:
        result = result[result["equipe"].isin(equipes)]
    if vendedores and "vendedor" in result.columns:
        result = result[result["vendedor"].isin(vendedores)]
    if date_range and len(date_range) == 2 and "data_pagto" in result.columns:
        d_min, d_max = date_range
        if d_min:
            result = result[result["data_pagto"].isna() | (result["data_pagto"] >= pd.Timestamp(d_min))]
        if d_max:
            result = result[result["data_pagto"].isna() | (result["data_pagto"] <= pd.Timestamp(d_max))]
    if tipo_veiculo and tipo_veiculo != "Todos" and "tipo_veiculo" in result.columns:
        letra = tipo_veiculo[tipo_veiculo.index("(") + 1] if "(" in tipo_veiculo else tipo_veiculo[0]
        result = result[result["tipo_veiculo"] == letra]
    return result.reset_index(drop=True)


# ─── Camada de UI ─────────────────────────────────────────────────────────────

def _render_kpis(df: pd.DataFrame) -> None:
    kpis = calc_kpis(df)
    with st.container(border=True):
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Total Contratos", f"{kpis['total_contratos']:,}")
        c2.metric("Retorno Total",   f"R$ {kpis['total_retorno']:,.0f}")
        c3.metric("Total Pontos",    f"{kpis['total_pontos']:,.1f}")
        c4.metric("VF Total",        f"R$ {kpis['total_vf']:,.0f}")
        c5.metric("VF Médio",        f"R$ {kpis['vf_medio']:,.0f}")


def _render_filters(df: pd.DataFrame) -> pd.DataFrame:
    with st.expander("🔍 Filtros", expanded=False):
        col1, col2, col3 = st.columns(3)
        with col1:
            opts_eq = sorted(df["equipe"].dropna().unique()) if "equipe" in df.columns else []
            sel_eq  = st.multiselect("Equipe", opts_eq, key="dash_flt_equipe")
        with col2:
            opts_vd = sorted(df["vendedor"].dropna().unique()) if "vendedor" in df.columns else []
            sel_vd  = st.multiselect("Vendedor", opts_vd, key="dash_flt_vendedor")
        with col3:
            sel_tipo = st.radio("Tipo", ["Todos", "Novo (N)", "Seminovo (S)"],
                                key="dash_flt_tipo", horizontal=True)

        date_range = (None, None)
        if "data_pagto" in df.columns:
            valid = df["data_pagto"].dropna()
            if not valid.empty:
                mn, mx = valid.min().date(), valid.max().date()
                cd1, cd2 = st.columns(2)
                with cd1:
                    d_from = st.date_input("Data início", value=mn, min_value=mn, max_value=mx,
                                           key="dash_flt_df")
                with cd2:
                    d_to   = st.date_input("Data fim",    value=mx, min_value=mn, max_value=mx,
                                           key="dash_flt_dt")
                date_range = (d_from, d_to)

    return apply_filters(df, sel_eq, sel_vd, date_range, sel_tipo)


def _render_charts(df: pd.DataFrame) -> None:
    # ── Linha 1 ───────────────────────────────────────────────────────────────
    l1, r1 = st.columns(2)

    with l1, st.container(border=True):
        st.markdown("**Retorno por Equipe**")
        if "equipe" in df.columns and "retorno" in df.columns:
            grp = (df.groupby("equipe", as_index=False)["retorno"]
                   .sum().sort_values("retorno", ascending=False))
            fig = px.bar(grp, x="equipe", y="retorno",
                         color_discrete_sequence=[_VW_BLUE],
                         labels={"equipe": "Equipe", "retorno": "Retorno (R$)"})
            fig.update_layout(**_CHART_LAYOUT)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Sem dados de equipe/retorno.")

    with r1, st.container(border=True):
        st.markdown("**Contratos por Equipe**")
        if "equipe" in df.columns:
            grp = df.groupby("equipe", as_index=False).size().rename(columns={"size": "contratos"})
            fig = go.Figure(go.Pie(labels=grp["equipe"], values=grp["contratos"],
                                   hole=0.5, marker=dict(colors=_PALETTE)))
            fig.update_layout(**_CHART_LAYOUT)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Sem dados de equipe.")

    # ── Linha 2 ───────────────────────────────────────────────────────────────
    l2, r2 = st.columns(2)

    with l2, st.container(border=True):
        st.markdown("**Top 10 Vendedores · Retorno**")
        if "vendedor" in df.columns and "retorno" in df.columns:
            top10 = (df.groupby("vendedor", as_index=False)["retorno"]
                     .sum().sort_values("retorno", ascending=False).head(10))
            fig = px.bar(top10, x="retorno", y="vendedor", orientation="h",
                         color_discrete_sequence=[_VW_BLUE],
                         labels={"vendedor": "", "retorno": "Retorno (R$)"})
            fig.update_layout(**_CHART_LAYOUT, yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Sem dados de vendedor/retorno.")

    with r2, st.container(border=True):
        st.markdown("**Contratos por Dia**")
        if "data_pagto" in df.columns:
            daily = (df.dropna(subset=["data_pagto"])
                     .groupby(df["data_pagto"].dt.date).size()
                     .reset_index(name="contratos")
                     .rename(columns={"data_pagto": "data"}))
            if not daily.empty:
                fig = px.line(daily, x="data", y="contratos",
                              color_discrete_sequence=[_VW_BLUE],
                              labels={"data": "Data", "contratos": "Contratos"})
                fig.update_layout(**_CHART_LAYOUT)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Sem datas válidas.")
        else:
            st.info("Sem dados de data.")

    # ── Linha 3 ───────────────────────────────────────────────────────────────
    l3, r3 = st.columns(2)

    with l3, st.container(border=True):
        st.markdown("**Penetração de Produtos (%)**")
        kpis = calc_kpis(df)
        _prod_map = {"SPF": "spf", "APP": "app", "GAP": "gap", "GE": "ge", "Protege": "protege"}
        _pct_map  = {"SPF": "pct_spf", "APP": "pct_app", "GAP": "pct_gap",
                     "GE": "pct_ge", "Protege": "pct_protege"}
        presentes = {k: kpis[_pct_map[k]] for k in _prod_map if _prod_map[k] in df.columns}
        if presentes:
            pen = (pd.DataFrame({"Produto": list(presentes), "Penetração (%)": list(presentes.values())})
                   .sort_values("Penetração (%)", ascending=True))
            fig = px.bar(pen, x="Penetração (%)", y="Produto", orientation="h",
                         color_discrete_sequence=["#0040B0"],
                         labels={"Produto": "", "Penetração (%)": "%"})
            fig.update_layout(**_CHART_LAYOUT)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Sem dados de produtos.")

    with r3, st.container(border=True):
        st.markdown("**Novo vs Seminovo**")
        if "tipo_veiculo" in df.columns:
            tv = df["tipo_veiculo"].value_counts().reset_index()
            tv.columns = ["tipo", "count"]
            lbl = {"N": "Novo", "S": "Seminovo", "U": "Usado"}
            tv["tipo"] = tv["tipo"].map(lambda x: lbl.get(str(x).upper(), str(x)))
            fig = go.Figure(go.Pie(labels=tv["tipo"], values=tv["count"],
                                   marker=dict(colors=_PALETTE[:len(tv)])))
            fig.update_layout(**_CHART_LAYOUT)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Sem dados de tipo de veículo.")


def _render_table(df: pd.DataFrame) -> None:
    st.markdown("#### 📋 Resumo por Vendedor")
    if "vendedor" not in df.columns:
        st.info("Sem dados de vendedor.")
        return

    agg = {"proposta": "count"}
    if "retorno"          in df.columns: agg["retorno"]          = "sum"
    if "pontos"           in df.columns: agg["pontos"]           = "sum"
    if "valor_financiado" in df.columns: agg["valor_financiado"] = "mean"

    resumo = df.groupby("vendedor", as_index=False).agg(agg)
    resumo = resumo.rename(columns={
        "vendedor": "Vendedor", "proposta": "Contratos",
        "retorno": "Retorno", "pontos": "Pontos", "valor_financiado": "VF Médio",
    })
    sort_col = "Retorno" if "Retorno" in resumo.columns else "Contratos"
    resumo = resumo.sort_values(sort_col, ascending=False)

    fmt = {}
    if "Retorno"  in resumo.columns: fmt["Retorno"]  = lambda x: f"R$ {x:,.0f}"
    if "VF Médio" in resumo.columns: fmt["VF Médio"] = lambda x: f"R$ {x:,.0f}" if not pd.isna(x) else "-"
    if "Pontos"   in resumo.columns: fmt["Pontos"]   = lambda x: f"{x:.1f}"

    st.dataframe(resumo.style.format(fmt), use_container_width=True, hide_index=True)


# ─── Entry point ──────────────────────────────────────────────────────────────

def render_dashboard(client_id: str = "", sharing_url: str = "") -> None:
    """Ponto de entrada do Dashboard — chamado pelo app.py."""
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

    # Guarda autenticado
    if st.session_state.get("_msal_auth_status") != "authenticated":
        st.info("🔑 Faça login com sua conta Microsoft nas **Configurações** para visualizar o Dashboard.")
        return

    if not sharing_url:
        st.info("⚙️ Configure o link do Excel (OneDrive) nas **Configurações**.")
        return

    # Seleção de aba + botão atualizar
    col_sel, col_btn = st.columns([5, 1])

    with col_btn:
        refresh = st.button("🔄 Atualizar", key="dash_refresh", use_container_width=True)

    with col_sel:
        with st.spinner("Listando abas…"):
            try:
                token    = _get_ms_token(client_id)
                ws_names = _list_worksheets(token, sharing_url)
            except Exception as e:
                st.error(f"❌ Erro ao conectar: {e}")
                return

        if not ws_names:
            st.warning("Nenhuma aba encontrada.")
            return

        atual   = _nome_aba_atual()
        def_idx = ws_names.index(atual) if atual in ws_names else 0
        aba     = st.selectbox("📄 Aba", ws_names, index=def_idx, key="dash_aba_sel",
                               label_visibility="collapsed")

    # Limpa cache da aba selecionada ao clicar em Atualizar
    if refresh:
        st.session_state.pop(f"_dash_df_{aba}", None)
        st.session_state.pop(f"_dash_ts_{aba}", None)
        st.rerun()

    # Carrega dados
    with st.spinner(f"⏳ Carregando dados da aba **{aba}**…"):
        df, err = load_data(client_id, sharing_url, aba)

    if err:
        st.error(err)
        return
    if df is None or df.empty:
        st.warning("Nenhum dado encontrado.")
        return

    # Timestamp da última atualização
    ts = st.session_state.get(f"_dash_ts_{aba}")
    if ts:
        st.caption(f"Última atualização: {datetime.fromtimestamp(ts).strftime('%d/%m/%Y %H:%M:%S')} "
                   f"· {len(df)} registros · aba **{aba}**")

    _render_kpis(df)
    st.divider()
    filtered = _render_filters(df)
    _render_charts(filtered)
    st.divider()
    _render_table(filtered)
