# Arquitetura Técnica — Tira Dúvidas Eleitoral

> Complementa `lógica.md` (regras de decisão do produto). Aqui está **como** implementar
> em Python/Django, e onde cada skill entra. Stack: Django 5 + DRF + Postgres/pgvector +
> Claude (Anthropic SDK).

---

## 1. Qualidade e segurança desde o início

| Ferramenta | Papel | Onde |
|------------|-------|------|
| **ruff** | Lint + format + isort + regras de segurança (bandit) | `pyproject.toml`, pre-commit, CI |
| **pip-audit** | Varre vulnerabilidades nas dependências | `make audit`, pre-commit, CI |
| **pre-commit** | Roda ruff + pip-audit antes de cada commit | `.pre-commit-config.yaml` |
| **CI** | Portão: lint + format-check + audit + testes em todo PR | `.github/workflows/ci.yml` |

Comando único local: `make check` (lint + audit + test). Nenhum código entra sem passar.

---

## 2. Estrutura de apps Django

```
config/                 # settings, urls, wsgi
core/                   # base, disclaimer, auditoria, utils comuns
rag/                    # ingestão, embeddings, recuperação (pgvector)
llm/                    # cliente Claude, roteamento, orçamento, cache
perguntas/              # Serviço 1 (§4) — API /perguntar/
materiais/              # Serviço 2 (§6) — API /analisar/
```

Fluxo comum (ambos os serviços): **gate de intenção → RAG → LLM → citação → auditoria**.

---

## 3. Onde cada skill entra

### 3.1 `iterative-retrieval` → app `rag`
Refinamento iterativo da recuperação antes de chamar a LLM (melhora qualidade nos 3 assuntos).

- **Ingestão** marca cada documento com `citavel: bool`:
  - `citavel=True` → norma e jurisprudência válidas (**podem ser citadas**, §1 da lógica).
  - `citavel=False` → doutrina, cursos, anexos internos (**só contexto, nunca citados**).
- **Retrieve** faz busca vetorial (pgvector), avalia suficiência e **re-consulta** com query
  reformulada se a cobertura for baixa — em vez de um único top-k cego.
- Retorna dois conjuntos separados: `contexto` (tudo) e `fontes_citaveis` (só `citavel=True`).

```
rag/
  ingest.py       # chunk + embed + tag citavel/vigência
  retriever.py    # busca iterativa; devolve (contexto, fontes_citaveis)
  models.py       # Documento(fonte, tipo, citavel, vigencia, embedding)
```

### 3.2 `cost-aware-llm-pipeline` → app `llm`
Roteamento por complexidade, orçamento, retry e cache (§13 da lógica).

| Etapa | Modelo (env) | Racional |
|-------|--------------|----------|
| Classificação de intenção | `MODEL_CLASSIFY` = Haiku 4.5 | simples, alto volume |
| Redação da resposta | `MODEL_ANSWER` = Sonnet 4.6 | precisão jurídica |
| Visão / análise de peça | `MODEL_VISION` = Sonnet 4.6 | imagem + norma |
| Caso complexo/ambíguo | `MODEL_COMPLEX` = Opus 4.8 | escala sob demanda |

- **Orçamento:** teto mensal (`LLM_MONTHLY_BUDGET_USD`); registra custo por chamada.
- **Retry:** backoff em erro transitório (`LLM_MAX_RETRIES`).
- **Cache de prompt:** instruções fixas (system prompt derivado de `lógica.md`) e trechos
  recorrentes do RAG entram em prompt caching para reduzir custo.

```
llm/
  client.py       # wrapper do SDK anthropic
  router.py       # escolhe modelo por complexidade
  budget.py       # contabiliza custo e aplica teto
```

### 3.3 `claude-api` → app `llm`
Referência canônica para IDs de modelo, tool use, visão e prompt caching. **Consultar a skill
antes de fixar preços/limites** — não chutar valores. Uso de visão (Serviço 2) e citação
estruturada saem daí.

### 3.4 `graphify` → app `rag` (reforço opcional, pós-MVP)
Transforma a legislação num grafo de conhecimento (relações norma↔resolução↔jurisprudência).
Complementa a busca vetorial com relações explícitas — útil quando uma resposta depende de
"esta resolução regulamenta aquele artigo".

