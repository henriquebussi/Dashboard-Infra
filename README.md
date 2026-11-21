# Dashboard SB100 — GCP FinOps Observatory

Dashboard de infraestrutura e FinOps para explorar métricas de banco de dados, cloud, storage, processamento, tokens e SLA, com filtros interativos, drill-down de recursos e alertas baseados em limites.

O projeto é dividido em:

- **Frontend** — React 19 + TypeScript + Vite (este repositório, pasta `src/`)
- **Backend** — FastAPI + Pydantic (pasta `routers/`, `services/`, `schemas.py`)
- **Integração** — o frontend consome a API em `/api/v1`; em desenvolvimento o Vite faz proxy de `/api` para `http://localhost:8000`

## Organização por fonte

O modo Real inclui um inventário de **Qdrant, Google Cloud Platform (GCP), Servidor Interno e Tokens Locais**, preservando as categorias e consultas existentes. GCP e Qdrant possuem coleta externa implementada; health da aplicação não é telemetria do host e tokens Vertex AI não são tokens locais. O inventário não confirma acesso remoto nem adiciona dados simulados.

Consulte [métricas por fonte](src/lib/metricSources.ts) e [orientações para agentes](AGENTS.md).

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

### O que a integração consegue ler

Com `roles/monitoring.viewer`, o dashboard consulta séries temporais de Compute Engine (CPU, rede e disco), Cloud SQL (consultas, conexões, CPU e replicação), Cloud Storage (bytes, objetos e requisições), BigQuery (jobs e consultas), Vertex AI (tokens) e métricas de disponibilidade/saturação derivadas dessas séries. Cada leitura informa a origem (`gcp` ou `cache`), o tipo de métrica e se há dados disponíveis. Os indicadores de Storage publicados diariamente usam uma janela mínima de 24 horas, inclusive quando o filtro do painel é 1 hora.

Com `roles/logging.viewer`, as rotas de Cloud Logging podem ler consultas lentas do Cloud SQL, eventos de Vertex AI e logs de erro, dentro dos limites de entradas de cada rota. Uma contagem limitada é indicada como piso mínimo, e falhas de leitura dos logs não são tratadas como contagem zero.

As permissões acima **não** dão acesso ao faturamento: custo de infraestrutura e custo por modelo ficam indisponíveis. Não há conector nem fonte de billing configurados neste checkout; permissões adicionais, isoladamente, não ativam custos. Também ficam indisponíveis percentuais de capacidade de buckets (não há capacidade fixa), latência sem métrica de duração, taxa de erro sem total correspondente de requisições e disponibilidade de VMs calculada apenas a partir de segundos de uptime. Métricas de memória e uso de filesystem da VM dependem do Ops Agent; tipos específicos de BigQuery, Cloud SQL e Vertex AI dependem dos serviços e telemetria realmente presentes no projeto.

Use `GCP_PROJECT_MAP=PROD:projeto-prod,STAGING:projeto-staging,DEV:projeto-dev` para separar ambientes por projeto. As consultas e o cache usam o projeto resolvido para cada ambiente. Sem esse mapa, o painel usa `GCP_PROJECT_ID` e sinaliza que mostra um único projeto. `GCP_ENV_LABEL` só deve ser configurado se o recurso monitorado realmente tiver esse label e os ambientes compartilharem o mesmo projeto.

Para confirmar permissões efetivas, execute `scripts/check_gcp.py` em um ambiente com acesso à API. Carregar ADC confirma a identidade local, mas apenas as consultas remotas de Monitoring e Logging confirmam acesso; um timeout de rede deixa essa verificação pendente.

No modo Real, abra **Explorar métricas do Cloud Monitoring**. O catálogo começa pelos tipos com atividade recente (cerca de 25 horas). Desmarque a opção para incluir todos os descritores, inclusive métricas personalizadas. O catálogo é do projeto. Ao consultar um tipo, as amostras respeitam o projeto, o ambiente configurado e a janela selecionada. Também é possível digitar um tipo conhecido quando a identidade pode ler séries mas não pode listar descritores. A consulta preserva valores, distribuições e rótulos e permite avançar em páginas de até 100 amostras. [Catálogo de descritores](https://cloud.google.com/monitoring/api/ref_v3/rest/v3/projects.metricDescriptors/list) · [Leitura de séries](https://cloud.google.com/monitoring/api/ref_v3/rest/v3/projects.timeSeries/list)

Os endpoints de leitura são `GET /api/v1/gcp/catalog` (parâmetros `env`, `active_only`) e `GET /api/v1/gcp/catalog/series` (`env`, `metric_type`, `period`). O catálogo retorna até 100 descritores por página; use o `next_page_token` como `page_token`, mantendo `env` e `active_only`. Para continuar a leitura de amostras, envie o mesmo `end` e o `next_page_token` recebido como `page_token`, mantendo ambiente, período e tipo de métrica. As permissões correspondentes são `monitoring.metricDescriptors.list`, `monitoring.timeSeries.list` e, para as rotas de logs, `logging.logEntries.list`.

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
pip install -r requirements.lock
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

Para o acesso temporário, use `viewer@dashboard` (leitura) ou `admin@dashboard` (administração), ambos com senha `123`. O login funciona sem arquivo `.env`. A configuração das integrações é independente. Clientes da API também podem usar os tokens Bearer configurados no backend.

O modo real retorna indisponibilidade quando não há integração GCP. Histórico, alertas, overview e relatórios usam demonstração somente com `source=demo`. O cartão de telemetria permite escolher uma métrica ativa do projeto, mostra uma série e guarda a escolha por projeto e ambiente. Regras e auditoria compartilham o SQLite indicado por `DASHBOARD_STATE_DB`. Use um volume persistente para essa base.

## Scripts

- `npm run dev` — inicia o frontend
- `npm run build` — typecheck + build de produção em `dist/`
- `npm run preview` — serve o build de produção localmente
- `npm run typecheck` — verifica os tipos TypeScript
- `.venv/bin/python -m pytest -q` — executa a suíte oficial do backend com o interpretador do projeto.
- Em sandbox com wakeup de asyncio bloqueado por `EPERM`: `.venv/bin/python -m pytest -q --asyncio-poll-interval=0.01`. Essa opção ativa um heartbeat somente nos testes, mantém threads e timeouts e emite aviso explícito.

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

## Qdrant no Banco de dados

No backend, preencha `QDRANT_URL` com o endereço REST da instância de produção e `QDRANT_API_KEY` com uma chave de leitura se a instância exigir autenticação. Para homologação e desenvolvimento, use os mesmos nomes com sufixo `_STAGING` ou `_DEV`. Reinicie o backend. Em Banco de dados, modo Real, selecione Todos os serviços para ver a contagem atual. O cartão consulta a lista de coleções a cada minuto enquanto estiver aberto.
