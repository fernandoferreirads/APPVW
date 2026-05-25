import streamlit as st
import json
import os
import re
import base64
import threading
import time as _time
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

# ─── Produtos Avulsos ──────────────────────────────────────────────────────────
# Categorias e opções exibidas no formulário de Cadastro Avulso
PRODUTOS_AVULSO = {
    "Garantia":   ["GE 1", "GE 2", "GE 3", "GE 4"],
    "Seguro":     ["Seguro VW", "Seguro Corretora"],
    "VW Protege": ["Prot Bas 24", "Prot Bas 36", "Prot Plus 24", "Prot Plus 36"],
}

# Pontos por produto avulso
PONTOS_AVULSO = {
    "GE 1":             0.50,
    "GE 2":             1.00,
    "GE 3":             1.15,
    "GE 4":             1.25,
    "Seguro VW":        0.50,
    "Seguro Corretora": 0.25,
    "Prot Bas 24":      0.25,
    "Prot Bas 36":      0.35,
    "Prot Plus 24":     0.50,
    "Prot Plus 36":     0.60,
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


def produto_para_linha_avulso(item: dict) -> list:
    """Gera a linha do Sheets para um cadastro avulso (GE, Seguro ou Protege)."""
    _protege_map = {
        "Prot Bas 24":  "PROTEGE BAS 24",
        "Prot Bas 36":  "PROTEGE BAS 36",
        "Prot Plus 24": "PROTEGE PLUS 24",
        "Prot Plus 36": "PROTEGE PLUS 36",
    }
    row = [""] * 28             # colunas A–AB (28 colunas)
    row[1]  = item["equipe"]    # B  - EQUIPE
    row[2]  = item["data"]      # C  - D. PAGTO
    row[3]  = item["cpf"]       # D  - CPF/CNPJ
    row[4]  = item["nome"]      # E  - CLIENTE
    row[20] = item["vendedor"]  # U  - VENDEDOR
    row[22] = item["pontos"]    # W  - PONTOS
    row[27] = item["equipe"]    # AB - LOJA

    cat  = item["categoria"]
    prod = item["produto"]

    if cat == "Garantia":
        row[13] = prod                          # N  - GE
        row[24] = prod                          # Y  - CORRESPONDÊNCIAS (tipo)
        row[25] = PONTOS_AVULSO.get(prod, "")   # Z  - CORRESPONDÊNCIAS (pts)
    elif cat == "Seguro":
        row[8] = prod                           # I  - coluna de Seguro/SPF
    elif cat == "VW Protege":
        row[14] = _protege_map.get(prod, prod)  # O  - PROTEGE

    return row


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
    page_title="Flow F&I — Financiamentos VW",
    page_icon="🚗",
    layout="wide",
)

# ── Assets ───────────────────────────────────────────────────────────────────
def _img_b64(path: str) -> str:
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    except Exception:
        return ""

_assets_dir   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
_vw_b64       = _img_b64(os.path.join(_assets_dir, "vw_logo.png"))
_brasal_b64   = _img_b64(os.path.join(_assets_dir, "brasal_logo.png"))

# ── Estilos VW Financial Services ────────────────────────────────────────────
st.markdown('<meta name="google" content="notranslate">', unsafe_allow_html=True)
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
@import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200&display=block');

* { font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important; }

/*
 * Restaura a fonte correta para os ícones do Streamlit.
 * [data-testid="stIconMaterial"] tem especificidade 0-1-0 > universal 0-0-0,
 * então sobrepõe o !important do * acima mesmo com !important aqui.
 */
[data-testid="stIconMaterial"] {
    font-family: "Material Symbols Rounded" !important;
    font-size: 1.25rem !important;
    line-height: 1 !important;
    font-weight: 400 !important;
    font-style: normal !important;
    letter-spacing: normal !important;
    user-select: none !important;
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
}

/* Esconde branding Streamlit SEM remover o botão da sidebar */
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }
[data-testid="stDecoration"] { display: none !important; }
[data-testid="stStatusWidget"] { visibility: hidden !important; }
/* Deixa a toolbar transparente mas NÃO usa display:none (sidebar toggle precisa dela) */
[data-testid="stToolbar"] { visibility: hidden; }
/* Header transparente — toggle da sidebar permanece clicável */
header[data-testid="stHeader"] {
    background: transparent !important;
    border-bottom: none !important;
}

