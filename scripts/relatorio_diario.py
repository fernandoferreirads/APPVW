"""
Relatório Diário de Produção — Brasal Volkswagen
Executado via GitHub Actions toda manhã (07:00 BRT).
Lê o BIGBASE do Excel (OneDrive), gera gráficos e envia por email.
"""

import os, io, base64, smtplib, requests
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from datetime import date, timedelta

# ─── Configuração (via GitHub Secrets / variáveis de ambiente) ────────────────
CLIENT_ID     = os.environ["MS_CLIENT_ID"]
REFRESH_TOKEN = os.environ["MS_REFRESH_TOKEN"]
EXCEL_URL     = os.environ["MS_EXCEL_URL"]
GMAIL_FROM    = os.environ["GMAIL_EMAIL"]
GMAIL_PASS    = os.environ["GMAIL_APP_PASSWORD"]
EMAIL_TO      = os.environ.get("EMAIL_TO", "ib.rec17@brasal.com.br")

VW_BLUE  = "#001E50"
AZUL_NV  = "#4472C4"
LARANJA  = "#ED7D31"
VERDE    = "#1EBE5D"
MESES_PT = {1:"JAN",2:"FEV",3:"MAR",4:"ABR",5:"MAI",6:"JUN",
            7:"JUL",8:"AGO",9:"SET",10:"OUT",11:"NOV",12:"DEZ"}


# ─── Auth Microsoft Graph ─────────────────────────────────────────────────────
def get_access_token() -> tuple[str, str]:
    r = requests.post(
        "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        data={
            "grant_type":    "refresh_token",
            "client_id":     CLIENT_ID,
            "refresh_token": REFRESH_TOKEN,
            "scope":         "https://graph.microsoft.com/Files.Read offline_access",
        },
        timeout=30,
    )
    r.raise_for_status()
    d = r.json()
    return d["access_token"], d.get("refresh_token", REFRESH_TOKEN)


def download_excel(token: str, sharing_url: str) -> bytes:
    b64 = base64.urlsafe_b64encode(sharing_url.encode()).decode().rstrip("=")
    r = requests.get(
        f"https://graph.microsoft.com/v1.0/shares/u!{b64}/driveItem/content",
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    )
    r.raise_for_status()
    return r.content


# ─── Carrega BIGBASE ──────────────────────────────────────────────────────────
_COLS = {
    0:"proposta", 1:"equipe", 2:"data_pagto", 3:"cpf_cnpj",
    4:"cliente", 8:"spf", 9:"app", 10:"gap", 11:"franquia",
    13:"ge", 14:"protege", 17:"tipo_veiculo", 18:"sempre_novo",
    20:"vendedor", 21:"retorno", 22:"pontos",
}

def load_bigbase(excel_bytes: bytes) -> pd.DataFrame:
    df = pd.read_excel(io.BytesIO(excel_bytes), sheet_name="BASE_PAGAMENTOS", header=0)
    rename = {df.columns[i]: name for i, name in _COLS.items() if i < len(df.columns)}
    df = df.rename(columns=rename)
    df["data_pagto"] = pd.to_datetime(df["data_pagto"], errors="coerce", dayfirst=True)
    if "pontos" in df.columns:
        df["pontos"] = pd.to_numeric(
            df["pontos"].astype(str).str.replace(",", ".", regex=False), errors="coerce"
        ).fillna(0.0)
    return df.dropna(subset=["data_pagto"])


# ─── Helpers de período ───────────────────────────────────────────────────────
def _ultimos_meses(df: pd.DataFrame, n: int = 6) -> list[dict]:
    hoje = date.today()
    result = []
    for i in range(n, 0, -1):
        pivot = date(hoje.year, hoje.month, 1)
        for _ in range(i):
            pivot = date(pivot.year, pivot.month, 1) - timedelta(days=1)
        y, m = pivot.year, pivot.month
        sub = df[(df["data_pagto"].dt.year == y) & (df["data_pagto"].dt.month == m)]
        result.append({"label": f"{MESES_PT[m]}/{str(y)[2:]}", "df": sub})
    return result


