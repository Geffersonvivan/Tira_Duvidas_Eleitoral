"""Captura e agrupamento das perguntas.

Fluxo de agrupamento (sempre dentro de um mesmo assunto):
  1. IGUAL       — texto normalizado idêntico → soma na contagem.
  2. MESMO SENTIDO — vizinho mais próximo por distância de cosseno (pgvector),
                     abaixo do limiar → soma como "variação".
  3. NOVA DÚVIDA — nada próximo → cria um grupo novo (a pergunta vira canônica).

O passo semântico só roda em Postgres (igual ao rag.retriever); em SQLite o
agrupamento cai para exato + novo grupo, mantendo dev/testes sem pgvector.
"""

import logging
import re
import unicodedata

from django.conf import settings
from django.db import connection, transaction

from analytics.models import GrupoDuvida, PerguntaRegistrada

logger = logging.getLogger(__name__)

# Limiar de distância de cosseno (0 = idêntico, 1 = ortogonal). 0.12 ≈ similaridade
# 0.88. Configurável para calibrar com dados reais.
LIMIAR_DISTANCIA = getattr(settings, "ANALYTICS_LIMIAR_DISTANCIA", 0.12)


def normalizar(texto: str) -> str:
    """Minúsculas, sem acento/pontuação e com espaços colapsados (chave do exato)."""
    txt = unicodedata.normalize("NFKD", texto or "")
    txt = "".join(c for c in txt if not unicodedata.combining(c))
    txt = txt.lower()
    txt = re.sub(r"[^\w\s]", " ", txt)
    return re.sub(r"\s+", " ", txt).strip()


def registrar_pergunta(texto, *, assunto=None, vetor=None, on_topic=True) -> PerguntaRegistrada:
    """Registra a pergunta e a agrupa (se on-topic). Nunca deve derrubar o fluxo
    de resposta — o chamador envolve esta função em proteção."""
    norm = normalizar(texto)
    grupo = _achar_ou_criar_grupo(assunto, texto, norm, vetor) if (on_topic and assunto) else None
    return PerguntaRegistrada.objects.create(
        texto=texto,
        texto_normalizado=norm,
        embedding=vetor,
        assunto=assunto or "",  # off-topic não tem assunto
        on_topic=on_topic,
        grupo=grupo,
    )


def _achar_ou_criar_grupo(assunto, texto, norm, vetor) -> GrupoDuvida:
    with transaction.atomic():
        # (1) IGUAL — dentro do assunto
        g = (
            GrupoDuvida.objects.select_for_update()
            .filter(assunto=assunto, texto_normalizado=norm)
            .first()
        )
        if g:
            g.frequencia += 1
            g.ocorrencias_exatas += 1
            g.save(update_fields=["frequencia", "ocorrencias_exatas", "ultima_ocorrencia"])
            return g

        # (2) MESMO SENTIDO — vizinho mais próximo (só Postgres)
        if connection.vendor == "postgresql" and vetor is not None:
            from pgvector.django import CosineDistance

            near = (
                GrupoDuvida.objects.filter(assunto=assunto, embedding__isnull=False)
                .annotate(dist=CosineDistance("embedding", vetor))
                .order_by("dist")
                .first()
            )
            if near is not None and near.dist <= LIMIAR_DISTANCIA:
                g = GrupoDuvida.objects.select_for_update().get(pk=near.pk)
                g.frequencia += 1
                g.variacoes += 1
                g.save(update_fields=["frequencia", "variacoes", "ultima_ocorrencia"])
                return g

        # (3) NOVA DÚVIDA
        return GrupoDuvida.objects.create(
            assunto=assunto,
            pergunta_canonica=texto,
            texto_normalizado=norm,
            embedding=vetor,
            frequencia=1,
            ocorrencias_exatas=1,
        )


def capturar_seguro(texto, *, assunto=None, vetor=None, on_topic=True) -> None:
    """Wrapper à prova de falhas: registra a pergunta sem nunca propagar erro
    para o fluxo de resposta ao usuário."""
    try:
        registrar_pergunta(texto, assunto=assunto, vetor=vetor, on_topic=on_topic)
    except Exception as e:  # noqa: BLE001 — captura é best-effort, jamais quebra a resposta
        logger.warning("Falha ao registrar pergunta em analytics: %s", e)
