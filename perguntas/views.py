"""API do Serviço 1 — Perguntas eleitorais (lógica.md §4)."""

from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from perguntas import services
from perguntas.serializers import FonteSerializer, PerguntaInputSerializer


@api_view(["POST"])
def perguntar(request: Request) -> Response:
    entrada = PerguntaInputSerializer(data=request.data)
    entrada.is_valid(raise_exception=True)

    resultado = services.responder_pergunta(entrada.validated_data["pergunta"])

    return Response(
        {
            "on_topic": resultado.on_topic,
            "assunto": resultado.assunto,
            "texto": resultado.texto,
            "disclaimer": resultado.disclaimer,
            "fontes": FonteSerializer(resultado.fontes, many=True).data,
        }
    )