def _count_col(sub: pd.DataFrame, col: str, filtro: str = "") -> int:
    if col not in sub.columns:
        return 0
    s = sub[col].astype(str).str.strip().str.upper()
    if filtro:
        return int(s.str.contains(filtro.upper()).sum())
    return int((s.notna() & (s != "") & (s != "NAN") & (s != "NONE")).sum())


# ─── Geração de gráficos ──────────────────────────────────────────────────────
def _fig_bytes(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _style_ax(ax, title: str):
    ax.set_title(title, color=VW_BLUE, fontweight="bold", fontsize=11, pad=10)
    ax.set_facecolor("#F8FAFF")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(labelsize=9)


def _chart_barras_perc(df, col, titulo, cor_barra, filtro="") -> bytes:
    """Barras de quantidade + linha de % penetração."""
    meses = _ultimos_meses(df, 6)
    labels = [r["label"] for r in meses]
    totais = [len(r["df"]) for r in meses]
    qtds   = [_count_col(r["df"], col, filtro) for r in meses]
    percs  = [round(q / t * 100, 1) if t > 0 else 0 for q, t in zip(qtds, totais)]

    fig, ax1 = plt.subplots(figsize=(10, 4))
    ax2 = ax1.twinx()

    bars = ax1.bar(range(len(labels)), qtds, color=cor_barra, zorder=3, alpha=0.85)
    ax2.plot(range(len(labels)), percs, color=LARANJA, linewidth=2,
             marker="o", markersize=5, label="% Penetração", zorder=4)

    for bar, v in zip(bars, qtds):
        if v > 0:
            ax1.text(bar.get_x() + bar.get_width()/2, v + 0.3, str(v),
                     ha="center", va="bottom", fontsize=9, fontweight="bold")
    for i, p in enumerate(percs):
        if p > 0:
            ax2.text(i, p + 0.8, f"{p:.0f}%",
                     ha="center", va="bottom", fontsize=8, color=LARANJA, fontweight="bold")

    ax1.set_xticks(range(len(labels)))
    ax1.set_xticklabels(labels)
    ax1.set_ylabel("Quantidade", fontsize=9, color=VW_BLUE)
    ax2.set_ylabel("% Penetração", fontsize=9, color=LARANJA)
    ax2.tick_params(colors=LARANJA, labelsize=8)
    ax2.spines["top"].set_visible(False)
    ax2.legend(fontsize=8, loc="upper left")
    _style_ax(ax1, titulo)
    fig.patch.set_facecolor("white")
    fig.tight_layout()
    return _fig_bytes(fig)


def chart_contratos(df: pd.DataFrame) -> bytes:
    meses = _ultimos_meses(df, 6)
    labels = [r["label"] for r in meses]
    nv = [_count_col(r["df"], "tipo_veiculo", "N") for r in meses]
    sn = [_count_col(r["df"], "tipo_veiculo", "S") for r in meses]

    fig, ax = plt.subplots(figsize=(10, 4))
    x = range(len(labels))
    b1 = ax.bar([i - 0.2 for i in x], nv, 0.38, label="Novo (NV)", color=AZUL_NV)
    b2 = ax.bar([i + 0.2 for i in x], sn, 0.38, label="Semi-Novo (SN)", color=LARANJA)
    for bar in list(b1) + list(b2):
        h = bar.get_height()
        if h > 0:
            ax.text(bar.get_x() + bar.get_width()/2, h + 0.2, str(int(h)),
                    ha="center", va="bottom", fontsize=9, fontweight="bold")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels)
    ax.legend(fontsize=9)
    _style_ax(ax, "CONTRATOS — NV vs SN (últimos 6 meses)")
    fig.patch.set_facecolor("white")
    fig.tight_layout()
    return _fig_bytes(fig)


