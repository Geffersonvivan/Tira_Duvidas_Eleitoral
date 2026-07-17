# Tira-Dúvidas Eleitoral (TDE)

Assistente jurídico-eleitoral brasileiro com RAG. Dois serviços:

1. **Perguntas** — dúvidas de direito eleitoral, contabilidade de campanha e
   impulsionamento, respondidas com base num corpus curado (RAG) e citando
   apenas norma e jurisprudência **vigentes**.
2. **Materiais** — análise de peças gráficas de campanha (santinho/PDF) quanto à
   conformidade com a legislação.

Stack: Django 5 + DRF · Postgres/pgvector · embeddings Voyage · LLM Claude
(Anthropic) · auth Clerk (opcional) · deploy Railway.

## Arquitetura em uma tela

```
pergunta → classificar (Haiku) → RAG (Voyage + pgvector, top-k)
         → redigir (Sonnet; escala p/ Opus sem fonte citável)
         → citar só norma/jurisprudência vigente → auditoria de custo
```

Apps: `perguntas`, `materiais` (serviços) · `rag` (ingestão/embeddings/busca) ·
`llm` (wrapper Anthropic, roteamento, orçamento) · `conversas` (histórico) ·
`analytics` (ranqueia dúvidas) · `core` (auth Clerk, health, checks).

Regra **inviolável**: só `norma` e `jurisprudencia` vigentes são citáveis;
doutrina/curso entram como contexto para redigir, nunca como fonte
(`rag/models.py`).

## Setup local

Requisitos: Python 3.12+ (opcional: Postgres+pgvector; sem `DATABASE_URL` usa
SQLite, mas a busca vetorial exige Postgres).

```bash
python -m venv .venv && source .venv/bin/activate
make install                 # deps + pre-commit
cp .env.example .env         # preencha as chaves (ver abaixo)
make migrate
make run                     # http://localhost:8000
```

Variáveis mínimas em `.env`: `ANTHROPIC_API_KEY`, `EMBEDDING_PROVIDER=voyage`,
`VOYAGE_API_KEY`. Sem `CLERK_*` o login fica desligado e o site é público
(degradação segura). Lista completa e comentada em `.env.example`.

## Qualidade

```bash
make check      # lint (ruff) + audit (pip-audit) + testes (pytest)
make test
```

Pre-commit roda ruff + pip-audit a cada commit. CI: `.github/workflows/ci.yml`.

## API (resumo)

| Método | Rota | Descrição |
|---|---|---|
| POST | `/api/perguntas/perguntar/` | Resposta única (JSON) |
| POST | `/api/perguntas/stream/` | Resposta em streaming (ndjson) |
| POST | `/api/materiais/analisar/` | Análise de peças (multipart, lote) |
| GET | `/api/conversas/?limit=&offset=` | Histórico do usuário (paginado) |
| GET·PATCH·DELETE | `/api/conversas/<id>/` | Abrir · renomear · apagar |
| DELETE | `/api/conversas/tudo/` | Apagar tudo (LGPD, direito ao esquecimento) |
| GET | `/health/` | Healthcheck (valida banco + pgvector) |

Endpoints de LLM têm rate limit por usuário/IP e respeitam o teto mensal de
custo (429/503 quando estouram).

## Operação e deploy

Ver **[OPERACAO.md](OPERACAO.md)**: ingestão do corpus (Drive), variáveis do
Railway, expurgo LGPD, calibração do RAG, monitoramento e troubleshooting.
