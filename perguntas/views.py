"""API do Serviço 1 — Perguntas eleitorais (lógica.md §4)."""

import json
import logging

from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.http import require_POST
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from core.auth import autorizado
from perguntas import services
from perguntas.serializers import FonteSerializer, PerguntaInputSerializer

logger = logging.getLogger(__name__)


@api_view(["POST"])
def perguntar(request: Request) -> Response:
    if not autorizado(request):
        return Response({"detail": "Autenticação necessária."}, status=401)

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


@require_POST
def perguntar_stream(request):
    """Responde em streaming (ndjson): a resposta chega se escrevendo, ao vivo.

    View Django pura (não DRF) porque StreamingHttpResponse não combina com o
    ciclo do DRF. Auth via `autorizado`; CSRF pelo middleware padrão do Django."""
    if not autorizado(request):
        return JsonResponse({"detail": "Autenticação necessária."}, status=401)
    try:
        pergunta = (json.loads(request.body).get("pergunta") or "").strip()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"detail": "JSON inválido."}, status=400)
    if not pergunta:
        return JsonResponse({"pergunta": ["Campo obrigatório."]}, status=400)

    def eventos():
        try:
            for ev in services.responder_pergunta_stream(pergunta):
                if ev.get("tipo") == "fim":
                    ev = {**ev, "fontes": FonteSerializer(ev["fontes"], many=True).data}
                yield json.dumps(ev, ensure_ascii=False) + "\n"
        except Exception:
            logger.exception("Erro no stream de perguntas")
            erro = {"tipo": "erro", "texto": "Erro ao consultar. Tente novamente."}
            yield json.dumps(erro) + "\n"

    resp = StreamingHttpResponse(eventos(), content_type="application/x-ndjson")
    resp["X-Accel-Buffering"] = "no"  # evita buffering do proxy (Railway)
    resp["Cache-Control"] = "no-cache"
    return resp