def chart_total_pontos(df: pd.DataFrame) -> bytes:
    meses = _ultimos_meses(df, 6)
    labels = [r["label"] for r in meses]
    totais = []
    for r in meses:
        s = r["df"]
        totais.append(round(float(s["pontos"].sum()), 1) if "pontos" in s.columns else 0.0)

    fig, ax = plt.subplots(figsize=(10, 4))
    bars = ax.bar(range(len(labels)), totais, color=AZUL_NV, zorder=3)
    for bar, v in zip(bars, totais):
        if v > 0:
            ax.text(bar.get_x() + bar.get_width()/2, v + 0.5,
                    f"{v:.1f}".replace(".", ","), ha="center", va="bottom",
                    fontsize=9, fontweight="bold")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels)
    _style_ax(ax, "TOTAL DE PONTOS — Soma mensal")
    fig.patch.set_facecolor("white")
    fig.tight_layout()
    return _fig_bytes(fig)


def chart_pontos(df: pd.DataFrame) -> bytes:
    meses = _ultimos_meses(df, 6)
    labels = [r["label"] for r in meses]
    medias = []
    for r in meses:
        s = r["df"]
        medias.append(round(s["pontos"].sum() / len(s), 2) if len(s) > 0 and "pontos" in s.columns else 0)

    cores = [("#1A5C38" if v >= 1.5 else ("#92400e" if v >= 1.3 else "#991b1b")) for v in medias]
    fig, ax = plt.subplots(figsize=(10, 4))
    bars = ax.bar(range(len(labels)), medias, color=cores, zorder=3)
    ax.axhline(1.5, color="red", linewidth=1.5, linestyle="--", label="Meta: 1,50", zorder=4)
    for bar, v in zip(bars, medias):
        if v > 0:
            ax.text(bar.get_x() + bar.get_width()/2, v + 0.03,
                    f"{v:.2f}".replace(".", ","), ha="center", va="bottom", fontsize=9, fontweight="bold")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels)
    ax.legend(fontsize=9)
    _style_ax(ax, "PONTOS POR CONTRATO — Média mensal vs Meta 1,50")
    fig.patch.set_facecolor("white")
    fig.tight_layout()
    return _fig_bytes(fig)


def chart_garantias(df: pd.DataFrame) -> bytes:
    return _chart_barras_perc(df, "ge", "GARANTIAS ESTENDIDAS — Quantidade e % Penetração", AZUL_NV)


def chart_seguros(df: pd.DataFrame) -> bytes:
    return _chart_barras_perc(df, "app", "SEGUROS (AP) — Quantidade e % Penetração", "#6366F1")


def chart_spf(df: pd.DataFrame) -> bytes:
    meses = _ultimos_meses(df, 6)
    labels = [r["label"] for r in meses]
    total  = [_count_col(r["df"], "spf") for r in meses]
    plus   = [_count_col(r["df"], "spf", "PLUS") for r in meses]

    fig, ax = plt.subplots(figsize=(10, 4))
    x = range(len(labels))
    b1 = ax.bar([i - 0.2 for i in x], total, 0.38, label="SPF Total", color=VERDE)
    b2 = ax.bar([i + 0.2 for i in x], plus,  0.38, label="SPF Plus",  color="#0F6E56")
    for bar in list(b1) + list(b2):
        h = bar.get_height()
        if h > 0:
            ax.text(bar.get_x() + bar.get_width()/2, h + 0.2, str(int(h)),
                    ha="center", va="bottom", fontsize=9, fontweight="bold")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels)
    ax.legend(fontsize=9)
    _style_ax(ax, "SPF — Total vs Plus (últimos 6 meses)")
    fig.patch.set_facecolor("white")
    fig.tight_layout()
    return _fig_bytes(fig)


def chart_protege(df: pd.DataFrame) -> bytes:
    return _chart_barras_perc(df, "protege", "PROTEGE — Quantidade e % Penetração", "#8B5CF6")


def chart_sempre_novo(df: pd.DataFrame) -> bytes:
    return _chart_barras_perc(df, "sempre_novo", "SEMPRE NOVO — Quantidade e % Penetração", "#0EA5E9")


