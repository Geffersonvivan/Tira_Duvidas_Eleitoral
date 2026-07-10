"""Views base do projeto."""

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie


def health(_request: HttpRequest) -> JsonResponse:
    """Healthcheck simples — usado pelo CI e por monitores de deploy."""
    return JsonResponse({"status": "ok", "servico": "tira-duvidas-eleitoral"})


@ensure_csrf_cookie
def home(request: HttpRequest) -> HttpResponse:
    """Página única com as duas abas (Serviços 1 e 2)."""
    return render(request, "index.html")
