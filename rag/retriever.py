"""Recuperação do RAG (padrão iterative-retrieval).

Devolve dois conjuntos distintos (lógica.md §4):
- `contexto`: todos os trechos relevantes (inclui doutrina/curso) — para redigir.
- `fontes_citaveis`: só documentos citáveis (norma/jurisprudência válida) — para citar.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field

from django.db import connection

from rag.models import Documento, Trecho


@dataclass
class Recuperacao:
    contexto: list[Trecho] = field(default_factory=list)
    fontes_citaveis: list[Documento] = field(default_factory=list)


def separar_por_citabilidade(trechos: Iterable[Trecho]) -> Recuperacao:
    """Separa contexto (tudo) das fontes citáveis (norma/jurisprudência válida).

    Puro e sem I/O — o coração da regra de citação, fácil de testar.
    """
    trechos = list(trechos)
    vistos: set[int] = set()
    fontes: list[Documento] = []
    for t in trechos:
        doc = t.documento
        if doc.pode_citar and doc.pk not in vistos:
            vistos.add(doc.pk)
            fontes.append(doc)
    return Recuperacao(contexto=trechos, fontes_citaveis=fontes)


def buscar(
    query_embedding: list[float],
    *,
    assunto: str | None = None,
    k: int = 8,
) -> Recuperacao:
    """Busca semântica top-k por distância de cosseno (requer Postgres/pgvector).

    Etapa 1 da recuperação iterativa. A reformulação/re-consulta em caso de baixa
    cobertura é orquestrada na camada de serviço (a implementar no wiring da LLM).
    """
    if connection.vendor != "postgresql":
        raise NotImplementedError(
            "Busca vetorial requer Postgres com pgvector (DATABASE_URL=postgres://...)."
        )

    from pgvector.django import CosineDistance  # import tardio: só no caminho Postgres

    qs = Trecho.objects.select_related("documento").exclude(embedding=None)
    if assunto:
        qs = qs.filter(documento__assunto=assunto)
    trechos = list(qs.order_by(CosineDistance("embedding", query_embedding))[:k])
    return separar_por_citabilidade(trechos)