# ─── Resumo do dia anterior ───────────────────────────────────────────────────
def resumo_ontem(df: pd.DataFrame) -> dict:
    ontem = date.today() - timedelta(days=1)
    sub   = df[df["data_pagto"].dt.date == ontem].copy()

    total_pts = float(sub["pontos"].sum()) if "pontos" in sub.columns else 0.0
    n = len(sub)
    media_pts = total_pts / n if n > 0 else 0.0

    produtos = {}
    for col in ["spf", "app", "gap", "franquia", "ge", "protege", "sempre_novo"]:
        if col in sub.columns:
            cnt = _count_col(sub, col)
            if cnt > 0:
                produtos[col.upper()] = cnt

    vendedores = {}
    if "vendedor" in sub.columns:
        vendedores = (sub["vendedor"].dropna().astype(str).str.strip()
                      .value_counts().head(10).to_dict())

    return {
        "data":         ontem.strftime("%d/%m/%Y"),
        "contratos":    n,
        "total_pontos": total_pts,
        "media_pontos": media_pts,
        "produtos":     produtos,
        "vendedores":   vendedores,
    }


# ─── Montagem do email ────────────────────────────────────────────────────────
_CHART_ORDER = [
    ("chart_contratos",   "CONTRATOS — NV vs SN"),
    ("chart_total_pontos","TOTAL DE PONTOS"),
    ("chart_pontos",      "PONTOS POR CONTRATO vs Meta"),
    ("chart_garantias",   "GARANTIAS ESTENDIDAS"),
    ("chart_seguros",     "SEGUROS (AP)"),
    ("chart_spf",         "SPF — Total vs Plus"),
    ("chart_protege",     "PROTEGE"),
    ("chart_sempre_novo", "SEMPRE NOVO"),
]

def build_email(charts: dict, r: dict) -> MIMEMultipart:
    msg = MIMEMultipart("related")
    msg["Subject"] = f"📊 Relatório de Produção — {r['data']} | Brasal VW"
    msg["From"]    = GMAIL_FROM
    msg["To"]      = EMAIL_TO

    cor_media = ("#166534" if r["media_pontos"] >= 1.5
                 else ("#92400e" if r["media_pontos"] >= 1.3 else "#991b1b"))

    def tabela_rows(d: dict) -> str:
        if not d:
            return "<tr><td colspan='2' style='color:#999;padding:8px 12px'>Nenhum registro</td></tr>"
        return "".join(
            f"<tr style='border-bottom:1px solid #EEF2FA'>"
            f"<td style='padding:5px 12px;color:#374A6B'>{k}</td>"
            f"<td style='padding:5px 12px;font-weight:700;color:#001E50'>{v}</td></tr>"
            for k, v in d.items()
        )

    graficos_html = "\n".join(
        f'<img src="cid:{cid}" style="width:100%;border-radius:8px;margin-bottom:14px;display:block">'
        for cid, _ in _CHART_ORDER if cid in charts
    )

    html = f"""
<html><body style="font-family:Arial,sans-serif;background:#EEF2FA;margin:0;padding:24px">
<div style="max-width:680px;margin:0 auto">

  <div style="background:#001E50;padding:22px 30px;border-radius:10px 10px 0 0">
    <h1 style="color:white;margin:0;font-size:19px;letter-spacing:.5px">📊 Relatório Diário de Produção</h1>
    <p style="color:rgba(255,255,255,.65);margin:5px 0 0;font-size:12px">
      Brasal Volkswagen · Flow F&amp;I · {r['data']}
    </p>
  </div>

  <div style="background:white;padding:24px 30px;border:1px solid #DDE3EF;border-top:none">
    <p style="color:#374A6B;font-size:12px;text-transform:uppercase;letter-spacing:1px;margin:0 0 14px;font-weight:700">
      Resumo de Ontem
    </p>
    <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:22px">
      <div style="flex:1;min-width:120px;background:#F8FAFF;border:1.5px solid #DDE3EF;border-radius:8px;padding:14px;text-align:center">
        <div style="color:#6B7280;font-size:10px;text-transform:uppercase;letter-spacing:.5px">Contratos</div>
        <div style="color:#001E50;font-size:30px;font-weight:700;line-height:1.2">{r['contratos']}</div>
      </div>
      <div style="flex:1;min-width:120px;background:#F8FAFF;border:1.5px solid #DDE3EF;border-radius:8px;padding:14px;text-align:center">
        <div style="color:#6B7280;font-size:10px;text-transform:uppercase;letter-spacing:.5px">Total de Pontos</div>
        <div style="color:#001E50;font-size:30px;font-weight:700;line-height:1.2">{r['total_pontos']:.1f}</div>
      </div>
      <div style="flex:1;min-width:120px;background:#F8FAFF;border:1.5px solid {cor_media};border-radius:8px;padding:14px;text-align:center">
        <div style="color:#6B7280;font-size:10px;text-transform:uppercase;letter-spacing:.5px">Média / Contrato</div>
        <div style="color:{cor_media};font-size:30px;font-weight:700;line-height:1.2">{r['media_pontos']:.2f}</div>
      </div>
    </div>

    <div style="display:flex;gap:20px;flex-wrap:wrap">
      <div style="flex:1;min-width:200px">
        <p style="color:#374A6B;font-size:11px;text-transform:uppercase;letter-spacing:.5px;font-weight:700;margin:0 0 8px">Produtos</p>
        <table style="width:100%;border-collapse:collapse;background:#F8FAFF;border-radius:8px;overflow:hidden;font-size:13px">
          {tabela_rows(r['produtos'])}
        </table>
      </div>
      <div style="flex:1;min-width:200px">
        <p style="color:#374A6B;font-size:11px;text-transform:uppercase;letter-spacing:.5px;font-weight:700;margin:0 0 8px">Vendedores</p>
        <table style="width:100%;border-collapse:collapse;background:#F8FAFF;border-radius:8px;overflow:hidden;font-size:13px">
          {tabela_rows(r['vendedores'])}
        </table>
      </div>
    </div>
  </div>

  <div style="background:white;padding:24px 30px;border:1px solid #DDE3EF;border-top:none">
    <p style="color:#374A6B;font-size:12px;text-transform:uppercase;letter-spacing:1px;margin:0 0 16px;font-weight:700">
      Gráficos — Últimos 6 Meses
    </p>
    {graficos_html}
  </div>

  <div style="background:#001E50;padding:12px 30px;border-radius:0 0 10px 10px;text-align:center">
    <p style="color:rgba(255,255,255,.45);font-size:10px;margin:0">
      Enviado automaticamente · extratorvw.streamlit.app
    </p>
  </div>

</div>
</body></html>
"""

    msg.attach(MIMEText(html, "html"))
    for cid, _ in _CHART_ORDER:
        if cid in charts:
            img = MIMEImage(charts[cid], "png")
            img.add_header("Content-ID",          f"<{cid}>")
            img.add_header("Content-Disposition", "inline")
            msg.attach(img)

    return msg


