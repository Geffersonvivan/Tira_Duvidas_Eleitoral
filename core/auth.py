"""Gate de autenticação com degradação segura.

Se o Clerk não estiver configurado (CLERK_ENABLED=False), o acesso é liberado
— o site permanece público, como antes de ligar o login.
"""

from functools import wraps

from django.conf import settings
from django.shortcuts import redirect


def autorizado(request) -> bool:
    """Acesso permitido: Clerk desligado (público) ou usuário autenticado."""
    return (not settings.CLERK_ENABLED) or request.user.is_authenticated


def exigir_login(view):
    """Gate para views HTML: sem login (com Clerk ligado) → landing."""

    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        if not autorizado(request):
            return redirect("landing")
        return view(request, *args, **kwargs)

    return _wrapped
