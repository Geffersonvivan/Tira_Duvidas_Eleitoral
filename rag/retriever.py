"""Recuperação do RAG (padrão iterative-retrieval).

Devolve dois conjuntos distintos (lógica.md §4):
- `contexto`: todos os trechos relevantes (inclui doutrina/curso) — para redigir.
- `fontes_citaveis`: só documentos citáveis (norma/jurisprudência válida) — para citar.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date

from django.db import connection
from django.db.models import Q
from django.utils import timezone

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


def filtrar_vigentes(qs, hoje: date | None = None):
    """Remove trechos de documentos revogados ou fora do período de vigência.

    Norma revogada/expirada não pode nem alimentar o CONTEXTO do LLM: redigir
    com base em lei que já não vale induz a resposta ao erro — pior ainda porque
    o modelo pode citar o conteúdo sem que ela apareça em `fontes_citaveis` (que
    já filtra por `pode_citar`). Doutrina/curso (vigente=True, sem datas) seguem
    no contexto — são apoio válido para a redação, apenas não citáveis.
    """
    hoje = hoje or timezone.now().date()
    return qs.filter(
        Q(documento__vigente=True)
        & (Q(documento__vigencia_inicio__isnull=True) | Q(documento__vigencia_inicio__lte=hoje))
        & (Q(documento__vigencia_fim__isnull=True) | Q(documento__vigencia_fim__gte=hoje))
    )


def buscar(
    query_embedding: list[float],
    *,
    assunto: str | None = None,
    k: int = 8,
) -> Recuperacao:
    """Busca semântica top-k por distância de cosseno (requer Postgres/pgvector).

    O `assunto` é usado como filtro **preferencial**, não rígido: se filtrar por
    ele não trouxer nada (ex.: classificação e tag não batem), refaz a busca em
    todos os assuntos. Assim evita o "Ausência de Contexto" quando a pergunta
    cai num assunto diferente do que o documento relevante está marcado.

    Documentos fora de vigência são excluídos antes da ordenação (ver
    `filtrar_vigentes`) — nunca entram no contexto nem nas fontes.
    """
    if connection.vendor != "postgresql":
        raise NotImplementedError(
            "Busca vetorial requer Postgres com pgvector (DATABASE_URL=postgres://...)."
        )

    from pgvector.django import CosineDistance  # import tardio: só no caminho Postgres

    base = filtrar_vigentes(Trecho.objects.select_related("documento").exclude(embedding=None))

    def ordenar(qs):
        return list(qs.order_by(CosineDistance("embedding", query_embedding))[:k])

    trechos = []
    if assunto:
        trechos = ordenar(base.filter(documento__assunto=assunto))
    if not trechos:
        trechos = ordenar(base)  # fallback: todos os assuntos
    return separar_por_citabilidade(trechos)
