# Extrator VW — Guia de Configuração

## O que você vai precisar

| Item | Onde obter |
|------|------------|
| Python 3.9+ | python.org/downloads |
| Chave API Claude | console.anthropic.com |
| Credenciais Google | console.cloud.google.com |
| Planilha no Google Sheets | Importar o Excel existente |

---

## Passo 1 — Instalar o Python

1. Acesse **python.org/downloads** e baixe a versão mais recente
2. Durante a instalação, marque a opção **"Add Python to PATH"**
3. Confirme abrindo o Prompt de Comando e digitando: `python --version`

---

## Passo 2 — Instalar as dependências

Abra o Prompt de Comando, navegue até a pasta do projeto e execute:

```
cd C:\Users\ib.rec17\Desktop\VW-Extractor
pip install -r requirements.txt
```

---

## Passo 3 — Chave da API Claude (Anthropic)

1. Acesse **console.anthropic.com** e faça login
2. Vá em **API Keys** → **Create Key**
3. Copie a chave (começa com `sk-ant-`)
4. Você vai colar essa chave na tela de configurações do app

---

## Passo 4 — Importar sua planilha para o Google Sheets

1. Acesse **sheets.google.com**
2. Clique em **Arquivo → Importar**
3. Selecione o arquivo `Modelo Plan de pagamento.xltm` da sua área de trabalho
4. Escolha **Substituir planilha** e confirme
5. Copie o **ID** da planilha da URL:
   ```
   docs.google.com/spreadsheets/d/[ID_AQUI]/edit
   ```

---

## Passo 5 — Configurar a API do Google Sheets

### 5.1 — Criar projeto no Google Cloud

1. Acesse **console.cloud.google.com**
2. Clique em **Selecionar projeto → Novo projeto**
3. Dê um nome (ex: "Extrator VW") e clique em **Criar**

### 5.2 — Ativar a API do Google Sheets

1. No menu lateral, vá em **APIs e Serviços → Biblioteca**
2. Pesquise por **Google Sheets API**
3. Clique em **Ativar**

### 5.3 — Criar uma Conta de Serviço

1. Vá em **APIs e Serviços → Credenciais**
2. Clique em **+ Criar Credenciais → Conta de serviço**
3. Preencha o nome (ex: "extrator-vw") e clique em **Criar e continuar**
4. Clique em **Concluir**

### 5.4 — Baixar o arquivo JSON

1. Na lista de contas de serviço, clique na que você acabou de criar
2. Vá na aba **Chaves → Adicionar chave → Criar nova chave**
3. Escolha **JSON** e clique em **Criar**
4. O arquivo será baixado — **renomeie para `service_account.json`**
5. Mova esse arquivo para a pasta:
   ```
   C:\Users\ib.rec17\Desktop\VW-Extractor\credentials\service_account.json
   ```

### 5.5 — Compartilhar a planilha com a conta de serviço

1. Abra o arquivo JSON e copie o campo `"client_email"` (ex: `extrator-vw@projeto.iam.gserviceaccount.com`)
2. Abra sua planilha no Google Sheets
3. Clique em **Compartilhar** (canto superior direito)
4. Cole o e-mail da conta de serviço e dê permissão de **Editor**
5. Clique em **Enviar**

---

## Passo 6 — Criar o arquivo .env

1. Na pasta `VW-Extractor`, copie o arquivo `.env.example` e renomeie para `.env`
2. Abra o `.env` e preencha:
   ```
   ANTHROPIC_API_KEY=sk-ant-SUA_CHAVE_AQUI
   SPREADSHEET_ID=ID_DA_SUA_PLANILHA_AQUI
   GOOGLE_CREDENTIALS_PATH=credentials/service_account.json
   ```

---

## Passo 7 — Rodar o aplicativo

Abra o Prompt de Comando na pasta do projeto e execute:

```
cd C:\Users\ib.rec17\Desktop\VW-Extractor
streamlit run app.py
```

O navegador abrirá automaticamente com o sistema.

---

## Uso diário

1. Abra o Prompt de Comando → entre na pasta → rode `streamlit run app.py`
2. Arraste os PDFs dos contratos na tela
3. Clique em **Processar Contratos**
4. Revise a prévia dos dados extraídos
5. Clique em **Inserir na planilha**
6. Pronto — os contratos aparecem como novas linhas na aba do mês atual

---

## Atenção — Aba do mês

O sistema insere os dados automaticamente na aba do **mês atual** (ex: `MAIO 2026`).  
Certifique-se de que a aba já existe na planilha antes de processar.  
A cada início de mês, crie uma nova aba com o nome no formato: `MÊS ANO` (ex: `JUNHO 2026`).
