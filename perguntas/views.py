"""API do Serviço 1 — Perguntas eleitorais (lógica.md §4)."""

import json
import logging

from django.conf import settings
from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.http import require_POST
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from core import ratelimit
from core.auth import autorizado
from llm import budget
from llm.client import LLMIndisponivel
from perguntas import services
from perguntas.serializers import FonteSerializer, PerguntaInputSerializer

logger = logging.getLogger(__name__)

MSG_RATE_LIMIT = "Muitas perguntas em pouco tempo. Aguarde um instante e tente de novo."
MSG_ORCAMENTO = "O serviço atingiu o limite de uso do período. Tente novamente mais tarde."
MSG_INDISPONIVEL = "O assistente está temporariamente indisponível. Tente novamente em instantes."


def _bloqueio_de_uso(request):
    """Portões de custo/abuso comuns aos dois endpoints. Retorna (motivo, status) ou None."""
    if ratelimit.limite_excedido(
        request, escopo="perguntas", limite=settings.RATE_LIMIT_PERGUNTAS_POR_MIN
    ):
        return MSG_RATE_LIMIT, 429
    if not budget.dentro_do_orcamento():
        return MSG_ORCAMENTO, 503
    return None


@api_view(["POST"])
def perguntar(request: Request) -> Response:
    if not autorizado(request):
        return Response({"detail": "Autenticação necessária."}, status=401)

    bloqueio = _bloqueio_de_uso(request)
    if bloqueio:
        return Response({"detail": bloqueio[0]}, status=bloqueio[1])

    entrada = PerguntaInputSerializer(data=request.data)
    entrada.is_valid(raise_exception=True)

    try:
        resultado = services.responder_pergunta(entrada.validated_data["pergunta"])
    except LLMIndisponivel:
        logger.warning("LLM indisponível ao responder pergunta")
        return Response({"detail": MSG_INDISPONIVEL}, status=503)

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

    bloqueio = _bloqueio_de_uso(request)
    if bloqueio:
        return JsonResponse({"detail": bloqueio[0]}, status=bloqueio[1])

    try:
        corpo = json.loads(request.body)
        pergunta = (corpo.get("pergunta") or "").strip()
        conversa_id = corpo.get("conversa_id")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"detail": "JSON inválido."}, status=400)
    if not pergunta:
        return JsonResponse({"pergunta": ["Campo obrigatório."]}, status=400)

    # Histórico: só persiste com usuário autenticado (público não tem dono).
    conversa = nova_conversa = None
    if request.user.is_authenticated:
        from conversas.models import Mensagem
        from conversas.services import get_or_create_conversa, salvar_mensagem

        conversa, nova_conversa = get_or_create_conversa(request.user, conversa_id, pergunta)
        salvar_mensagem(conversa, Mensagem.Papel.USUARIO, pergunta)

    def eventos():
        partes, meta = [], {"assunto": "", "on_topic": True, "disclaimer": "", "fontes": []}
        if conversa is not None:
            ini = {
                "tipo": "conversa",
                "id": conversa.id,
                "titulo": conversa.titulo,
                "nova": nova_conversa,
            }
            yield json.dumps(ini, ensure_ascii=False) + "\n"
        try:
            for ev in services.responder_pergunta_stream(pergunta):
                if ev.get("tipo") == "meta":
                    meta["assunto"] = ev.get("assunto") or ""
                    meta["on_topic"] = ev.get("on_topic", True)
                elif ev.get("tipo") == "delta":
                    partes.append(ev["texto"])
                elif ev.get("tipo") == "fim":
                    ev = {**ev, "fontes": FonteSerializer(ev["fontes"], many=True).data}
                    meta["disclaimer"] = ev.get("disclaimer") or ""
                    meta["fontes"] = ev["fontes"]
                yield json.dumps(ev, ensure_ascii=False) + "\n"
            # resposta completa: grava no histórico
            if conversa is not None and partes:
                from conversas.models import Mensagem
                from conversas.services import salvar_mensagem

                salvar_mensagem(conversa, Mensagem.Papel.ASSISTENTE, "".join(partes), **meta)
        except LLMIndisponivel:
            logger.warning("LLM indisponível no stream de perguntas")
            yield json.dumps({"tipo": "erro", "texto": MSG_INDISPONIVEL}) + "\n"
        except Exception:
            logger.exception("Erro no stream de perguntas")
            erro = {"tipo": "erro", "texto": "Erro ao consultar. Tente novamente."}
            yield json.dumps(erro) + "\n"

    resp = StreamingHttpResponse(eventos(), content_type="application/x-ndjson")
    resp["X-Accel-Buffering"] = "no"  # evita buffering do proxy (Railway)
    resp["Cache-Control"] = "no-cache"
    return resp
