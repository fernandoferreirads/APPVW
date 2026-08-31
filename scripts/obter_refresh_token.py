"""
Execute este script UMA VEZ para obter o refresh token do Microsoft.
O token será usado como secret MS_REFRESH_TOKEN no GitHub Actions.

Uso:
    python scripts/obter_refresh_token.py
"""

import requests

CLIENT_ID = "4c19cc34-0c80-4dcd-9d8c-f0e35c0f48b5"
SCOPES    = "https://graph.microsoft.com/Files.Read offline_access"

# ── Inicia device code flow ───────────────────────────────────────────────────
r = requests.post(
    "https://login.microsoftonline.com/common/oauth2/v2.0/devicecode",
    data={"client_id": CLIENT_ID, "scope": SCOPES},
)
r.raise_for_status()
flow = r.json()

print("\n" + "="*60)
print("1. Acesse:", flow["verification_uri"])
print("2. Insira o código:", flow["user_code"])
print("3. Faça login com a conta: flowfinances2026@outlook.com.br")
print("4. Volte aqui e pressione ENTER")
print("="*60)
input("\nPressione ENTER após concluir o login... ")

# ── Troca o device code pelo token ────────────────────────────────────────────
import time
deadline = time.time() + flow.get("expires_in", 900)

while time.time() < deadline:
    resp = requests.post(
        "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        data={
            "grant_type":  "urn:ietf:params:oauth:grant-type:device_code",
            "client_id":   CLIENT_ID,
            "device_code": flow["device_code"],
        },
    )
    data = resp.json()

    if "refresh_token" in data:
        print("\n✅ Token obtido com sucesso!\n")
        print("=" * 60)
        print("ADICIONE ESSES SECRETS NO GITHUB:")
        print("  Repositório → Settings → Secrets and variables → Actions")
        print("=" * 60)
        print(f"\nMS_CLIENT_ID:\n  {CLIENT_ID}")
        print(f"\nMS_REFRESH_TOKEN:\n  {data['refresh_token']}")
        print(f"\nMS_EXCEL_URL:\n  https://1drv.ms/x/c/34eb48bbe5babf33/IQBkkgUSG37eT7AUIIT0EnFIAawdB8KZ6Yx5ypjyblkZbdU?e=DuWAzF")
        print("\n" + "=" * 60)
        break
    elif data.get("error") == "authorization_pending":
        time.sleep(5)
    else:
        print("Erro:", data.get("error_description", data))
        break
