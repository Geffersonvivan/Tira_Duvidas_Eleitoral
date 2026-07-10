# Corpus do RAG — legislação eleitoral

Aqui ficam as fontes que alimentam o RAG. Cada documento é descrito num
**manifesto JSON**; o texto pode ir inline (`texto`) ou num arquivo (`arquivo`).

## Formato do manifesto

```json
[
  {
    "titulo": "Lei nº 9.504/1997 — art. 57-C",
    "tipo": "norma",                  // norma | jurisprudencia | doutrina | curso | anexo
    "assunto": "impulsionamento",     // direito | contabilidade | impulsionamento
    "vigente": true,
    "fonte_url": "https://...",
    "arquivo": "textos/lei-9504-art-57c.txt"   // ou use "texto": "..."
  }
]
```

## Regra de citação (importante)
- `norma` e `jurisprudencia` → **citáveis** (aparecem como fonte nas respostas).
- `doutrina`, `curso`, `anexo` → **só contexto** (ajudam a redigir, nunca são citados).

## Como ingerir

Com o CLI da Railway linkado ao serviço web (usa as variáveis de produção —
banco pgvector + Voyage automaticamente):

```bash
railway run python manage.py ingerir corpus/manifesto.json
```

Ou apontando manualmente para produção:

```bash
DATABASE_URL='<url do pgvector>' EMBEDDING_PROVIDER=voyage VOYAGE_API_KEY='pa-...' \
  python manage.py ingerir corpus/manifesto.json
```

Re-executar atualiza os documentos e re-indexa os trechos (idempotente).
