"""Captura e agrupamento das perguntas.

Fluxo de agrupamento (sempre dentro de um mesmo assunto):
  1. IGUAL       — texto normalizado idêntico → soma na contagem.
  2. MESMO SENTIDO — vizinho mais próximo por distância de cosseno (pgvector),
                     abaixo do limiar → soma como "variação".
  3. NOVA DÚVIDA — nada próximo → cria um grupo novo (a pergunta vira canônica).

O passo semântico só roda em Postgres (igual ao rag.retriever); em SQLite o
agrupamento cai para exato + novo grupo, mantendo dev/testes sem pgvector.
"""

import json
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


# ---------------------------------------------------------------------------
# Reagrupamento por intenção (passada offline com LLM)
#
# O embedding do voyage-3, sozinho, não aproxima paráfrases pesadas (ex.:
# "impulsionar publicação" vs "pagar para promover post" ficam a ~0.43 de
# distância). Esta passada usa o Haiku para fundir grupos de MESMO SENTIDO
# dentro de um assunto — o que o vetor não pega. Roda em lote (barato: uma
# chamada por assunto, sobre os grupos, não sobre cada pergunta).
# ---------------------------------------------------------------------------
def _extrair_json(texto: str) -> dict:
    """Extrai o objeto JSON da resposta do modelo, tolerando cercas e texto ao redor."""
    txt = texto.strip()
    if txt.startswith("```"):
        txt = re.sub(r"^```(?:json)?|```$", "", txt, flags=re.MULTILINE).strip()
    ini, fim = txt.find("{"), txt.rfind("}")
    if ini == -1 or fim == -1:
        raise ValueError("sem JSON na resposta")
    return json.loads(txt[ini : fim + 1])


def clusterizar_haiku(perguntas: list[str]) -> list[list[int]]:
    """Pede ao Haiku para agrupar as perguntas por intenção. Retorna listas de
    índices (cada índice em exatamente um grupo). Em falha, devolve tudo separado
    (nenhuma fusão) — degradação segura."""
    from llm import budget, client
    from llm.config import Tarefa
    from llm.router import escolher_modelo

    modelo = escolher_modelo(Tarefa.CLASSIFICAR)  # Haiku
    lista = "\n".join(f"{i}. {p}" for i, p in enumerate(perguntas))
    system = (
        "Você agrupa perguntas de eleitores por INTENÇÃO. Perguntas que buscam a "
        "MESMA resposta ficam no mesmo grupo, mesmo com palavras diferentes; "
        "perguntas com respostas distintas ficam separadas. Responda SOMENTE JSON "
        'no formato {"grupos": [[indices]...]}, com cada índice em exatamente um grupo.'
    )
    try:
        resp = client.completar(
            modelo, system, [{"role": "user", "content": f"PERGUNTAS:\n{lista}"}], max_tokens=1200
        )
        budget.registrar_uso(modelo, Tarefa.CLASSIFICAR, resp.tokens_entrada, resp.tokens_saida)
        grupos = _extrair_json(resp.texto).get("grupos", [])
        # sanidade: só listas de inteiros válidos
        return [[i for i in g if isinstance(i, int) and 0 <= i < len(perguntas)] for g in grupos]
    except Exception as e:  # noqa: BLE001 — sem fusão em caso de falha
        logger.warning("clusterizar_haiku falhou: %s", e)
        return [[i] for i in range(len(perguntas))]


def reagrupar_por_intencao(assunto: str, *, clusterizar=None) -> int:
    """Funde, dentro do assunto, grupos que o LLM aponta como mesmo sentido.
    Retorna quantos grupos foram fundidos (removidos)."""
    clusterizar = clusterizar or clusterizar_haiku
    grupos = list(GrupoDuvida.objects.filter(assunto=assunto).order_by("-frequencia"))
    if len(grupos) < 2:
        return 0

    clusters = clusterizar([g.pergunta_canonica for g in grupos])
    fundidos = 0
    usados: set[int] = set()
    with transaction.atomic():
        for idxs in clusters:
            idxs = [i for i in idxs if i not in usados]
            if len(idxs) < 2:
                usados.update(idxs)
                continue
            membros = [grupos[i] for i in idxs]
            principal = max(membros, key=lambda g: g.frequencia)
            for o in membros:
                if o.pk == principal.pk:
                    continue
                principal.frequencia += o.frequencia
                PerguntaRegistrada.objects.filter(grupo=o).update(grupo=principal)
                o.delete()
                fundidos += 1
            # variações = tudo que não bateu com o texto exato da canônica
            principal.variacoes = principal.frequencia - principal.ocorrencias_exatas
            principal.save(update_fields=["frequencia", "variacoes", "ultima_ocorrencia"])
            usados.update(idxs)
    return fundidos
