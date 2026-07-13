"""API do histórico de conversas (só do próprio usuário)."""

from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from conversas.models import Conversa


@api_view(["GET"])
def listar(request: Request) -> Response:
    """Lista as conversas do usuário (mais recentes primeiro)."""
    if not request.user.is_authenticated:
        return Response([])
    conversas = Conversa.objects.filter(user=request.user, arquivada=False)
    return Response(
        [{"id": c.id, "titulo": c.titulo, "atualizado_em": c.atualizado_em} for c in conversas]
    )


@api_view(["GET", "PATCH", "DELETE"])
def detalhe(request: Request, pk: int) -> Response:
    """Mensagens de uma conversa; renomear (PATCH); apagar (DELETE)."""
    if not request.user.is_authenticated:
        return Response({"detail": "Autenticação necessária."}, status=401)
    conversa = get_object_or_404(Conversa, pk=pk, user=request.user)

    if request.method == "DELETE":
        conversa.delete()
        return Response(status=204)

    if request.method == "PATCH":
        titulo = (request.data.get("titulo") or "").strip()
        if titulo:
            conversa.titulo = titulo[:200]
            conversa.save(update_fields=["titulo"])
        return Response({"id": conversa.id, "titulo": conversa.titulo})

    mensagens = [
        {
            "papel": m.papel,
            "texto": m.texto,
            "assunto": m.assunto,
            "on_topic": m.on_topic,
            "disclaimer": m.disclaimer,
            "fontes": m.fontes,
        }
        for m in conversa.mensagens.all()
    ]
    return Response({"id": conversa.id, "titulo": conversa.titulo, "mensagens": mensagens})
