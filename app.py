import streamlit as st
import json
import os
import re
from datetime import datetime
from difflib import get_close_matches

import pandas as pd
from google import genai
from google.genai import types
from google.oauth2 import service_account
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

# ─── Mapeamentos ───────────────────────────────────────────────────────────────

MESES_PT = {
    1: "JANEIRO", 2: "FEVEREIRO", 3: "MARÇO", 4: "ABRIL",
    5: "MAIO", 6: "JUNHO", 7: "JULHO", 8: "AGOSTO",
    9: "SETEMBRO", 10: "OUTUBRO", 11: "NOVEMBRO", 12: "DEZEMBRO",
}

VENDEDOR_EQUIPE = {
    "ALBERT ALVES TORRES": "S.I.A",
    "ALEX MOREIRA SOUZA": "CEI VW",
    "ALEXANDRE HENRIQUE M": "FORD EPIA",
    "AMAURI RODRIGUES DOS SANTOS": "NÃO PRESENCIAL",
    "ANDRE LUIZ FONTANA DE PAIVA": "TAG VW",
    "ANTONINO VITORINO DE SOUSA": "S.I.A",
    "BRENO FELIPE CAVALCANTE": "NÃO PRESENCIAL",
    "BRUNO FREITAS OLIVEIRA": "TAG VW",
    "CARLUCIA SANTOS FERN": "FORD EPIA",
    "CATARINA GUEDES": "S.I.A",
    "CLAUDIO HENRIQUE": "S.I.A",
    "CLINSMAN WILKE DE VASCONCELOS": "S.I.A",
    "DANILO DA ROCHA NEVES": "NÃO PRESENCIAL",
    "DANUBIA CANUTO": "TAG VW",
    "DIOGO ELLER DA SILVA NASCIMENTO": "TAG VW",
    "DOUGLAS OLIVEIRA DE MORAIS": "S.I.A",
    "EDUARDO ALVES ROQUE": "CEI VW",
    "EDUARDO DOS SANTOS CAMPOS": "TAG VW",
    "ELCIO GUSTAVO R MENDES": "FORD EPIA",
    "EUCARLITO GEOVANI DA SILVA": "FORD TAG",
    "EVERTON ANICESIO VELOSO": "MM CEI",
    "FABIANO CARVALHO DOS": "TAG VW",
    "FABIO RODRIGUES SILVA": "FORD EPIA",
    "FABIO TAVARES": "FORD TAG",
    "FABRICIO SILVA DE MORAIS": "TAG VW",
    "FERNANDO BARBOSA ALBUQUERQUE": "FORD TAG",
    "FLAVIO PEREIRA DE SOUZA": "NÃO PRESENCIAL",
    "GABRIEL DA SILVA ALMEIDA BARBOSA": "S.I.A",
    "GRAZIELLE SANTOS LIMA": "S.I.A",
    "IANCA": "FORD EPIA",
    "IVANDA FERREIRA PINTO": "TAG VW",
    "JAME WILLIAMS": "NÃO PRESENCIAL",
    "JOAB SANTIAGO": "TAG VW",
    "JOAO MARCOS": "CEI VW",
    "JOSE PEREIRA NEVES": "S.I.A",
    "LARISSA OLIVEIRA": "S.I.A",
    "LEANDRO MATOS CABRAL": "S.I.A",
    "LEONARDO PEREIRA LIMA MORAIS": "FORD TAG",
    "LILIAN AMARAL": "FORD TAG",
    "LUCAS DOS SANTOS LOBO": "CEI VW",
    "MARCELO FERREIRA BOMFIN": "TAG VW",
    "MARCUS VINICIUS RODRIGUES LOPES": "S.I.A",
    "MICHELL GONÇALO": "TAG VW",
    "MOISES DA SILVA LIRA": "FORD EPIA",
    "NEY SANTOS CERQUEIRA": "S.I.A",
    "PEDRO HENRIQUE SOARES DUTRA": "S.I.A",
    "RENATO MENDES": "S.I.A",
    "RODRIGO ALESSANDRO": "FORD EPIA",
    "RODRIGO DA SILVA PAZ": "NÃO PRESENCIAL",
    "RODRIGO SANTANA": "S.I.A",
    "SABRINA ALMEIDA VIANA": "S.I.A",
    "THIAGO BATISTA GOMES": "S.I.A",
    "TANIZZE BATISTA": "FORD EPIA",
    "THIAGO GOMES DA SILVA": "CEI VW",
    "THOMAS RAVELLI": "S.I.A",
    "UEVERSON DENIS GERMANO SANTANA": "FORD EPIA",
    "UILLIAN MARRA SILVA": "FORD EPIA",
    "WILCK JORGE COSTA MEDEIROS": "FORD TAG",
    "WILLIAM DA SILVA QUEIROZ": "FORD TAG",
    "YNGRID KAREN": "S.I.A",
}

