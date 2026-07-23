"""Views base do projeto."""

import logging

from django.conf import settings
from django.db import connection
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie

logger = logging.getLogger(__name__)


def health(_request: HttpRequest) -> JsonResponse:
    """Healthcheck — valida banco (e pgvector no Postgres). 503 se o banco cair.

    Antes respondia "ok" mesmo com o banco fora; um monitor não detectava a
    queda. Agora faz um SELECT 1 e, no Postgres, confere a extensão vector.
    """
    detalhes: dict = {"status": "ok", "servico": "tira-duvidas-eleitoral"}
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
            if connection.vendor == "postgresql":
                cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
                linha = cur.fetchone()
                detalhes["pgvector"] = linha[0] if linha else "ausente"
        detalhes["banco"] = "ok"
    except Exception:
        logger.exception("Healthcheck: falha ao acessar o banco")
        return JsonResponse({"status": "degraded", "banco": "erro"}, status=503)
    return JsonResponse(detalhes)


@ensure_csrf_cookie
def home(request: HttpRequest) -> HttpResponse:
    """Ferramenta (Serviços 1 e 2). Servida em /app/; exige login com Clerk ligado."""
    if settings.CLERK_ENABLED and not request.user.is_authenticated:
        return redirect("landing")
    # A publishable key permite carregar o Clerk.js na página e manter o cookie
    # __session renovado (o token de sessão do Clerk é curto).
    ctx = {"CLERK_PUBLISHABLE_KEY": settings.CLERK_PUBLISHABLE_KEY}

    # Chip de cota no header: plano efetivo + perguntas restantes + data de acesso.
    prof = getattr(request.user, "profile", None) if request.user.is_authenticated else None
    if prof is not None:
        from billing import gate
        from billing.plans import plano_do
        from billing.services import acesso_ate

        ctx.update(
            plano_nome=plano_do(gate.plano_efetivo(prof))["nome"],
            perguntas_restantes=gate.restante(prof, "perguntas"),
            acesso_ate=acesso_ate(),
        )
    elif not settings.CLERK_ENABLED:
        # Modo público/local (Clerk desligado): dados de exemplo só para preview.
        from billing.services import acesso_ate

        ctx.update(plano_nome="Profissional", perguntas_restantes=583, acesso_ate=acesso_ate())

    return render(request, "index.html", ctx)