/* Fundo gradiente suave */
.stApp {
    background: linear-gradient(160deg, #ffffff 0%, #f4f6fb 55%, #eaecf4 100%) !important;
}

/* Espaço para o header do Streamlit (onde fica o botão da sidebar) */
.block-container {
    padding-top: 3.5rem !important;
    padding-bottom: 5rem !important;
}

/* ── Header ── */
.vw-header {
    background: linear-gradient(135deg, #001e50 0%, #002d7a 100%);
    border-radius: 12px;
    padding: 1.75rem 2.5rem;
    display: flex;
    align-items: center;
    gap: 2rem;
    margin-bottom: 2rem;
    box-shadow: 0 4px 24px rgba(0,30,80,0.18);
}
/* Logo VW dentro de círculo branco */
.vw-logo-wrap {
    width: 76px;
    height: 76px;
    border-radius: 50%;
    background: #ffffff;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    overflow: hidden;
    padding: 8px;
    box-shadow: 0 2px 10px rgba(0,0,0,0.2);
}
.vw-logo-wrap img {
    width: 100%;
    height: 100%;
    object-fit: contain;
}
.vw-header-sep {
    width: 1px;
    height: 56px;
    background: rgba(255,255,255,0.2);
    flex-shrink: 0;
}
.vw-header-text h1 {
    color: #ffffff;
    font-size: 1.55rem;
    font-weight: 700;
    margin: 0 0 5px 0;
    letter-spacing: -0.4px;
    line-height: 1.2;
}
.vw-header-text p {
    color: rgba(255,255,255,0.6);
    font-size: 0.875rem;
    font-weight: 400;
    margin: 0;
    letter-spacing: 0.2px;
}
.vw-header-badge {
    margin-left: auto;
    background: rgba(255,255,255,0.08);
    border: 1px solid rgba(255,255,255,0.18);
    border-radius: 20px;
    padding: 6px 18px;
    color: rgba(255,255,255,0.75);
    font-size: 0.78rem;
    font-weight: 500;
    letter-spacing: 0.5px;
    white-space: nowrap;
}

/* ── Título de seção com ícone SVG ── */
.section-title {
    display: flex;
    align-items: center;
    gap: 10px;
    margin: 1.5rem 0 1rem 0;
}
.section-title span {
    color: #001e50;
    font-size: 1.2rem;
    font-weight: 600;
    letter-spacing: -0.2px;
}

/* ── Fix texto duplicado no botão de upload ── */
/* Oculta TODO conteúdo interno do botão (qualquer variante de Streamlit) */
[data-testid="stFileUploaderDropzone"] button > *,
[data-testid="stFileUploaderDropzone"] button > * > *,
[data-testid="stFileUploaderDropzoneButton"] > *,
[data-testid="stFileUploaderDropzoneButton"] > * > * {
    display: none !important;
    visibility: hidden !important;
}
/* Substitui pelo nosso texto via ::before — CSS puro, não é traduzido */
[data-testid="stFileUploaderDropzone"] button,
[data-testid="stFileUploaderDropzoneButton"] {
    position: relative !important;
    min-width: 150px !important;
    min-height: 36px !important;
}
[data-testid="stFileUploaderDropzone"] button::before,
[data-testid="stFileUploaderDropzoneButton"]::before {
    content: "Selecionar arquivos" !important;
    position: absolute !important;
    top: 50% !important;
    left: 50% !important;
    transform: translate(-50%, -50%) !important;
    display: block !important;
    visibility: visible !important;
    font-size: 0.875rem !important;
    font-weight: 500 !important;
    line-height: 1 !important;
    white-space: nowrap !important;
    color: inherit !important;
    pointer-events: none !important;
}

/* ── Seta animada entre header e conteúdo ── */
.down-arrow-hint {
    display: flex;
    justify-content: center;
    align-items: center;
    margin: 0.25rem 0 1.5rem 0;
    opacity: 0.75;
    animation: vw-bounce 2.2s ease-in-out infinite;
}
@keyframes vw-bounce {
    0%, 100% { transform: translateY(0px);  opacity: 0.65; }
    50%       { transform: translateY(8px);  opacity: 1;    }
}

/* ── Buttons ── */
.stButton > button[kind="primary"] {
    background: #001e50 !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 6px !important;
    font-weight: 600 !important;
    font-size: 0.9rem !important;
    letter-spacing: 0.2px !important;
    transition: background 0.2s, box-shadow 0.2s, transform 0.15s !important;
}
.stButton > button[kind="primary"]:hover {
    background: #002d7a !important;
    box-shadow: 0 4px 14px rgba(0,30,80,0.28) !important;
    transform: translateY(-1px) !important;
}

/* ── Headings ── */
h2, h3 {
    color: #001e50 !important;
    font-weight: 600 !important;
}

/* ── Progress bar ── */
.stProgress > div > div > div {
    background: linear-gradient(90deg, #001e50, #0057b8) !important;
}

/* ── Alerts ── */
div[data-testid="stAlert"] {
    border-radius: 8px !important;
}

/* ── Footer ── */
.vw-footer {
    position: fixed;
    bottom: 0; left: 0; right: 0;
    height: 48px;
    background: rgba(244,246,251,0.97);
    backdrop-filter: blur(8px);
    border-top: 1px solid #dde3ef;
    display: flex;
    align-items: center;
    justify-content: flex-start;
    padding: 0 2rem;
    z-index: 9999;
    gap: 1rem;
}
.vw-footer img {
    height: 26px;
    opacity: 0.85;
}
.vw-footer-sep {
    width: 1px;
    height: 20px;
    background: #c0c8d8;
}
.vw-footer-version {
    color: #8a94a8;
    font-size: 0.72rem;
    letter-spacing: 0.3px;
}
</style>
""", unsafe_allow_html=True)

# ── Header ───────────────────────────────────────────────────────────────────
_vw_inner = (
    f'<img src="data:image/png;base64,{_vw_b64}" alt="Volkswagen">'
    if _vw_b64 else
    '<span style="color:#001e50;font-size:1.6rem;font-weight:700;">VW</span>'
)
st.markdown(f"""
<div class="vw-header">
    <div class="vw-logo-wrap">{_vw_inner}</div>
    <div class="vw-header-sep"></div>
    <div class="vw-header-text">
        <h1>Flow F&amp;I</h1>
        <p>Banco Volkswagen · CCB — Processamento automatizado via Gemini AI</p>
    </div>
    <span class="vw-header-badge">Financiamentos VW</span>
</div>
""", unsafe_allow_html=True)

# ── Footer (posição fixa) ─────────────────────────────────────────────────────
_brasal_img = (
    f'<img src="data:image/png;base64,{_brasal_b64}" alt="Brasal Veículos">'
    if _brasal_b64 else
    '<span style="color:#6b7280;font-size:0.85rem;font-weight:500;">Brasal Veículos</span>'
)
st.markdown(f"""
<div class="vw-footer">
    {_brasal_img}
    <div class="vw-footer-sep"></div>
    <span class="vw-footer-version">v1.3 · Banco Volkswagen CCB</span>
</div>
""", unsafe_allow_html=True)

# ── Configurações (popover — botão nativo, painel flutuante) ──────────────────
_gemini_default = os.getenv("GEMINI_API_KEY") or st.secrets.get("GEMINI_API_KEY", "")
_sid_default    = os.getenv("SPREADSHEET_ID") or st.secrets.get("SPREADSHEET_ID", "")

# st.popover: botão sempre visível, abre popup ao clicar.
# O bloco interno SEMPRE executa a cada rerun (como st.expander),
# então todas as variáveis ficam disponíveis no escopo global.
with st.popover("⚙️  Configurações"):
    col1, col2, col3 = st.columns(3)
    with col1:
        api_key = st.text_input(
            "Gemini API Key",
            value=_gemini_default,
            type="password",
            help="Chave gratuita em: aistudio.google.com → Get API Key",
            key="cfg_api_key",
        )
    with col2:
        _sid_raw = st.text_input(
            "ID do Google Sheets",
            value=_sid_default,
            help="ID da planilha na URL: docs.google.com/spreadsheets/d/[ID]/edit",
            key="cfg_sheets_id",
        )
    with col3:
        creds_path_raw = st.text_input(
            "Credenciais Google (JSON)",
            value=os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials/service_account.json"),
            help="Caminho para o arquivo JSON da conta de serviço",
            key="cfg_creds_path",
        )

    # Aceita URL completa ou só o ID — extrai apenas o ID
    _sid_match = re.search(r'spreadsheets/d/([a-zA-Z0-9_-]+)', _sid_raw)
    spreadsheet_id = _sid_match.group(1) if _sid_match else _sid_raw.strip()

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
        st.warning("Configure o ID da planilha e as credenciais Google para habilitar a inserção.")

# ── Upload ───────────────────────────────────────────────────────────────────
st.markdown("""
<div class="section-title">
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none"
         stroke="#001e50" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
        <polyline points="17 8 12 3 7 8"/>
        <line x1="12" y1="3" x2="12" y2="15"/>
    </svg>
    <span>Envio de Contratos</span>
</div>
""", unsafe_allow_html=True)

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
        erros      = []
        data_hoje  = datetime.now().strftime("%d/%m/%Y")

        # Barra de progresso geral (avança a cada arquivo concluído)
        barra = st.progress(0, text="Iniciando extração...")

        # st.status: spinner CSS animado pelo cliente — não depende de updates do servidor
        with st.status("⏳ Processando contratos via Gemini AI…", expanded=True) as _status:
            for i, arq in enumerate(arquivos):
                barra.progress(i / n, text=f"Contrato {i + 1}/{n}: **{arq.name}**")
                st.write(f"🔍 Lendo: **{arq.name}**")

                # Thread separada para a chamada à API
                _slot = {"raw": None, "err": None}
                _pdf  = arq.read()

                def _worker(pdf=_pdf, slot=_slot):
                    try:
                        slot["raw"] = extrair_contrato(pdf, api_key)
                    except Exception as exc:
                        slot["err"] = str(exc)

                _t = threading.Thread(target=_worker, daemon=True)
                _t.start()

                # Animação da barra enquanto aguarda
                _p     = i / n
                _teto  = (i / n) + (1 / n) * 0.90
                _passo = (1 / n) * 0.90 / 60   # ~30 s para cobrir 90 % do segmento
                while _t.is_alive():
                    _p = min(_p + _passo, _teto)
                    barra.progress(_p, text=f"⏳ Gemini AI analisando: **{arq.name}**")
                    _time.sleep(0.5)

                _t.join()

                if _slot["err"]:
                    erros.append({"arquivo": arq.name, "erro": _slot["err"]})
                    st.write(f"❌ Erro: **{arq.name}**")
                else:
                    try:
                        processado = aplicar_regras(_slot["raw"], data_hoje)
                        processado["_arquivo"] = arq.name
                        resultados.append(processado)
                        st.write(f"✅ Concluído: **{arq.name}**")
                    except Exception as exc:
                        erros.append({"arquivo": arq.name, "erro": str(exc)})
                        st.write(f"❌ Erro ao processar: **{arq.name}**")

                barra.progress((i + 1) / n, text=f"✅ {i + 1}/{n} concluído(s)")

            barra.progress(1.0, text="✅ Processamento concluído!")

            if erros:
                _status.update(label=f"⚠️ Concluído com {len(erros)} erro(s)", state="error")
            else:
                _status.update(
                    label=f"✅ {len(resultados)} contrato(s) extraído(s) com sucesso!",
                    state="complete",
                )

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

# ── Cadastro Avulso ───────────────────────────────────────────────────────────
st.markdown(
    '<hr style="border:none;border-top:2px solid #eaecf4;margin:2.5rem 0 1.5rem 0;">',
    unsafe_allow_html=True,
)

st.markdown("""
<div class="section-title">
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none"
         stroke="#001e50" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 20h9"/>
        <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/>
    </svg>
    <span>Cadastro Avulso</span>
</div>
<p style="color:#6b7280;font-size:0.875rem;margin:-0.5rem 0 1.25rem 32px;">
    Garantias &nbsp;·&nbsp; Seguros &nbsp;·&nbsp; VW Protege &mdash; produtos inseridos fora do financiamento
</p>
""", unsafe_allow_html=True)

if "avulso_items" not in st.session_state:
    st.session_state["avulso_items"] = []

# Formulário de entrada
with st.container(border=True):
    # Linha 1 — Nome e CPF
    col_av_nome, col_av_cpf = st.columns(2)
    with col_av_nome:
        av_nome = st.text_input(
            "Nome do Cliente",
            key="av_nome",
            placeholder="Ex: JOÃO SILVA SANTOS",
        )
    with col_av_cpf:
        av_cpf = st.text_input(
            "CPF",
            key="av_cpf",
            placeholder="000.000.000-00",
        )

    # Linha 2 — Vendedor | Categoria | Produto (cascata)
    col_av_vend, col_av_cat, col_av_prod = st.columns(3)
    with col_av_vend:
        av_vendedor = st.selectbox(
            "Vendedor",
            options=sorted(VENDEDOR_EQUIPE.keys()),
            key="av_vendedor",
        )
        _av_equipe = lookup_vendedor(av_vendedor)
        st.caption(f"🏢 Equipe: **{_av_equipe}**")

    with col_av_cat:
        av_cat = st.selectbox(
            "Categoria",
            options=list(PRODUTOS_AVULSO.keys()),
            key="av_categoria",
        )

    with col_av_prod:
        # Chave dinâmica garante reset ao trocar de categoria
        av_prod = st.selectbox(
            "Produto",
            options=PRODUTOS_AVULSO[av_cat],
            key=f"av_produto_{av_cat}",
        )
        _av_pts = PONTOS_AVULSO.get(av_prod, 0)
        st.caption(f"⭐ Pontos: **{_av_pts}**")

    # Botão Adicionar
    col_av_add, _col_sp = st.columns([1, 4])
    with col_av_add:
        av_add = st.button("➕ Adicionar à lista", key="av_add", use_container_width=True)

if av_add:
    if not av_nome.strip():
        st.warning("⚠️ Informe o nome do cliente.")
    elif not av_cpf.strip():
        st.warning("⚠️ Informe o CPF.")
    else:
        st.session_state["avulso_items"].append({
            "nome":      av_nome.strip().upper(),
            "cpf":       av_cpf.strip(),
            "vendedor":  av_vendedor,
            "equipe":    _av_equipe,
            "categoria": av_cat,
            "produto":   av_prod,
            "pontos":    _av_pts,
            "data":      datetime.now().strftime("%d/%m/%Y"),
        })
        st.rerun()

# Prévia da fila e botão de inserção
if st.session_state["avulso_items"]:
    _av_items = st.session_state["avulso_items"]
    st.success(f"**{len(_av_items)} item(ns)** na fila — confira abaixo antes de inserir na planilha.")

    _av_df = pd.DataFrame([
        {
            "Nome":      it["nome"],
            "CPF":       it["cpf"],
            "Vendedor":  it["vendedor"],
            "Equipe":    it["equipe"],
            "Categoria": it["categoria"],
            "Produto":   it["produto"],
            "Pontos":    it["pontos"],
        }
        for it in _av_items
    ])
    st.dataframe(_av_df, use_container_width=True, hide_index=True)

    col_av_ins, col_av_lim = st.columns([4, 1])

    with col_av_lim:
        if st.button("🗑️ Limpar", key="av_clear", use_container_width=True):
            st.session_state["avulso_items"] = []
            st.rerun()

    with col_av_ins:
        _av_aba = nome_aba_atual()
        if not sheets_ok:
            st.warning("Configure o Google Sheets nas configurações para habilitar a inserção.")
        else:
            if st.button(
                f"✅ Inserir {len(_av_items)} item(ns) na planilha → aba {_av_aba}",
                type="primary",
                key="av_inserir",
                use_container_width=True,
            ):
                try:
                    _av_linhas  = [produto_para_linha_avulso(it) for it in _av_items]
                    _av_ini     = inserir_linhas_sheets(_av_linhas, spreadsheet_id, creds_path)
                    st.success(
                        f"✅ **{len(_av_linhas)} item(ns)** inserido(s) com sucesso na aba "
                        f"**{_av_aba}** a partir da linha **{_av_ini}**!"
                    )
                    st.session_state["avulso_items"] = []
                    st.balloons()
                except Exception as e:
                    st.error(f"❌ Erro ao inserir: {e}")