PONTOS_PRODUTO = {
    "GE 1": 0.50,
    "GE 2": 1.00,
    "GE 4": 1.25,
    "SPF BASICO": 0.75,
    "SPF NORMAL": 1.00,
    "SPF PLUS": 1.50,
    "AP": 0.15,
    "GAP": 0.25,
    "FRANQUIA": 0.25,
    "PROTEGE BAS 24": 0.25,
    "PROTEGE BAS 36": 0.35,
    "PROTEGE PLUS 24": 0.50,
    "PROTEGE PLUS 36": 0.60,
}

EXTRACTION_PROMPT = """Você é um sistema de extração de dados de contratos CCB do Banco Volkswagen.
Extraia os campos abaixo do PDF e retorne APENAS um objeto JSON válido — sem markdown, sem explicação.

REGRAS DE EXTRAÇÃO:

1. proposta: número de 8 dígitos da proposta (área do código de barras, canto inferior esquerdo da página 1).
   Exemplo: "14469703". NÃO inclua sufixos como "V.002".

2. vendedor: nome IMPRESSO (não assinatura) abaixo de "ASSINATURA DO RESPONSÁVEL PELA ABERTURA DO CADASTRO"
   na página "FICHA CADASTRAL - PESSOA FÍSICA". Retorne em maiúsculas.

3. cpf_cnpj: em "I- EMITENTE", campo CPF/CNPJ (lado direito), com pontuação original (pontos, traços, barras).
   ATENÇÃO: copie o número COMPLETO incluindo todos os dígitos. CPF tem 11 dígitos (ex: 830.606.501-87). Não omita nenhum dígito do início.

4. cliente: em "I- EMITENTE", campo "Nome / Razão Social". Nome completo.

5. valor_veiculo: em "QUADRO 5 – ESPECIFICAÇÕES GERAIS DO CRÉDITO CONSOLIDADAS",
   campo "Valor do Veículo". Retorne como número float (ex: 117000.00). Sem símbolo de moeda.

6. entrada: em "QUADRO 5", campo "Valor da Entrada". Retorne como float.

7. spf: em "QUADRO 4", linha "Seguro de Proteção Financeira":
   - Não contratado → null
   - Contratado → localize a página "SEGURO DE PROTEÇÃO FINANCEIRA + PERDA DE RENDA ___"
     A palavra após RENDA indica o tipo: PLUS, NORMAL ou BÁSICO/BASICO.
   - Retorne exatamente: "SPF PLUS", "SPF NORMAL" ou "SPF BASICO". Null se não contratado.

8. app: "Acidentes Pessoais" no QUADRO 4 — contratado → "AP", senão null.

9. gap: "GAP" no QUADRO 4 — contratado → "GAP", senão null.

10. franquia: "Seguro Franquia" no QUADRO 4 — contratado → "FRANQUIA", senão null.

11. ge: "Garantia Estendida / Garantia Mecânica" no QUADRO 4:
    - Não contratado → null
    - Contratado: verifique o Valor do Prêmio daquela linha:
      * valor < 1100 → "GE 1"
      * 1100 ≤ valor ≤ 2000 → "GE 2"
      * valor > 2000 → "GE 4"
    IMPORTANTE: GE 3 NÃO EXISTE. Nunca retorne "GE 3".

12. protege: no QUADRO 3 (ACESSÓRIOS/PEÇAS/SERVIÇOS), produto PROTEGE/proteção veicular:
    - Não contratado → null
    - Contratado, verifique o valor: 699 → "PROTEGE BAS 24" | 999 → "PROTEGE BAS 36"
      1399 → "PROTEGE PLUS 24" | 1699 → "PROTEGE PLUS 36"

13. prazo: em "QUADRO 5", "Prazo da CÉDULA" em Meses. Retorne como inteiro.

14. taxa: em "QUADRO 1 - VEÍCULO FINANCIADO", "Taxa de juros ao mês prefixados e capitalizados".
    Retorne como float com ponto decimal (ex: 0.99 para 0,99%).

15. tipo_veiculo: em "QUADRO 1", qual opção está marcada:
    Novo(N) → "N" | Semi-Novo(SN) → "S" | Usado(U) → "U"

16. sempre_novo: em "QUADRO 7 – FLUXO DE PRESTAÇÕES PERIÓDICAS E INTERMEDIÁRIAS":
    Se a última parcela (número mais alto) tiver valor significativamente maior que as demais → "S"
    Se todas as parcelas forem iguais ou aproximadamente iguais → "N"

Retorne APENAS este JSON:
{
  "proposta": "",
  "vendedor": "",
  "cpf_cnpj": "",
  "cliente": "",
  "valor_veiculo": 0.0,
  "entrada": 0.0,
  "spf": null,
  "app": null,
  "gap": null,
  "franquia": null,
  "ge": null,
  "protege": null,
  "prazo": 0,
  "taxa": 0.0,
  "tipo_veiculo": "N",
  "sempre_novo": "N"
}"""