> **Decisão (RAG em produção):** a **base é Postgres + pgvector no nosso próprio banco** —
> recuperação primária por **busca vetorial** (não grafo). Nenhum serviço externo de RAG:
> dados e embeddings ficam na nossa base. O **grafo é reforço posterior**, fora do escopo
> do MVP; quando entrar, de preferência **dentro do mesmo Postgres** (tabelas de relação /
> `ltree`), para não multiplicar infraestrutura. Os dois serviços do produto já funcionam
> só com vetorial + a regra de citação.

---

## 4. Fluxo do Serviço 1 — `/perguntar/`

```
POST /perguntar/  {pergunta}
  1. gate de intenção (llm.router → Haiku)         # §3 lógica
     ├─ off-topic → resposta descontraída (§5)
     └─ on-topic  ↓
  2. rag.retriever → (contexto, fontes_citaveis)   # iterative-retrieval
  3. llm.router → Sonnet redige ancorado no contexto
  4. monta resposta + fontes (só citaveis) + disclaimer
  5. core.auditoria registra metadados (não o texto sensível)
```

## 5. Fluxo do Serviço 2 — `/analisar/`

```
POST /analisar/  {arquivos[]}   # JPG/PNG/PDF, lote
  para cada peça:
  0. gate: é material de campanha BR? (visão)       # §6 lógica
  1. valida formato/legibilidade (pillow/pypdf)
  2. extrai conteúdo (visão Sonnet + OCR)
  3. rag.retriever → regras aplicáveis
  4. llm confronta peça × regras
  5. parecer: 1 dos 4 status + fundamentos + fontes citaveis + disclaimer
  6. auditoria (metadados; imagem NÃO retida — §11.1 lógica)
```

---

## 6. Princípios não-negociáveis (herdados da lógica)

- **Citação:** só `citavel=True` (norma/jurisprudência válida) chega ao campo de fontes.
- **Anonimato do material de apoio (LGPD) — INVIOLÁVEL:** a resposta **nunca**
  revela a procedência do conteúdo de contexto (doutrina, livros, apostilas, cursos —
  ex.: o corpus do Drive). É **terminantemente proibido**, sob qualquer forma, citar,
  nomear, transcrever ou aludir a: **nome de curso, autor(es), professor(es), editora,
  obra/título, edição, ISBN, URL/arquivo de origem** ou **qualquer dado pessoal ou
  particular** presente no material. Aproveita-se **única e exclusivamente o conteúdo
  (o conhecimento/raciocínio)** — a origem jamais aparece na resposta. As **únicas**
  fontes que podem ser nomeadas são **norma e jurisprudência válidas** (`citavel=True`),
  e só pelo campo de fontes citáveis. Na dúvida sobre identificar algo, **omitir**.
  Vale para o texto da resposta, o campo de fontes, exemplos e qualquer metadado exposto.
- **Grounded first:** sem base no RAG → incerteza (§8), nunca invenção.
- **LGPD:** imagem descartada após o parecer (salvo consentimento); auditoria só de metadados.
- **Escopo:** fora dos 3 assuntos → recusa descontraída.

---

## 7. Decisões e pendências técnicas

**Decidido:**
- **RAG em produção:** Postgres + pgvector no nosso banco; busca vetorial como recuperação
  primária (§3.4). Grafo (`graphify`) fica como reforço pós-MVP, dentro do mesmo Postgres.

- **Embeddings:** Voyage AI (`voyage-3`, 1024 dims — casa com `EMBEDDING_DIM`).
  Integração em `rag/embeddings.py` (rede mockada nos testes); ingestão em `rag/ingest.py`.

- **Corpus do Drive (fonte viva):** `manage.py ingerir_drive` sincroniza a pasta RAG do
  Google Drive (1º nível = assunto; 2º = natureza). Doutrina/curso entram como **contexto
  não citável** e **anonimizado** (§6): servem só para redigir, nunca como fonte nem com
  identificação de origem. PDFs escaneados passam por OCR (tesseract) e o texto é cacheado
  em `Documento.texto_extraido` (nunca re-OCRa). Incremental por md5; reconcilia remoções.

**A detalhar:**
1. Índice pgvector (HNSW) e afinação do top-k — migração Postgres-only.
2. Estratégia de OCR (visão nativa do Claude já cobre; avaliar OCR dedicado p/ baixa qualidade).
3. Processo operacional de ingestão do RAG e versionamento das fontes.
4. Autenticação/perfis (perfil único no MVP — §15 lógica).
