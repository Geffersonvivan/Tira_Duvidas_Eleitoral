"""API do Serviço 2 — Análise de material gráfico (lógica.md §6/§7).

A imagem NÃO é retida após o parecer (LGPD, lógica.md §11.1): os bytes ficam só
em memória durante a análise.
"""

from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response

from materiais import services
from materiais.serializers import AnaliseInputSerializer, FonteSerializer


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
    entrada = AnaliseInputSerializer(data=request.data)
    entrada.is_valid(raise_exception=True)

    pecas = [
        (f.name, f.read(), services.media_type(f.name)) for f in entrada.validated_data["arquivos"]
    ]
    resultados = services.analisar_lote(pecas)
    return Response({"resultados": [_serializar(r) for r in resultados]})