# ─── Regras de Negócio ─────────────────────────────────────────────────────────

def lookup_vendedor(nome: str) -> str:
    nome_up = nome.upper().strip()
    if nome_up in VENDEDOR_EQUIPE:
        return VENDEDOR_EQUIPE[nome_up]
    matches = get_close_matches(nome_up, VENDEDOR_EQUIPE.keys(), n=1, cutoff=0.6)
    if matches:
        return VENDEDOR_EQUIPE[matches[0]]
    for chave, valor in VENDEDOR_EQUIPE.items():
        if chave in nome_up or nome_up in chave:
            return valor
    return "NÃO IDENTIFICADO"


def calcular_peso(tipo: str, taxa: float) -> float:
    if tipo == "S":
        return 0.75
    if taxa <= 1.0:
        return 0.15
    if taxa <= 1.70:
        return 0.50
    if taxa <= 1.99:
        return 0.75
    return 1.00


def calcular_pontos(raw: dict) -> float:
    total = 0.0
    for campo in ["spf", "app", "gap", "franquia", "ge", "protege"]:
        prod = raw.get(campo)
        if prod:
            total += PONTOS_PRODUTO.get(prod, 0.0)
    return round(total, 2)


def aplicar_regras(raw: dict, data_upload: str) -> dict:
    veiculo = raw["valor_veiculo"]
    entrada = raw["entrada"]
    taxa = raw["taxa"]
    tipo = raw["tipo_veiculo"]
    vendedor = raw["vendedor"]

    equipe = lookup_vendedor(vendedor)
    valor_financiado = round(veiculo - entrada, 2)
    peso = calcular_peso(tipo, taxa)
    retorno = round(valor_financiado * 0.004, 2)
    pontos = calcular_pontos(raw)

    ge = raw.get("ge") or ""
    ge_pts = PONTOS_PRODUTO.get(ge, "") if ge else ""
    taxa_str = f"{taxa:.2f}".replace(".", ",") + "%"

    return {
        "proposta":             raw["proposta"],
        "equipe":               equipe,
        "data_pagto":           data_upload,
        "cpf_cnpj":             raw["cpf_cnpj"],
        "cliente":              raw["cliente"],
        "valor_veiculo":        veiculo,
        "entrada":              entrada,
        "valor_financiado":     valor_financiado,
        "spf":                  raw.get("spf") or "",
        "app":                  raw.get("app") or "",
        "gap":                  raw.get("gap") or "",
        "franquia":             raw.get("franquia") or "",
        "ge":                   ge,
        "protege":              raw.get("protege") or "",
        "prazo":                raw["prazo"],
        "taxa":                 taxa_str,
        "tipo_veiculo":         tipo,
        "sempre_novo":          raw["sempre_novo"],
        "peso_tabela":          peso,
        "vendedor":             vendedor,
        "retorno":              retorno,
        "pontos":               pontos,
        "correspondencias_ge":  ge,
        "correspondencias_pts": ge_pts,
        "loja":                 equipe,
    }


