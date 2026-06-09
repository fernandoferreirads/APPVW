# CLAUDE.md — Guia do Projeto VW Extractor

## Visão Geral
App Streamlit em `extratorvw.streamlit.app` que lê dados do Excel Online via Microsoft Graph API.
Repositório GitHub: `fernandoferreirads/APPVW` (branch `main` → auto-deploy no Streamlit Cloud).

---

## Estrutura de Arquivos
```
app.py          — ponto de entrada, abas, autenticação MSAL
comissao.py     — lógica da aba Comissão + load_bigbase() (cache compartilhado)
graficos.py     — aba Gráficos: todos os gráficos nativos Plotly
dashboard.py    — aba Dashboard
requirements.txt
.streamlit/config.toml
```

---

## BIGBASE — Mapeamento de Colunas (`_BIGBASE_SPEC` em comissao.py)

| Nome interno | Aliases (cabeçalho Excel) | Posição (0-idx) | Coluna Excel |
|---|---|---|---|
| `proposta` | PROPOSTA, N PROPOSTA | 0 | A |
| `equipe` | EQUIPE, LOJA | 1 | B |
| `data_pagto` | D. PAGTO, DATA PAGTO | 6 | G |
| `spf` | SPF, SEGURO PROT FINANCEIRA | 12 | M |
| `app` | APP, ACID PESSOAIS | 13 | N |
| `gap` | GAP | 14 | O |
| `franquia` | FRANQ, FRANQUIA | 15 | P |
| `rev_plan` | REV PLAN, REVISAO | 16 | Q |
| `ge` | GE, GARANTIA ESTENDIDA | 17 | R |
| `protege` | PROTEGE, VW PROTEGE | 18 | S |
| `tipo_veiculo` | N/S, TIPO VEICULO | 21 | V |
| `sempre_novo` | SEMPRE NV, SEMPRE NOVO | 22 | W |
| `vendedor` | VENDEDOR, CONSULTOR | 24 | Y |
| `retorno` | RETORNO, RETORNO F&I | 25 | Z |

---

## Como Adicionar um Novo Gráfico na Aba Gráficos

### Passo 1 — Identificar a coluna no BIGBASE
- Ver tabela acima. Nome interno = nome da coluna no DataFrame carregado.
- Se o gráfico filtra um valor específico (ex: `"SEGURO VW"`), usar `filtro=`.

### Passo 2 — Escolher o tipo de gráfico

**Tipo A — Barras + Linha % AAK (mais comum)**
Usado por: GARANTIAS, SEGUROS, PROTEGE.
```python
def _chart_nome(df):
    return _chart_produto(df, col="nome_coluna", titulo="NOME", y_min_floor=50)
```
- `y_min_floor`: piso do eixo Y esquerdo (SEGUROS=200, PROTEGE=50, padrão=50)
- `filtro="TEXTO"`: filtra só as linhas que contêm esse texto na coluna (case-insensitive)

**Tipo B — Barras Agrupadas (dois grupos)**
Usado por: SPF (Total vs Plus).
Copiar `_chart_spf` como base e adaptar colunas + filtros.

**Tipo C — Barras Empilhadas**
Usado por: CONTRATOS (NV vs SN).
Copiar `_chart_contratos_nv_sn` como base.

### Passo 3 — Adicionar a função em `graficos.py`

Adicionar ANTES do bloco `# ─── Render principal`:

```python
# ─── Gráfico N — Nome ─────────────────────────────────────────────────────
def _chart_nome(df: pd.DataFrame) -> tuple[go.Figure, pd.DataFrame]:
    """Descrição."""
    return _chart_produto(df, col="coluna", titulo="NOME", y_min_floor=50)
```

### Passo 4 — Adicionar o bloco de renderização em `render_graficos()`

Adicionar no final da função, ANTES do último `except`:

```python
    st.markdown("<div style='height:1.5rem'></div>", unsafe_allow_html=True)

    # ═══ Gráfico N — Nome ════════════════════════════════════════════════════
    try:
        with st.container(border=True):
            st.markdown(
                "<p style='font-size:1rem;font-weight:700;color:#001e50;"
                "text-align:center;margin-bottom:2px'>NOME</p>",
                unsafe_allow_html=True,
            )
            st.caption("Descrição do gráfico")

            figN, tblN = _chart_nome(df)
            st.plotly_chart(figN, use_container_width=True)
            if not tblN.empty:
                st.dataframe(tblN, use_container_width=True, hide_index=True,
                             column_config={"": st.column_config.TextColumn("", width="medium")})
    except Exception as _e:
        st.error(f"❌ Erro ao renderizar NOME: {_e}")
        import traceback
        st.code(traceback.format_exc(), language="python")
```

### Passo 5 — Commit e push

```bash
git add graficos.py
git commit -m "feat: adiciona gráfico NOME"
git push origin main
```
Streamlit Cloud faz deploy automático (~1 min). Clicar em 🔄 para recarregar BIGBASE.

---

## Regras Críticas de `graficos.py`

### DataFrames das Tabelas — SEMPRE usar `_str_df()`
```python
df_tabela = _str_df(pd.DataFrame({
    "": ["Linha1", "Linha2"],
    **{label_tabela[i]: [str(val1[i]), f"{val2[i]:.0f}%"] for i in range(len(label_tabela))},
}))
```
**Por quê:** o pyarrow (usado pelo Streamlit) infere `int64` quando vê strings numéricas como `"17"`.
`_str_df()` força `pd.StringDtype()` em todas as colunas, bloqueando a inferência.

### Labels com `\n` — separar label de gráfico vs label de tabela
```python
labels.append("TENDÊNCIA\nM.A")                          # gráfico Plotly (OK)
label_tabela = [lbl.replace("\n", " ") for lbl in labels] # tabela pandas (sem \n)
```
**Por quê:** `\n` em nome de coluna do DataFrame crasha o `st.dataframe`.

### Cache do BIGBASE — compartilhado entre abas
- `load_bigbase()` em `comissao.py` usa `st.session_state["_comm_df_bigbase"]`
- `graficos.py` importa e chama `load_bigbase()` → sem double API call
- Botão 🔄 limpa: `st.session_state.pop("_comm_df_bigbase", None)`

---

## Gráficos Implementados (aba 📈 Gráficos)

| # | Título | Tipo | Coluna BIGBASE | Filtro | y_min_floor |
|---|---|---|---|---|---|
| 1 | CONTRATOS | Barras empilhadas NV/SN | `tipo_veiculo` | N ou S | — |
| 2 | GARANTIAS | Barras + linha % AAK | `ge` | — | 50 |
| 3 | SEGUROS | Barras + linha % AAK | `app` | `"Seguro VW"` | 200 |
| 4 | SPF | Barras agrupadas Total/Plus | `spf` | `"PLUS"` para Plus | 100 |
| 5 | PROTEGE | Barras + linha % AAK | `protege` | — | 50 |

---

## Paleta de Cores
```python
_AZUL_NV    = "#4472C4"   # azul Excel — barras principais
_LARANJA_SN = "#ED7D31"   # laranja Excel — SN / linha AAK / barra tendência
_VW_BLUE    = "#001E50"   # azul VW — títulos
```

---

## Períodos dos Gráficos
- `_meses_range(n=6)` → n-1 meses completos + mês vigente (usado no CONTRATOS)
- `_meses_completos(n=7)` → últimos n meses completos sem o mês vigente (usado nos demais)
- **TENDÊNCIA M.A** → média dos últimos 3 meses completos

---

## Variáveis de Ambiente / Configuração
- `az_client_id` → ID do app Azure (autenticação MSAL)
- `dash_url` → link compartilhado do Excel no SharePoint/OneDrive
- Configurados nas **Configurações** do app (sidebar)