def send_email(msg: MIMEMultipart) -> None:
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(GMAIL_FROM, GMAIL_PASS)
        smtp.send_message(msg)


# ─── Entry point ──────────────────────────────────────────────────────────────
def main():
    print("🔐 Autenticando no Microsoft Graph...")
    token, new_refresh = get_access_token()

    if new_refresh != REFRESH_TOKEN:
        with open(os.environ.get("GITHUB_ENV", "/dev/null"), "a") as f:
            f.write(f"NEW_REFRESH_TOKEN={new_refresh}\n")
        print("♻️  Refresh token renovado.")

    print("📥 Baixando BIGBASE do Excel...")
    excel_bytes = download_excel(token, EXCEL_URL)

    print("📊 Processando dados...")
    df = load_bigbase(excel_bytes)

    print("🎨 Gerando gráficos...")
    charts = {
        "chart_contratos":    chart_contratos(df),
        "chart_total_pontos": chart_total_pontos(df),
        "chart_pontos":       chart_pontos(df),
        "chart_garantias":    chart_garantias(df),
        "chart_seguros":      chart_seguros(df),
        "chart_spf":          chart_spf(df),
        "chart_protege":      chart_protege(df),
        "chart_sempre_novo":  chart_sempre_novo(df),
    }

    resumo = resumo_ontem(df)
    print(f"📅 Ontem ({resumo['data']}): {resumo['contratos']} contrato(s) · {resumo['total_pontos']:.1f} pts")

    print("📧 Enviando email...")
    msg = build_email(charts, resumo)
    send_email(msg)
    print(f"✅ Relatório enviado para {EMAIL_TO}")


if __name__ == "__main__":
    main()