def para_linha_sheets(d: dict) -> list:
    return [
        d["proposta"],              # A  - PROPOSTA
        d["equipe"],                # B  - EQUIPE
        d["data_pagto"],            # C  - D. PAGTO
        d["cpf_cnpj"],              # D  - CPF/CNPJ
        d["cliente"],               # E  - CLIENTE
        d["valor_veiculo"],         # F  - VALOR DO VEICULO
        d["entrada"],               # G  - ENTRADA
        d["valor_financiado"],      # H  - VALOR FINANCIADO
        d["spf"],                   # I  - SPF
        d["app"],                   # J  - APP
        d["gap"],                   # K  - GAP
        d["franquia"],              # L  - FRANQ
        "",                         # M  - REV PLAN (desconsiderada)
        d["ge"],                    # N  - GE
        d["protege"],               # O  - PROTEGE
        d["prazo"],                 # P  - PRAZO
        d["taxa"],                  # Q  - TAXA
        d["tipo_veiculo"],          # R  - N/S
        d["sempre_novo"],           # S  - SEMPRE NV
        d["peso_tabela"],           # T  - Peso Tabela
        d["vendedor"],              # U  - VENDEDOR
        d["retorno"],               # V  - RETORNO3
        d["pontos"],                # W  - PONTOS POR CONTRATOS
        "",                         # X  - CONTRATOS SEM PONTOS (desconsiderada)
        d["correspondencias_ge"],   # Y  - CORRESPONDÊNCIAS (tipo GE)
        d["correspondencias_pts"],  # Z  - CORRESPONDÊNCIAS (pontos GE)
        "",                         # AA - vazio
        d["loja"],                  # AB - LOJA
    ]


# ─── Extração via Gemini API ───────────────────────────────────────────────────

def extrair_contrato(pdf_bytes: bytes, api_key: str) -> dict:
    client = genai.Client(api_key=api_key)

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
            EXTRACTION_PROMPT,
        ],
    )

    texto = response.text.strip()
    texto = re.sub(r"^```(?:json)?\s*", "", texto)
    texto = re.sub(r"\s*```$", "", texto).strip()
    return json.loads(texto)


# ─── Google Sheets ─────────────────────────────────────────────────────────────

def get_sheets_service(creds_path: str):
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    # Streamlit Cloud: lê credenciais dos secrets
    try:
        if "gcp_service_account" in st.secrets:
            creds = service_account.Credentials.from_service_account_info(
                dict(st.secrets["gcp_service_account"]),
                scopes=scopes,
            )
            return build("sheets", "v4", credentials=creds)
    except Exception:
        pass
    # Local: lê do arquivo JSON
    creds = service_account.Credentials.from_service_account_file(
        creds_path, scopes=scopes,
    )
    return build("sheets", "v4", credentials=creds)


def nome_aba_atual() -> str:
    now = datetime.now()
    return f"{MESES_PT[now.month]} {now.year}"


def inserir_linhas_sheets(linhas: list, spreadsheet_id: str, creds_path: str) -> int:
    service = get_sheets_service(creds_path)
    aba = nome_aba_atual()

    resultado = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"'{aba}'!A:A",
    ).execute()
    proxima_linha = len(resultado.get("values", [])) + 1

    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{aba}'!A{proxima_linha}",
        valueInputOption="USER_ENTERED",
        body={"values": linhas},
    ).execute()
    return proxima_linha


# ─── Interface ─────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Extrator VW — Plano de Pagamentos",
    page_icon="🚗",
    layout="wide",
)

st.title("🚗 Extrator de Contratos VW")
st.caption("Lê contratos de financiamento em PDF e insere automaticamente no Google Sheets")

# ── Sidebar — Configurações ──────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Configurações")

    # Lê valores do .env local ou dos secrets do Streamlit Cloud
    _gemini_default = os.getenv("GEMINI_API_KEY") or st.secrets.get("GEMINI_API_KEY", "")
    _sid_default    = os.getenv("SPREADSHEET_ID") or st.secrets.get("SPREADSHEET_ID", "")

    api_key = st.text_input(
        "Gemini API Key",
        value=_gemini_default,
        type="password",
        help="Chave gratuita em: aistudio.google.com → Get API Key",
    )
    _sid_raw = st.text_input(
        "ID do Google Sheets",
        value=_sid_default,
        help="ID da planilha na URL: docs.google.com/spreadsheets/d/[ID]/edit",
    )
    # Aceita URL completa ou só o ID — extrai apenas o ID
    _sid_match = re.search(r'spreadsheets/d/([a-zA-Z0-9_-]+)', _sid_raw)
    spreadsheet_id = _sid_match.group(1) if _sid_match else _sid_raw.strip()

    creds_path_raw = st.text_input(
        "Credenciais Google (JSON)",
        value=os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials/service_account.json"),
        help="Caminho para o arquivo JSON da conta de serviço",
    )
    # Resolve caminho relativo à pasta do app.py
    _app_dir = os.path.dirname(os.path.abspath(__file__))
    creds_path = (
        creds_path_raw if os.path.isabs(creds_path_raw)
        else os.path.join(_app_dir, creds_path_raw)
    )

    # Sheets OK: arquivo local OU secrets da nuvem configurados
    _secrets_ok = "gcp_service_account" in st.secrets
    sheets_ok = bool(spreadsheet_id) and (os.path.exists(creds_path) or _secrets_ok)
    if sheets_ok:
        st.success("Google Sheets configurado ✓")
    else:
        st.warning("Configure o Google Sheets para poder inserir.")

    st.divider()
    st.caption("v1.3 — Banco Volkswagen CCB · Gemini")

