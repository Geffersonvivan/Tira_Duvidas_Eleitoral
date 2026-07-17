"""API do histórico de conversas (só do próprio usuário)."""

from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from conversas.models import Conversa


def _inteiro(valor, padrao: int, *, minimo: int, maximo: int) -> int:
    try:
        return max(minimo, min(int(valor), maximo))
    except (TypeError, ValueError):
        return padrao


@api_view(["GET"])
def listar(request: Request) -> Response:
    """Lista as conversas do usuário (mais recentes primeiro).

    Paginada por `?limit` (default 50, máx 100) e `?offset` — antes trazia TODAS
    as conversas numa query, o que não escala. Continua devolvendo um array
    (compatível com o frontend); a fatia é aplicada no banco.
    """
    if not request.user.is_authenticated:
        return Response([])
    limite = _inteiro(request.query_params.get("limit"), 50, minimo=1, maximo=100)
    offset = _inteiro(request.query_params.get("offset"), 0, minimo=0, maximo=1_000_000)
    fatia = slice(offset, offset + limite)
    conversas = Conversa.objects.filter(user=request.user, arquivada=False)[fatia]
    return Response(
        [{"id": c.id, "titulo": c.titulo, "atualizado_em": c.atualizado_em} for c in conversas]
    )


@api_view(["DELETE"])
def apagar_todas(request: Request) -> Response:
    """Direito ao esquecimento (LGPD): apaga TODAS as conversas do usuário.

    As perguntas registradas (analytics) são anônimas — não têm vínculo com o
    usuário — então nada nelas identifica quem perguntou para apagar aqui.
    """
    if not request.user.is_authenticated:
        return Response({"detail": "Autenticação necessária."}, status=401)
    apagadas, _ = Conversa.objects.filter(user=request.user).delete()
    return Response({"apagadas": apagadas})


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
