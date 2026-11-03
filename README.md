# Dashboard SB100

Dashboard de infraestrutura e FinOps para explorar métricas de banco de dados, cloud, storage, processamento, tokens e SLA, com filtros interativos, drill-down de recursos e alertas baseados em limites.

## Stack

- React 19 + TypeScript
- Vite 7
- Tailwind CSS 4
- Radix UI + shadcn/ui
- ApexCharts
- Wouter para rotas

## Como rodar

```bash
npm install
npm run dev
```

Acesse http://localhost:5173.

## Scripts

- `npm run dev` — inicia o servidor de desenvolvimento
- `npm start` — alias para `npm run dev`
- `npm run build` — typecheck + build de produção em `dist/`
- `npm run preview` — serve o build de produção localmente
- `npm run typecheck` — verifica os tipos TypeScript

## Estrutura

```text
src/
  components/     componentes de UI e error boundary
  features/       gráficos, filtros, cards e dados mock do dashboard
  pages/          páginas da aplicação
  lib/            utilitários
  App.tsx         rotas e providers
  main.tsx        entrada da aplicação
```

## Observações

- O projeto usa apenas dados mock; não precisa de banco de dados, API ou variáveis de ambiente.
- O favicon fica em `public/`.
