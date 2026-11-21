# Orientações para agentes — Dashboard-Infra

## Arquitetura e tecnologias

- Monorepositório: frontend React 19/TypeScript, Vite 7, Tailwind 4, Radix/shadcn, ApexCharts e Wouter em `src/`; backend Python/FastAPI/Pydantic em `main.py`, `routers/`, `services/` e `schemas.py`.
- `src/lib/api.ts` define contratos HTTP; `useMetrics.ts` coordena consultas; `overview.ts` converte DTOs em modelos do dashboard. Alias `@/` aponta para `src/`. Vite usa porta 5173 e proxy `/api` para backend 8000.
- `main.py` carrega `.env`, registra rotas `/api/v1` e gerencia lifespan/cache. `services/gcp_service.py` usa ADC, Monitoring, cache e circuit breaker. `log_service.py` acessa Logging. `metric_registry.py` define tipos, unidades, agregações e restrições; `resource_inventory.py` deriva recursos dos labels.
- Redis é opcional; `docker-compose.yml` contém apenas Redis. Não subir serviços ou executar prewarm só para testes unitários. `metrics_store.py` é a fonte demonstrativa em memória, não coleta real do servidor.
- `security.py` aplica RBAC VIEW_ONLY/INFRA_ADMIN e auditoria. Não ampliar permissões, alterar IAM ou divulgar ADC/tokens.

## Fontes e contratos

A taxonomia está em `src/lib/metricSources.ts` e o inventário visível do modo Real em `MetricSourceOverview.tsx`.

1. Qdrant: contagem de coleções via REST, com configuração por ambiente.
2. GCP: seis categorias existentes preservadas. Vertex AI é GCP, não Tokens Locais. Custos sem conector de billing ficam indisponíveis.
3. Servidor Interno: health da aplicação/cache existe, mas não há coleta de CPU/RAM/disco do host.
4. Tokens Locais: sem fonte de eventos/consumo local implementada. Não confundir com token de autenticação ou contagem Vertex AI.

Fonte técnica e proveniência são diferentes. Preserve `source` atual (`gcp`, `cache`, `demo`, `estimated`, `unavailable`); não o substitua pelos quatro nomes de fontes sem evolução explícita de contrato. Não criar amostras para fontes ausentes. Indicador mapeado/listagem de descritor não prova leitura remota.

## Convenções de implementação

- Preserve rotas, filtros de ambiente/período, paginação e modo demonstrativo. Mapeie projetos por ambiente sem misturá-los; fixe `end` entre páginas de séries. Requisições canceladas não podem sobrescrever estado de outro escopo.
- Tipos protobuf devem preservar `false`, zero, int64 em texto, strings e distribuições. Mostre unidade, período e ausência de dados sem inventar conversões.
- `available=false`/`source=unavailable` não representa custo zero. Não preencher séries reais com dados demo/zeros sintéticos. Estimativa precisa de regra explícita e identificação. A origem demonstrativa do payload prevalece sobre defaults individuais.
- Novos coletores entram em `services/`, contratos em `schemas.py`/`src/lib/api.ts`, rotas em `routers/` com segurança atual e testes com chamadas externas controladas. Configuração documentada em `.env.example` sem segredos; não registrar valores de credenciais.
- Mudanças pequenas e baseadas em reprodução. Não alterar dependências, defaults, timeouts de produção ou comportamento de serviços por conveniência dos testes.

## Desenvolvimento e validação

Na raiz, com dependências existentes:

```sh
.venv/bin/python -m pytest -q
npm run typecheck
npm run build
node tests/metric_explorer.test.cjs
node tests/cost_presentation.test.cjs
node tests/metric_sources.test.cjs
git diff --check
```

No sandbox com EPERM no wakeup por socketpair, use `.venv/bin/python -m pytest -q --asyncio-poll-interval=0.01`: heartbeat explícito somente no pytest, threads/exceções/timeouts reais preservados. Não editar stdlib ou produção para fazê-los passar. Testes de JSX virtual não são navegador/E2E.

`npm run dev` e `.venv/bin/python main.py` são os pontos de desenvolvimento (inspecione configuração antes de iniciar). Diagnóstico remoto somente de leitura: `scripts/check_gcp.py --diagnose`; inventário delimitado: `scripts/gcp_inventory.py`. Eles podem falhar por DNS sem comprovar permissões. Não consultar serviços novos/projetos não configurados, habilitar APIs ou disparar queries financeiras sem autorização específica.

## Evidências, arquivos e automação

- Consulte evidências locais em `docs/diagnostics/INFRA002*` a `INFRA006*`; bloqueios de DNS/billing não se tornam sucesso por testes simulados. Documentação local pode estar ignorada por `.gitignore` (`/docs/`); não a trate como automaticamente versionada.
- Não editar retroativamente `log.md`, fila operacional, estado ou logs do monitor. A fila central fica em `../Automacao-Codex/tarefas.md`, fora deste repositório; alteração depende de pedido explícito e permissão do ambiente. Não executar prompts futuros durante sua preparação.
- Respeite alterações pré-existentes. Não fazer reset/clean, publicar, deploy ou ações destrutivas sem autorização. Verifique `git status` antes/depois e relate testes, evidências e pendências reais.
