"""
comissao.py — Módulo de Cálculo de Comissão de Vendedores

Arquitetura em camadas:
  Configuração  → COMMISSION_TABLE (única fonte de verdade)
  Leitura       → load_bigbase()
  Filtro        → filter_records()
  Cálculo       → calc_commission()
  Interface     → render_comissao() → _render_kpis / _render_table / _render_charts

Lê diretamente da aba "BIGBASE" da planilha do Dashboard (dash_url).
Autenticação reutiliza o token Microsoft já armazenado em session_state.
"""

from __future__ import annotations

import base64
import time
from datetime import date, datetime
from urllib.parse import quote as _url_quote

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st


# ─── Tabela de Comissões (única fonte de verdade) ─────────────────────────────
# Edite APENAS aqui para alterar valores.
# Chaves são normalizadas para uppercase no lookup — sem duplicatas necessárias.

COMMISSION_TABLE: dict[str, float] = {
    "AP":               15.00,
    "GAP":              25.00,
    "FRANQUIA":         25.00,
    "SPF BASICO":       75.00,
    "SPF BÁSICO":       75.00,
    "SPF NORMAL":      100.00,
    "SPF PLUS":        150.00,
    "SEGURO VW":       275.00,
    "SEGURO CORRETORA":100.00,
    "GE 1":            250.00,
    "GE 2":            300.00,
    "GE 3":            275.00,
    "GE 4":            325.00,
    "REV PLAN":        100.00,
    "PROTEGE BAS 24":   25.00,
    "PROT BAS 24":      25.00,
    "PROTEGE BAS 36":   35.00,
    "PROT BAS 36":      35.00,
    "PROTEGE PLUS 24":  50.00,
    "PROT PLUS 24":     50.00,
    "PROTEGE PLUS 36":  60.00,
    "PROT PLUS 36":     60.00,
}

# Lookup normalizado (uppercase) — construído uma única vez no import
_COMM_NORM: dict[str, float] = {k.upper().strip(): v for k, v in COMMISSION_TABLE.items()}


def _commission(produto: str) -> float:
    """Retorna o valor de comissão de um produto (case-insensitive, 0.0 se não mapeado)."""
    if not produto or str(produto).strip() in ("", "0", "0.0"):
        return 0.0
    return _COMM_NORM.get(str(produto).upper().strip(), 0.0)


# ─── Colunas de produto na BIGBASE ────────────────────────────────────────────
# col_interna → rótulo de exibição

PRODUCT_COLS: dict[str, str] = {
    "spf":      "SPF / Seguro",
    "app":      "APP",
    "gap":      "GAP",
    "franquia": "Franquia",
    "rev_plan": "Rev Plan",
    "ge":       "GE",
    "protege":  "Protege",
}

# ─── Especificação de colunas do BIGBASE ──────────────────────────────────────
# Cada entrada: (nome_interno, [headers aceitos em uppercase], posição_fallback)
# Posições confirmadas pelo usuário:
#   G(6)=data  M(12)=spf  N(13)=app  O(14)=gap  P(15)=franquia
#   Q(16)=rev_plan  R(17)=ge  S(18)=protege  Y(24)=vendedor  Z(25)=retorno

