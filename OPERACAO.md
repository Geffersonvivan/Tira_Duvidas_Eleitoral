# Operação — Tira-Dúvidas Eleitoral

Guia de quem opera o app em produção (Railway). Setup de dev fica no README.

## Deploy (Railway)

Build por Nixpacks; o boot roda `collectstatic` + `migrate` + `gunicorn`
(`Procfile`/`railway.json`). O Nixpacks já inclui `tesseract`+`poppler` para OCR.

### Variáveis obrigatórias
- `DJANGO_SECRET_KEY` — **obrigatória** em produção. Sem ela, o `manage.py check`
  falha (system check `core.E001`) e o deploy não sobe.
- `DJANGO_DEBUG=False`
- `DATABASE_URL=postgres://…` — Postgres **com a extensão pgvector**.
- `ANTHROPIC_API_KEY`, `EMBEDDING_PROVIDER=voyage`, `VOYAGE_API_KEY`.

`RAILWAY_PUBLIC_DOMAIN` é lido sozinho para `ALLOWED_HOSTS`/`CSRF_TRUSTED_ORIGINS`.

### Recomendadas
- `LLM_MONTHLY_BUDGET_USD` — teto mensal (USD). Estourou, os endpoints de LLM
  respondem 503 até virar o mês. `PRECO_<modelo>=entrada,saida` alimenta o cálculo.
- `RATE_LIMIT_PERGUNTAS_POR_MIN` / `RATE_LIMIT_MATERIAIS_POR_MIN`.
- `SENTRY_DSN` (+ `SENTRY_TRACES_SAMPLE_RATE`) — erros em produção.

Envs ausentes disparam avisos no `manage.py check` (`core.W001/W002`).

## Ingestão do corpus (RAG)

O corpus vem de uma pasta **RAG** no Google Drive, compartilhada (leitura) com uma
conta de serviço. Estrutura: `RAG/<Assunto>/<Natureza>/arquivos`. O 1º nível vira
o `assunto`; o 2º define a natureza (doutrina/curso = contexto não citável).

```bash
python manage.py ingerir_drive            # incremental (md5); reconcilia remoções
python manage.py ingerir_drive --pasta Jurídico   # só um assunto
python manage.py ingerir_drive --so-vazios        # só re-embeda docs com 0 trechos (do cache)
python manage.py ingerir_drive --dry-run          # só lista o que faria
```

Requer `GOOGLE_SERVICE_ACCOUNT_JSON` e `RAG_DRIVE_ROOT_FOLDER_ID`. O texto extraído
(OCR/nativo) é cacheado no banco para não re-OCRar quando o conteúdo não muda. O
OCR é **retomável** (`Documento.ocr_paginas`/`ocr_completo`): se um scan longo cair
no meio, o próximo run continua da última página salva. Ao fim, o comando **lista
docs com 0 trechos** e sugere `--so-vazios`.

### Sincronização automática (cron no Railway) — RECOMENDADO

Hoje a ingestão é **manual**. Rodá-la via `railway ssh` mantido aberto é frágil
(a sessão cai a cada ~10-15 min; livros grandes não terminam numa sessão). A
solução robusta é um **serviço de cron no Railway** que roda a ingestão
server-side (sem limite de sessão) — e mantém o corpus atualizado sozinho.

**Passo a passo (painel do Railway, projeto `Tira-Dúvidas_Eleitoral`):**

1. **New → Service → GitHub Repo** → mesmo repo (`Tira_Duvidas_Eleitoral`).
   Nomeie algo como `rag-sync`.
2. Em **Settings → Deploy → Custom Start Command**, defina:
   ```
   python manage.py ingerir_drive
   ```
   (Sobrescreve o start command do `railway.json`, que é o do web.)
3. Em **Settings → Cron Schedule**, defina o horário. Sugestão diária de
   madrugada (evita concorrer com pico de uso):
   ```
   0 6 * * *
   ```
   (Railway roda o container no horário, executa o comando e encerra quando o
   processo sai — a ingestão incremental é rápida quando nada mudou.)
4. **Variables** — o serviço precisa das MESMAS variáveis do web. Referencie o
   Postgres e replique as chaves:
   - `DATABASE_URL` → referência ao serviço Postgres (rede privada, igual ao web);
   - `ANTHROPIC_API_KEY`, `EMBEDDING_PROVIDER=voyage`, `VOYAGE_API_KEY`;
   - `GOOGLE_SERVICE_ACCOUNT_JSON`, `RAG_DRIVE_ROOT_FOLDER_ID`;
   - (opcional) `VOYAGE_PAUSA` para espaçar embeddings se a cota apertar.
5. O build usa o mesmo `nixpacks.toml` (tesseract+poppler já vêm p/ o OCR).

**Notas:**
- Não precisa `migrate`/`collectstatic` no cron — o web já cuida disso no deploy.
- É seguro rodar junto com o web: a ingestão é incremental e idempotente
  (`update_or_create` por `origem_id`; reconciliação só na varredura completa).
- Para o expurgo LGPD, crie um 2º cron análogo com start command
  `python manage.py expurgar_dados` (ver seção LGPD).

**Vigência:** só documentos `vigente=True` e dentro de `vigencia_inicio/fim` entram
na busca — norma revogada não vira contexto nem citação. Ao subir uma norma que
revoga outra, marque a antiga como não vigente (ou preencha `vigencia_fim`).

## Qualidade do RAG (recall@k)

```bash
python manage.py avaliar_rag --k 8 --min-recall 0.8
```

Roda o golden set (`rag/golden.py`) contra a recuperação e falha se o recall médio
cair abaixo do mínimo — bom para agendar e pegar regressões. **Popule `CASOS` com
perguntas reais** (as mais frequentes do `analytics` são um bom começo) antes de
confiar nos números.

**Threshold de relevância:** `RAG_DISTANCIA_MAX` corta trechos com distância de
cosseno acima do valor (vazio = desligado). Calibre com o golden set antes de
ativar — valor baixo demais derruba contexto útil.

## LGPD — retenção e expurgo

Perguntas registradas (analytics) são **anônimas** (sem vínculo com usuário);
conversas são por usuário e exclusíveis sob demanda (`DELETE /api/conversas/tudo/`).

```bash
python manage.py expurgar_dados --dry-run    # conta o que apagaria
python manage.py expurgar_dados              # apaga além do prazo
```

Prazos: `LGPD_RETENCAO_PERGUNTAS_DIAS` e `LGPD_RETENCAO_CONVERSAS_DIAS`
(`0` = desligado). Agende no cron/Railway. Os grupos agregados do analytics são
preservados.

## Monitoramento e troubleshooting

- **Saúde:** `GET /health/` retorna 503 se o banco cair; no Postgres inclui a
  versão do pgvector.
- **Índice vetorial:** a migration `0005` cria índice HNSW (Postgres). Se o
  pgvector for < 0.5, ela registra aviso e segue — a busca funciona, só mais
  lenta. Atualize a extensão para reativar o índice.
- **Rate limit por worker:** com o cache padrão, o teto é por processo do
  gunicorn. Para um teto global, configure um cache compartilhado (Redis) em
  `CACHES`.
- **Custo alto / 503 nos endpoints:** confira `LLM_MONTHLY_BUDGET_USD` e o gasto
  do mês (`llm_consumollm`). Escalonamento para Opus ocorre quando o RAG não traz
  fonte citável — sinal de que o corpus pode ter lacuna.
