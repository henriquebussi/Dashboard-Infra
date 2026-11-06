# Dashboard SB100 — GCP FinOps Observatory

Dashboard de infraestrutura e FinOps para explorar métricas de banco de dados, cloud, storage, processamento, tokens e SLA, com filtros interativos, drill-down de recursos e alertas baseados em limites.

O projeto é dividido em:

- **Frontend** — React 19 + TypeScript + Vite (este repositório, pasta `src/`)
- **Backend** — FastAPI + Pydantic (pasta `routers/`, `services/`, `schemas.py`)
- **Integração** — o frontend consome a API em `/api/v1`; em desenvolvimento o Vite faz proxy de `/api` para `http://localhost:8000`

## Stack

- React 19 + TypeScript
- Vite 7
- Tailwind CSS 4
- Radix UI + shadcn/ui
- ApexCharts
- Wouter para rotas
- FastAPI + Uvicorn
- Redis (cache opcional)
- Google Cloud Monitoring / Logging (opcional)

## Configuração do ambiente

Copie o arquivo de exemplo e preencha os valores:

```bash
cp .env.example .env
```

O `.env` é carregado automaticamente pelo backend (via `python-dotenv`) e pelo Vite para as variáveis com prefixo `VITE_`.

Principais variáveis:

```dotenv
# GCP — deixe vazio para usar apenas a API de overview embutida
GCP_PROJECT_ID=
# GOOGLE_APPLICATION_CREDENTIALS=/caminho/para/service-account.json

# Redis (opcional em desenvolvimento)
REDIS_URL=redis://localhost:6379/0

# API
API_HOST=0.0.0.0
API_PORT=8000
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173

# Frontend — vazio usa o proxy do Vite em desenvolvimento
VITE_API_BASE_URL=
VITE_USER_ROLE=INFRA_ADMIN
VITE_METRICS_POLL_MS=30000
VITE_USE_MOCK_DATA=false
```

> O arquivo `.env` está no `.gitignore`. Nunca commite credenciais reais.

## Redis (opcional)

O backend funciona sem Redis — ele entra em **cache-miss mode** e continua respondendo normalmente. Por isso o `.env` local já vem com:

```dotenv
REDIS_ENABLED=false
```

### Opção A — Docker (recomendado)

Se o Docker exigir permissão de `sudo`:

```bash
sudo usermod -aG docker "$USER"
newgrp docker   # ou faça logout/login
```

Depois:

```bash
docker compose up -d redis
docker compose exec redis redis-cli ping   # deve responder PONG
```

Depois altere o `.env`:

```dotenv
REDIS_ENABLED=true
REDIS_URL=redis://localhost:6379/0
```

E reinicie o backend.

Para parar o Redis:

```bash
docker compose down
```

### Opção B — Redis local

```bash
sudo apt update
sudo apt install redis-server
sudo systemctl enable --now redis-server
redis-cli ping   # deve responder PONG
```

Depois defina `REDIS_ENABLED=true` no `.env` e reinicie o backend.

### Opção C — Redis gerenciado (produção)

Use a URL fornecida pelo provedor:

```dotenv
REDIS_ENABLED=true
REDIS_URL=rediss://usuario:senha@host:6380/0
```

### Se o Redis estiver indisponível

Com `REDIS_ENABLED=true` e o Redis fora do ar, o backend continua funcionando, mas registra um aviso. Para silenciar completamente, use `REDIS_ENABLED=false`.

> Alterações no `.env` exigem reiniciar o processo do Uvicorn.

## GCP (métricas ao vivo)

O backend usa o SDK oficial do Google Cloud, que autentica via **Application Default Credentials (ADC)** ou **service account**. Ele **não** usa OAuth Client ID nem API key.

### 1. Use o Project ID correto

No Google Cloud Console, abra o seletor de projetos e copie o **Project ID** — algo como:

```text
meu-projeto-123456
```

Não use:

- `835983746489-xxxx.apps.googleusercontent.com` → isso é um **OAuth Client ID**
- `AIza...` → isso é uma **API key**
- o nome de exibição do projeto

Configure no `.env`:

```dotenv
GCP_PROJECT_ID=meu-projeto-123456
```

### 2. Autentique o backend

**Opção A — ADC (recomendado para desenvolvimento)**

```bash
# Instale o gcloud CLI: https://cloud.google.com/sdk/docs/install
gcloud auth application-default login
gcloud config set project meu-projeto-123456
```

**Opção B — Service account**

Crie uma service account com as roles abaixo, baixe a chave JSON e configure:

```dotenv
GOOGLE_APPLICATION_CREDENTIALS=/caminho/para/service-account.json
```

### 3. Permissões e APIs

A conta usada precisa de:

- `roles/monitoring.viewer`
- `roles/logging.viewer`

E as APIs precisam estar habilitadas no projeto:

```bash
gcloud services enable monitoring.googleapis.com logging.googleapis.com \
  --project=meu-projeto-123456
```

### 4. Valide a conexão

```bash
.venv/bin/python scripts/check_gcp.py
```

O script verifica o formato do Project ID, as credenciais e o acesso à Cloud Monitoring API, mostrando exatamente o que corrigir.

### 5. Reinicie o backend

```bash
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Se o dashboard continuar sem dados ao vivo, consulte:

```bash
curl http://localhost:8000/api/v1/gcp/health
```

## Como rodar

### 1. Backend

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

- API: http://localhost:8000
- Swagger: http://localhost:8000/docs
- Health: http://localhost:8000/health

### 2. Frontend

Em outro terminal:

```bash
npm install
npm run dev
```

Acesse http://localhost:5173.

O frontend chama `/api/v1/...` na mesma origem; o proxy do Vite encaminha para o backend configurado em `VITE_API_BASE_URL` (ou `http://localhost:8000` por padrão).

### Produção

```bash
npm run build
```

Defina `VITE_API_BASE_URL=https://sua-api.exemplo.com` antes do build (ou sirva o `dist/` atrás do mesmo domínio da API).

## Endpoints principais

| Método | Rota | Descrição |
| --- | --- | --- |
| GET | `/api/v1/metrics/overview` | Payload agregado do dashboard (fonte principal do frontend) |
| GET | `/api/v1/metrics/{category}/timeseries` | Série histórica por categoria |
| GET | `/api/v1/alerts/active` | Alertas ativos |
| GET/POST | `/api/v1/thresholds` | Limites customizados (POST restrito a `INFRA_ADMIN`) |
| GET | `/api/v1/audit-logs` | Trilha de auditoria |
| GET | `/api/v1/export?format=csv\|xlsx\|pdf` | Exportação de relatórios |
| GET | `/api/v1/gcp/metrics/{category}` | Métricas ao vivo do GCP (requer `GCP_PROJECT_ID`) |
| GET | `/api/v1/gcp/health` | Saúde do cache Redis + integração GCP |

Todas as requisições enviam o header `X-User-Role` (`VIEW_ONLY` ou `INFRA_ADMIN`) configurado em `VITE_USER_ROLE`.

## Comportamento sem GCP/Redis

- **Sem `GCP_PROJECT_ID`**: o dashboard continua funcionando com os dados agregados de `/api/v1/metrics/overview`.
- **Sem Redis**: o cache é degradado graciosamente; as requisições continuam respondendo.
- **Backend offline**: o frontend exibe os dados de demonstração e indica “Backend indisponível”.

## Scripts

- `npm run dev` — inicia o frontend
- `npm run build` — typecheck + build de produção em `dist/`
- `npm run preview` — serve o build de produção localmente
- `npm run typecheck` — verifica os tipos TypeScript
- `pytest` — executa os testes do backend

## Estrutura

```text
src/
  components/     componentes de UI e error boundary
  features/       gráficos, filtros, cards e dados de demonstração
  lib/            cliente da API, hooks e mapeamento do overview
  pages/          páginas da aplicação
  App.tsx         rotas e providers
  main.tsx        entrada da aplicação
routers/          rotas FastAPI
services/         cache Redis, integração GCP e store de métricas
main.py           aplicação FastAPI
schemas.py        modelos Pydantic
```