_BIGBASE_SPEC: list[tuple[str, list[str], int | None]] = [
    ("proposta",         ["PROPOSTA", "N PROPOSTA", "NUM PROPOSTA"],          0),
    ("equipe",           ["EQUIPE", "LOJA", "LOJA/EQUIPE"],                   1),
    ("data_pagto",       ["D. PAGTO","DATA","DATA PAGTO","DT PAGTO",
                          "D.PAGTO","DATA PAGAMENTO","DATA DE PAGAMENTO"],     6),
    ("spf",              ["SPF","SPF/SEGURO","SEGURO PROT FINANCEIRA"],       12),
    ("app",              ["APP","ACID PESSOAIS","ACIDENTE PESSOAL"],          13),
    ("gap",              ["GAP"],                                             14),
    ("franquia",         ["FRANQ","FRANQUIA","SEGURO FRANQUIA"],              15),
    ("rev_plan",         ["REV PLAN","REV_PLAN","REVISAO","REVISÃO"],         16),
    ("ge",               ["GE","GARANTIA","GARANTIA ESTENDIDA"],              17),
    ("protege",          ["PROTEGE","VW PROTEGE"],                            18),
    ("vendedor",         ["VENDEDOR","CONSULTOR","NOME VENDEDOR"],            24),
    ("retorno",          ["RETORNO","RETORNO3","RETORNO 3","RETORNO F&I"],    25),
    ("cliente",          ["CLIENTE","NOME CLIENTE","RAZAO SOCIAL"],          None),
    ("cpf_cnpj",         ["CPF/CNPJ","CPF","CNPJ","DOCUMENTO"],             None),
    ("valor_financiado", ["VALOR FINANCIADO","VL FINANCIADO"],               None),
    ("pontos",           ["PONTOS","PONTOS POR CONTRATOS"],                  None),
]


def _build_bigbase_df(values: list[list]) -> pd.DataFrame:
    """
    Constrói DataFrame normalizado a partir dos valores brutos do BIGBASE.

    Para cada coluna interna tenta, em ordem:
      1. Localizar pelo nome do cabeçalho (case-insensitive)
      2. Usar a posição confirmada pelo usuário como fallback

    Isso garante funcionamento independente do nome real dos cabeçalhos.
    """
    if not values or len(values) < 2:
        return pd.DataFrame()

    headers_raw = [str(c).strip() for c in values[0]]
    headers_up  = [h.upper() for h in headers_raw]

    # Resolve índice de coluna para cada spec
    col_index: dict[str, int | None] = {}
    for name, aliases, fallback in _BIGBASE_SPEC:
        idx: int | None = None
        for alias in aliases:
            if alias in headers_up:
                idx = headers_up.index(alias)
                break
        if idx is None and fallback is not None and fallback < len(headers_up):
            idx = fallback
        col_index[name] = idx

    # Constrói linhas usando os índices resolvidos
    records = []
    for row in values[1:]:
        record: dict = {}
        for name, idx in col_index.items():
            if idx is not None and idx < len(row):
                record[name] = row[idx]
            else:
                record[name] = None
        records.append(record)

    return pd.DataFrame(records)


_BIGBASE_TAB  = "BIGBASE"
_CACHE_TTL    = 300   # segundos (5 min)


# ─── Camada de Leitura — Graph API ────────────────────────────────────────────

def _ms_token() -> str:
    """Retorna access token válido da session_state (renova via refresh se necessário)."""
    token = st.session_state.get("_ms_token")
    exp   = st.session_state.get("_ms_token_exp", 0)
    if token and time.time() < exp - 60:
        return token

    refresh   = st.session_state.get("_ms_refresh_token")
    client_id = st.session_state.get("_comm_client_id", "")
    if refresh and client_id:
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

    raise Exception("Não autenticado. Faça login nas Configurações (🔑).")


