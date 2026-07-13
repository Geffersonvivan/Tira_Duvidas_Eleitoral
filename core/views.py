"""Views base do projeto."""

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie


def health(_request: HttpRequest) -> JsonResponse:
    """Healthcheck simples — usado pelo CI e por monitores de deploy."""
    return JsonResponse({"status": "ok", "servico": "tira-duvidas-eleitoral"})


@ensure_csrf_cookie
def home(request: HttpRequest) -> HttpResponse:
    """Ferramenta (Serviços 1 e 2). Servida em /app/; exige login com Clerk ligado."""
    if settings.CLERK_ENABLED and not request.user.is_authenticated:
        return redirect("landing")
    # A publishable key permite carregar o Clerk.js na página e manter o cookie
    # __session renovado (o token de sessão do Clerk é curto).
    return render(request, "index.html", {"CLERK_PUBLISHABLE_KEY": settings.CLERK_PUBLISHABLE_KEY})
