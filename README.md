# Dashboard SB100 — GCP FinOps Observatory

Painel de infraestrutura e FinOps com frontend React/Vite e API FastAPI. O modo **Demo** permite explorar o painel sem configurar serviços externos.

## Contas de acesso local

| E-mail | Senha | Permissão |
| --- | --- | --- |
| `viewer@dashboard` | `123` | Somente leitura |
| `admin@dashboard` | `123` | Administração |

Em um clone novo, as duas contas padrão já estão disponíveis assim que o backend inicia. O backend cadastra as contas no SQLite na primeira inicialização e armazena as senhas como hashes com salt. O acesso local funciona sem cadastro manual e sem arquivo `.env`.

## Instalação

Na raiz do projeto, com Python 3.14 e Node.js 22:

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
npm ci
```

## Como rodar

Abra dois terminais na raiz do projeto.

**Terminal 1 — Backend**

```bash
.venv/bin/python main.py
```

**Terminal 2 — Frontend**

```bash
npm run dev
```

Acesse o [dashboard](http://localhost:5173) ou a [documentação da API](http://localhost:8000/docs). Para parar, pressione **Ctrl+C** em cada terminal.

## Banco de dados local

O backend cria automaticamente o arquivo `dashboard-state.sqlite3` ao iniciar. O SQLite guarda as contas, as regras personalizadas e a trilha de auditoria. Configure `DASHBOARD_STATE_DB` no `.env` para usar outro caminho.

O Git ignora o arquivo padrão. Cada clone começa com seu próprio banco local e as duas contas padrão.

## Integrações opcionais

Se ainda não tiver um arquivo `.env`, copie o [modelo](.env.example).

```bash
cp -n .env.example .env
```

- **GCP** — configure `GCP_PROJECT_ID` ou `GCP_PROJECT_MAP` para projetos separados por ambiente. O backend usa Application Default Credentials (ADC) para Monitoring e Logging. Para diagnosticar a conexão, execute `.venv/bin/python scripts/check_gcp.py --diagnose`.
- **Qdrant** — configure `QDRANT_URL` e, quando exigida, `QDRANT_API_KEY`. Para homologação e desenvolvimento, use os sufixos `_STAGING` e `_DEV`. A contagem de coleções aparece em **Banco de dados → Todos os serviços**, no modo **Real**.
- **Redis** — o cache é opcional. Para ativar, inicie o Redis com `docker compose up -d redis` e defina `REDIS_ENABLED=true` no `.env`.

Reinicie o backend após editar o `.env`. Consulte o [inventário de métricas](METRIC_SOURCES.md) para detalhes sobre dados disponíveis.

## Build e testes

- `npm run build` gera o frontend em `dist/`.
- `.venv/bin/python -m pytest -q` executa os testes do backend.
- `node --test tests/*.test.cjs` executa os testes do frontend.

## Tecnologias utilizadas

- **Frontend** — React 19, TypeScript, Vite, Tailwind CSS, Radix UI, shadcn/ui, ApexCharts e Wouter.
- **Backend** — Python, FastAPI, Pydantic e Uvicorn.
- **Persistência e cache** — SQLite para contas, limites e auditoria. Redis opcional via Docker Compose.
- **Integrações** — Google Cloud Monitoring, Google Cloud Logging e Qdrant.
- **Exportação** — CSV, OpenPyXL para XLSX e ReportLab para PDF.
- **Ferramentas de desenvolvimento** — Antigravity, OpenCode e Codex.