def _resolve_file(token: str, sharing_url: str) -> tuple[str, str]:
    """Resolve sharing_url → (drive_id, item_id) com cache por URL."""
    import hashlib
    url_key   = f"_comm_file_{hashlib.md5(sharing_url.encode()).hexdigest()[:12]}"
    cached    = st.session_state.get(url_key)
    if cached:
        return cached

    encoded = base64.urlsafe_b64encode(sharing_url.encode()).decode().rstrip("=")
    r = requests.get(
        f"https://graph.microsoft.com/v1.0/shares/u!{encoded}/driveItem",
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    r.raise_for_status()
    d = r.json()
    ids = (d["parentReference"]["driveId"], d["id"])
    st.session_state[url_key] = ids
    return ids


def _find_ws_id(token: str, drive_id: str, item_id: str, tab_name: str) -> str:
    """Localiza ws_id pelo nome da aba (case-insensitive fallback)."""
    cache_key = f"_comm_ws_{item_id}_{tab_name}"
    cached = st.session_state.get(cache_key)
    if cached:
        return cached

    r = requests.get(
        f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}"
        f"/workbook/worksheets",
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    r.raise_for_status()
    sheets = r.json().get("value", [])

    # Tenta match exato, depois case-insensitive
    ws_id = None
    for ws in sheets:
        if ws["name"] == tab_name:
            ws_id = ws["id"]
            break
    if ws_id is None:
        for ws in sheets:
            if ws["name"].upper() == tab_name.upper():
                ws_id = ws["id"]
                break
    if ws_id is None:
        nomes = [ws["name"] for ws in sheets]
        raise Exception(f"Aba '{tab_name}' não encontrada. Abas disponíveis: {nomes}")

    st.session_state[cache_key] = ws_id
    return ws_id


def _read_range(token: str, drive_id: str, item_id: str, ws_id: str) -> list[list]:
    """Lê usedRange da aba (reutiliza sessão Excel se ativa)."""
    hdrs = {"Authorization": f"Bearer {token}"}
    sess = st.session_state.get(f"_xl_sess_{item_id}", "")
    if sess:
        hdrs["workbook-session-id"] = sess
    r = requests.get(
        f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}"
        f"/workbook/worksheets/{_url_quote(ws_id)}/usedRange?$select=values",
        headers=hdrs,
        timeout=40,
    )
    r.raise_for_status()
    return r.json().get("values", [])


