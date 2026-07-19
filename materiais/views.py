"""API do Serviço 2 — Análise de material gráfico (lógica.md §6/§7).

A imagem NÃO é retida após o parecer (LGPD, lógica.md §11.1): os bytes ficam só
em memória durante a análise.
"""

import logging

from django.conf import settings
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response

from billing import gate as billing_gate
from core import ratelimit
from core.auth import autorizado
from llm import budget
from llm.client import LLMIndisponivel
from materiais import services
from materiais.serializers import AnaliseInputSerializer, FonteSerializer

logger = logging.getLogger(__name__)

MSG_RATE_LIMIT = "Muitas análises em pouco tempo. Aguarde um instante e tente de novo."
MSG_ORCAMENTO = "O serviço atingiu o limite de uso do período. Tente novamente mais tarde."
MSG_INDISPONIVEL = "O analisador está temporariamente indisponível. Tente novamente em instantes."


def _serializar(resultado: services.ResultadoAnalise) -> dict:
    if not resultado.on_topic:
        return {"peca": resultado.peca, "on_topic": False, "mensagem": resultado.mensagem}
    p = resultado.parecer
    return {
        "peca": resultado.peca,
        "on_topic": True,
        "status": p.status,
        "pontos": [
            {"descricao": pt.descricao, "conforme": pt.conforme, "fundamento": pt.fundamento}
            for pt in p.pontos
        ],
        "recomendacoes": p.recomendacoes,
        "fontes": FonteSerializer(p.fontes, many=True).data,
        "disclaimer": p.disclaimer,
    }


@api_view(["POST"])
@parser_classes([MultiPartParser])
def analisar(request: Request) -> Response:
    if not autorizado(request):
        return Response({"detail": "Autenticação necessária."}, status=401)

    if ratelimit.limite_excedido(
        request, escopo="materiais", limite=settings.RATE_LIMIT_MATERIAIS_POR_MIN
    ):
        return Response({"detail": MSG_RATE_LIMIT}, status=429)
    if not budget.dentro_do_orcamento():
        return Response({"detail": MSG_ORCAMENTO}, status=503)

    entrada = AnaliseInputSerializer(data=request.data)
    entrada.is_valid(raise_exception=True)
    arquivos = entrada.validated_data["arquivos"]

    # Material é sempre pago (free = 0). Exige cota para todas as peças do lote.
    cota = billing_gate.bloqueio_por_cota(request, billing_gate.MATERIAIS, n=len(arquivos))
    if cota:
        return Response({"detail": cota[0]}, status=cota[1])

    pecas = [(f.name, f.read(), services.media_type(f.name)) for f in arquivos]
    try:
        resultados = services.analisar_lote(pecas)
    except LLMIndisponivel:
        logger.warning("LLM indisponível ao analisar material")
        return Response({"detail": MSG_INDISPONIVEL}, status=503)

    # Consome só as peças efetivamente analisadas (on-topic); off-topic não cobra.
    consumidos = sum(1 for r in resultados if r.on_topic)
    billing_gate.registrar_uso(request, billing_gate.MATERIAIS, n=consumidos)
    return Response({"resultados": [_serializar(r) for r in resultados]})