# ── Upload ───────────────────────────────────────────────────────────────────
st.subheader("📂 Upload de Contratos")

arquivos = st.file_uploader(
    "Arraste os PDFs dos contratos aqui",
    type="pdf",
    accept_multiple_files=True,
    label_visibility="collapsed",
)

if arquivos:
    n = len(arquivos)
    st.info(f"**{n} arquivo(s) carregado(s).** Clique em Processar para extrair as informações.")

    col_btn, _ = st.columns([1, 3])
    with col_btn:
        processar = st.button("🔍 Processar Contratos", type="primary", use_container_width=True)

    if processar:
        if not api_key:
            st.error("Informe a Gemini API Key nas configurações.")
            st.stop()

        resultados = []
        erros = []
        data_hoje = datetime.now().strftime("%d/%m/%Y")
        barra = st.progress(0, text="Iniciando extração...")

        for i, arq in enumerate(arquivos):
            barra.progress(i / n, text=f"Processando: **{arq.name}**")
            try:
                raw = extrair_contrato(arq.read(), api_key)
                processado = aplicar_regras(raw, data_hoje)
                processado["_arquivo"] = arq.name
                resultados.append(processado)
            except Exception as e:
                erros.append({"arquivo": arq.name, "erro": str(e)})

        barra.progress(1.0, text="Extração concluída!")

        for erro in erros:
            st.error(f"❌ Erro em **{erro['arquivo']}**: {erro['erro']}")

        if resultados:
            st.session_state["resultados"] = resultados
            st.rerun()

# ── Prévia e Inserção ────────────────────────────────────────────────────────
if st.session_state.get("resultados"):
    resultados = st.session_state["resultados"]

    st.success(f"✅ **{len(resultados)} contrato(s) extraído(s)** — revise os dados abaixo antes de inserir.")
    st.subheader("📋 Prévia dos Dados")

    df = pd.DataFrame([
        {
            "Arquivo":        r.get("_arquivo", ""),
            "Proposta":       r["proposta"],
            "Cliente":        r["cliente"],
            "CPF/CNPJ":       r["cpf_cnpj"],
            "Vendedor":       r["vendedor"],
            "Equipe":         r["equipe"],
            "Vr. Veículo":    f"R$ {r['valor_veiculo']:,.2f}",
            "Entrada":        f"R$ {r['entrada']:,.2f}",
            "Vr. Financiado": f"R$ {r['valor_financiado']:,.2f}",
            "SPF":            r["spf"],
            "APP":            r["app"],
            "GAP":            r["gap"],
            "Franquia":       r["franquia"],
            "GE":             r["ge"],
            "Protege":        r["protege"],
            "Prazo":          r["prazo"],
            "Taxa":           r["taxa"],
            "N/S":            r["tipo_veiculo"],
            "Sempre Novo":    r["sempre_novo"],
            "Peso":           r["peso_tabela"],
            "Retorno":        f"R$ {r['retorno']:,.2f}",
            "Pontos":         r["pontos"],
        }
        for r in resultados
    ])

    st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()
    col_ins, col_lim = st.columns([4, 1])

    with col_lim:
        if st.button("🗑️ Limpar", use_container_width=True):
            del st.session_state["resultados"]
            st.rerun()

    with col_ins:
        aba_atual = nome_aba_atual()
        label_btn = f"✅ Inserir {len(resultados)} linha(s) na planilha → aba {aba_atual}"

        if not sheets_ok:
            st.warning("Configure o Google Sheets na barra lateral para habilitar a inserção.")
        else:
            if st.button(label_btn, type="primary", use_container_width=True):
                try:
                    linhas = [para_linha_sheets(r) for r in resultados]
                    linha_ini = inserir_linhas_sheets(linhas, spreadsheet_id, creds_path)
                    st.success(
                        f"✅ **{len(linhas)} linha(s)** inserida(s) com sucesso na aba "
                        f"**{aba_atual}** a partir da linha **{linha_ini}**!"
                    )
                    del st.session_state["resultados"]
                    st.balloons()
                except Exception as e:
                    st.error(f"❌ Erro ao inserir na planilha: {e}")