def load_bigbase(client_id: str, sharing_url: str) -> tuple[pd.DataFrame | None, str]:
    """
    Lê e normaliza a aba BIGBASE com cache de 5 minutos.
    Retorna (df, "") em sucesso, (None, "mensagem") em erro.
    """
    # Guarda client_id para renovação de token
    st.session_state["_comm_client_id"] = client_id

    cache_key = "_comm_df_bigbase"
    ts_key    = "_comm_ts_bigbase"

    cached    = st.session_state.get(cache_key)
    cached_ts = st.session_state.get(ts_key, 0)
    if cached is not None and time.time() - cached_ts < _CACHE_TTL:
        return cached, ""

    try:
        token             = _ms_token()
        drive_id, item_id = _resolve_file(token, sharing_url)
        ws_id             = _find_ws_id(token, drive_id, item_id, _BIGBASE_TAB)
        values            = _read_range(token, drive_id, item_id, ws_id)

        if not values or len(values) < 2:
            return None, "⚠️ A aba BIGBASE está vazia ou sem dados suficientes."

        # Usa mapeamento por posição (com fallback por nome de cabeçalho)
        df = _build_bigbase_df(values)

        if df.empty:
            return None, "⚠️ Não foi possível interpretar as colunas da BIGBASE."

        df = df.dropna(how="all")

        # Tipos numéricos
        for col in ("retorno", "pontos", "valor_financiado"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # Data — aceita tanto serial Excel (número) quanto string DD/MM/YYYY
        if "data_pagto" in df.columns:
            def _parse_date(v):
                if v is None or (isinstance(v, float) and pd.isna(v)):
                    return pd.NaT
                # Excel serial number
                if isinstance(v, (int, float)):
                    try:
                        return pd.Timestamp("1899-12-30") + pd.Timedelta(days=int(v))
                    except Exception:
                        return pd.NaT
                return pd.to_datetime(str(v), dayfirst=True, errors="coerce")

            df["data_pagto"] = df["data_pagto"].apply(_parse_date)

        # Remove linhas completamente sem dados de vendedor e data
        df = df[~(df.get("vendedor", pd.Series(dtype=str)).isna()
                  & df.get("data_pagto", pd.Series(dtype="datetime64[ns]")).isna())]

        df = df.reset_index(drop=True)

        st.session_state[cache_key] = df
        st.session_state[ts_key]    = time.time()
        return df, ""

    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 0
        msgs   = {
            401: "❌ Token expirado. Reconecte sua conta Microsoft nas Configurações.",
            403: "❌ Sem permissão de acesso ao arquivo (403).",
            404: "❌ Arquivo não encontrado (404). Verifique o link do OneDrive.",
        }
        return None, msgs.get(status, f"❌ Erro HTTP {status}.")
    except requests.ConnectionError:
        return None, "❌ Sem conexão com a internet."
    except requests.Timeout:
        return None, "❌ Timeout ao carregar BIGBASE (40 s). Tente novamente."
    except Exception as exc:
        return None, f"❌ {exc}"


# ─── Camada de Filtro ─────────────────────────────────────────────────────────

def filter_records(
    df: pd.DataFrame,
    vendedor: str,
    data_ini: date,
    data_fim: date,
) -> pd.DataFrame:
    """Filtra BIGBASE por vendedor (contém, case-insensitive) e período."""
    result = df.copy()

    if "data_pagto" in result.columns:
        result = result[
            result["data_pagto"].notna()
            & (result["data_pagto"] >= pd.Timestamp(data_ini))
            & (result["data_pagto"] <= pd.Timestamp(data_fim))
        ]

    if vendedor and "vendedor" in result.columns:
        vup    = vendedor.upper().strip()
        result = result[
            result["vendedor"].fillna("").str.upper().str.contains(vup, regex=False)
        ]

    return result.reset_index(drop=True)


# ─── Camada de Cálculo de Comissão ────────────────────────────────────────────

def calc_commission(df: pd.DataFrame) -> dict:
    """
    Calcula comissão por produto a partir de um DataFrame já filtrado.

    Retorna dict com:
      por_produto     → list[dict]  (categoria, produto, qtd, unit, total)
      total_contratos → int
      total_comissao  → float
      total_retorno   → float
      total_produtos  → int
    """
    resultados: list[dict] = []

    for col_key, col_label in PRODUCT_COLS.items():
        if col_key not in df.columns:
            continue

        serie = df[col_key].copy()

        # Máscara de valores preenchidos
        validos = serie.apply(
            lambda x: bool(x)
            and not (isinstance(x, float) and pd.isna(x))
            and str(x).strip() not in ("", "0", "0.0")
        )
        if not validos.any():
            continue

        serie_valida = serie[validos]

        for prod_val, grupo in serie_valida.groupby(serie_valida):
            prod_str = str(prod_val).strip()
            if not prod_str:
                continue
            valor_unit = _commission(prod_str)
            qtd        = len(grupo)
            resultados.append({
                "categoria": col_label,
                "produto":   prod_str,
                "qtd":       qtd,
                "unit":      valor_unit,
                "total":     qtd * valor_unit,
            })

    # Ordena por comissão total decrescente
    resultados.sort(key=lambda x: x["total"], reverse=True)

    total_retorno = 0.0
    if "retorno" in df.columns:
        s = pd.to_numeric(df["retorno"], errors="coerce").sum()
        total_retorno = float(s) if not pd.isna(s) else 0.0

    total_comissao = sum(r["total"] for r in resultados)

    return {
        "por_produto":      resultados,
        "total_contratos":  len(df),
        "total_produtos":   sum(r["qtd"] for r in resultados),
        "total_comissao":   total_comissao,           # só produtos
        "total_retorno":    total_retorno,             # só retorno de financiamento
        "total_bruto":      total_comissao + total_retorno,  # produtos + retorno
    }


# ─── Camada de Interface ──────────────────────────────────────────────────────

_VW_BLUE = "#001E50"
_PALETTE = ["#001E50","#0040B0","#00B0F0","#1EBE5D",
            "#FF6B35","#9B59B6","#F39C12","#E74C3C"]


def _render_kpis(summary: dict) -> None:
    # ── Linha 1: quadro financeiro principal ──────────────────────────────────
    st.markdown("""
    <style>
    .comm-card {
        background: #f8faff;
        border: 1.5px solid #dde3ef;
        border-radius: 10px;
        padding: 1.1rem 1.4rem;
        text-align: center;
    }
    .comm-card .label {
        color: #6b7280;
        font-size: 0.78rem;
        font-weight: 500;
        letter-spacing: 0.4px;
        text-transform: uppercase;
        margin-bottom: 6px;
    }
    .comm-card .value {
        color: #001e50;
        font-size: 1.45rem;
        font-weight: 700;
        letter-spacing: -0.5px;
    }
    .comm-card.highlight {
        background: linear-gradient(135deg, #001e50 0%, #0040b0 100%);
        border-color: #001e50;
    }
    .comm-card.highlight .label { color: rgba(255,255,255,0.7); }
    .comm-card.highlight .value { color: #ffffff; font-size: 1.6rem; }
    </style>
    """, unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(f"""
        <div class="comm-card">
            <div class="label">💼 Comissão de Produtos</div>
            <div class="value">R$ {summary['total_comissao']:,.2f}</div>
        </div>""", unsafe_allow_html=True)
    with c2:
        st.markdown(f"""
        <div class="comm-card">
            <div class="label">📈 Retorno de Financiamento</div>
            <div class="value">R$ {summary['total_retorno']:,.2f}</div>
        </div>""", unsafe_allow_html=True)
    with c3:
        st.markdown(f"""
        <div class="comm-card highlight">
            <div class="label">⭐ Total Bruto (Produtos + Retorno)</div>
            <div class="value">R$ {summary['total_bruto']:,.2f}</div>
        </div>""", unsafe_allow_html=True)

    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

    # ── Linha 2: contadores operacionais ─────────────────────────────────────
    with st.container(border=True):
        cc1, cc2 = st.columns(2)
        cc1.metric("📄 Contratos no período", f"{summary['total_contratos']:,}")
        cc2.metric("📦 Produtos produzidos",  f"{summary['total_produtos']:,}")


def _render_table(summary: dict) -> None:
    rows = summary["por_produto"]
    if not rows:
        st.info("ℹ️ Nenhum produto com comissão mapeada encontrado no período.")
        return

    df = pd.DataFrame(rows)

    # Tabela formatada
    display = pd.DataFrame({
        "Categoria":      df["categoria"],
        "Produto":        df["produto"],
        "Qtd":            df["qtd"],
        "Comissão Unit.": df["unit"].apply(lambda x: f"R$ {x:,.2f}"),
        "Total":          df["total"].apply(lambda x: f"R$ {x:,.2f}"),
    })
    st.dataframe(display, use_container_width=True, hide_index=True)

    # Totalizador
    t1, t2, t3 = st.columns(3)
    t1.metric("Tipos distintos",  len(df))
    t2.metric("Total de itens",   f"{int(df['qtd'].sum()):,}")
    t3.metric("Total comissão",   f"R$ {df['total'].sum():,.2f}")


def _render_charts(summary: dict) -> None:
    rows = summary["por_produto"]
    if not rows:
        return

    df = pd.DataFrame(rows)

    col_l, col_r = st.columns(2)

    with col_l, st.container(border=True):
        st.markdown("**Comissão por Produto (R$)**")
        fig = px.bar(
            df.sort_values("total"),
            x="total", y="produto", orientation="h",
            color="categoria",
            color_discrete_sequence=_PALETTE,
            labels={"total": "R$", "produto": "", "categoria": ""},
            text=df.sort_values("total")["total"].apply(lambda x: f"R$ {x:,.0f}"),
        )
        fig.update_traces(textposition="outside")
        fig.update_layout(
            template="plotly_white", height=max(300, len(df) * 36),
            margin=dict(l=10, r=80, t=20, b=10),
            showlegend=True, legend=dict(orientation="h", y=-0.15),
        )
        st.plotly_chart(fig, use_container_width=True)

    with col_r, st.container(border=True):
        st.markdown("**Quantidade por Produto**")
        fig2 = px.bar(
            df.sort_values("qtd", ascending=False),
            x="produto", y="qtd",
            color="categoria",
            color_discrete_sequence=_PALETTE,
            labels={"qtd": "Qtd", "produto": "", "categoria": ""},
            text="qtd",
        )
        fig2.update_traces(textposition="outside")
        fig2.update_layout(
            template="plotly_white", height=max(300, len(df) * 36),
            margin=dict(l=10, r=10, t=20, b=60),
            showlegend=False, xaxis_tickangle=-35,
        )
        st.plotly_chart(fig2, use_container_width=True)

    # Donut — participação por categoria
    if len(df["categoria"].unique()) > 1:
        cat_df = df.groupby("categoria", as_index=False)["total"].sum()
        with st.container(border=True):
            st.markdown("**Participação por Categoria**")
            col_a, col_b = st.columns([1, 2])
            with col_a:
                fig3 = go.Figure(go.Pie(
                    labels=cat_df["categoria"],
                    values=cat_df["total"],
                    hole=0.5,
                    marker=dict(colors=_PALETTE[:len(cat_df)]),
                    textinfo="label+percent",
                ))
                fig3.update_layout(
                    template="plotly_white", height=260,
                    margin=dict(l=10, r=10, t=20, b=10),
                    showlegend=False,
                )
                st.plotly_chart(fig3, use_container_width=True)
            with col_b:
                cat_display = cat_df.copy()
                cat_display["Total"] = cat_display["total"].apply(lambda x: f"R$ {x:,.2f}")
                cat_display["Part. %"] = (
                    cat_display["total"] / cat_display["total"].sum() * 100
                ).apply(lambda x: f"{x:.1f}%")
                st.dataframe(
                    cat_display[["categoria", "Total", "Part. %"]].rename(
                        columns={"categoria": "Categoria"}
                    ),
                    use_container_width=True,
                    hide_index=True,
                )


def _render_contratos(df_filtrado: pd.DataFrame) -> None:
    """Tabela dos contratos individuais do período filtrado."""
    cols_show = [c for c in ["proposta", "data_pagto", "cliente", "cpf_cnpj",
                              "spf", "app", "gap", "franquia", "ge", "protege",
                              "retorno", "pontos"] if c in df_filtrado.columns]
    if not cols_show:
        return

    display = df_filtrado[cols_show].copy()
    if "data_pagto" in display.columns:
        display["data_pagto"] = display["data_pagto"].dt.strftime("%d/%m/%Y")
    if "retorno" in display.columns:
        display["retorno"] = display["retorno"].apply(
            lambda x: f"R$ {x:,.2f}" if not pd.isna(x) else ""
        )

    display.columns = [c.replace("_", " ").upper() for c in display.columns]
    st.dataframe(display, use_container_width=True, hide_index=True)


# ─── Entry point ──────────────────────────────────────────────────────────────

def render_comissao(client_id: str = "", sharing_url: str = "") -> None:
    """Ponto de entrada da aba Comissão — chamado pelo app.py."""
    st.markdown("""
    <div class="section-title">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none"
             stroke="#001e50" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="12" y1="1" x2="12" y2="23"/>
            <path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>
        </svg>
        <span>Comissão de Vendedores</span>
    </div>
    """, unsafe_allow_html=True)

    # ── Pré-requisitos ─────────────────────────────────────────────────────────
    if st.session_state.get("_msal_auth_status") != "authenticated":
        st.info("🔑 Faça login com sua conta Microsoft nas **Configurações** para usar esta funcionalidade.")
        return
    if not sharing_url:
        st.info("⚙️ Configure o **Link do Excel — Dashboard** nas **Configurações**. "
                "O BIGBASE deve estar nesse arquivo.")
        return

    # ── Carrega BIGBASE ────────────────────────────────────────────────────────
    with st.spinner("⏳ Carregando BIGBASE…"):
        df_base, err = load_bigbase(client_id, sharing_url)

    if err:
        st.error(err)
        col_retry, _ = st.columns([1, 4])
        with col_retry:
            if st.button("🔄 Tentar novamente", key="comm_retry"):
                st.session_state.pop("_comm_df_bigbase", None)
                st.session_state.pop("_comm_ts_bigbase", None)
                st.rerun()
        return

    if df_base is None or df_base.empty:
        st.warning("Nenhum dado encontrado na aba BIGBASE.")
        return

    ts_base = st.session_state.get("_comm_ts_bigbase")
    st.caption(
        f"BIGBASE · {len(df_base):,} registros"
        + (f" · carregado às {datetime.fromtimestamp(ts_base).strftime('%H:%M:%S')}" if ts_base else "")
    )

    # ── Filtros ────────────────────────────────────────────────────────────────
    with st.container(border=True):
        col_d1, col_d2, col_vend, col_btn = st.columns([2, 2, 4, 1])

        with col_d1:
            data_ini = st.date_input(
                "Data inicial",
                value=date.today().replace(day=1),
                key="comm_data_ini",
                format="DD/MM/YYYY",
            )
        with col_d2:
            data_fim = st.date_input(
                "Data final",
                value=date.today(),
                key="comm_data_fim",
                format="DD/MM/YYYY",
            )
        with col_vend:
            vendedores_disp = (
                sorted(df_base["vendedor"].dropna().str.strip().unique())
                if "vendedor" in df_base.columns else []
            )
            vendedor_sel = st.selectbox(
                "Vendedor",
                options=[""] + vendedores_disp,
                format_func=lambda x: "Selecione um vendedor..." if x == "" else x,
                key="comm_vendedor",
            )
        with col_btn:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            consultar = st.button(
                "🔍 Consultar",
                type="primary",
                use_container_width=True,
                key="comm_consultar",
            )

    # ── Valida e executa consulta ──────────────────────────────────────────────
    if consultar:
        if not vendedor_sel:
            st.warning("⚠️ Selecione um vendedor para consultar.")
            return
        if data_ini > data_fim:
            st.warning("⚠️ A data inicial deve ser anterior ou igual à data final.")
            return

        df_filtrado = filter_records(df_base, vendedor_sel, data_ini, data_fim)

        if df_filtrado.empty:
            st.warning(
                f"⚠️ Nenhum registro encontrado para **{vendedor_sel}** "
                f"entre **{data_ini.strftime('%d/%m/%Y')}** e "
                f"**{data_fim.strftime('%d/%m/%Y')}**."
            )
            st.session_state.pop("comm_resultado", None)
            return

        summary = calc_commission(df_filtrado)
        summary["vendedor"]     = vendedor_sel
        summary["data_ini"]     = data_ini
        summary["data_fim"]     = data_fim
        summary["df_filtrado"]  = df_filtrado
        st.session_state["comm_resultado"] = summary

    # ── Exibe resultado ────────────────────────────────────────────────────────
    resultado = st.session_state.get("comm_resultado")
    if not resultado:
        st.info("Selecione o período e o vendedor, depois clique em **🔍 Consultar**.")
        return

    st.divider()

    # Cabeçalho do resultado
    st.markdown(
        f"### {resultado['vendedor']} &nbsp;·&nbsp; "
        f"{resultado['data_ini'].strftime('%d/%m/%Y')} → "
        f"{resultado['data_fim'].strftime('%d/%m/%Y')}"
    )

    # KPIs
    _render_kpis(resultado)

    # Abas internas: Detalhamento | Contratos
    sub_det, sub_con = st.tabs(["📋 Detalhamento por Produto", "📄 Contratos do Período"])

    with sub_det:
        st.markdown("#### Comissão por produto")
        _render_table(resultado)
        st.divider()
        st.markdown("#### Gráficos de produção")
        _render_charts(resultado)

    with sub_con:
        st.markdown(
            f"**{resultado['total_contratos']} contrato(s)** no período filtrado"
        )
        _render_contratos(resultado["df_filtrado"])

    # Botões de ação
    col_lim, col_att, _ = st.columns([1, 1, 4])
    with col_lim:
        if st.button("🗑️ Limpar", key="comm_clear", use_container_width=True):
            st.session_state.pop("comm_resultado", None)
            st.rerun()
    with col_att:
        if st.button("🔄 Recarregar base", key="comm_reload", use_container_width=True):
            st.session_state.pop("_comm_df_bigbase", None)
            st.session_state.pop("_comm_ts_bigbase", None)
            st.session_state.pop("comm_resultado", None)
            st.rerun()
