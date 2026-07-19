"""Views de autenticação (Clerk) — landing pública, sync de sessão e logout."""

from django.conf import settings
from django.contrib.auth import logout as auth_logout
from django.shortcuts import redirect, render


def _clerk_ctx() -> dict:
    return {"CLERK_PUBLISHABLE_KEY": settings.CLERK_PUBLISHABLE_KEY}


def landing_view(request):
    """Landing pública em `/`. Com Clerk ligado, usuário já logado vai ao app."""
    if settings.CLERK_ENABLED and request.user.is_authenticated:
        return redirect("app")
    # Preços vêm da fonte única (billing.plans) para não desincronizar da /planos.
    from billing.plans import ESSENCIAL, PRO, plano_do
    from billing.services import acesso_ate

    ctx = _clerk_ctx()
    ctx["essencial"] = plano_do(ESSENCIAL)
    ctx["pro"] = plano_do(PRO)
    ctx["acesso_ate"] = acesso_ate()
    ctx["whatsapp"] = settings.BILLING_WHATSAPP
    return render(request, "landing.html", ctx)


def auth_sync_view(request):
    """Interceptora pós-login: grava o cookie __session e vai para /app/."""
    return render(request, "auth_sync.html", _clerk_ctx())


def logout_view(request):
    """Encerra sessão Django + Clerk e volta para a landing."""
    auth_logout(request)
    response = render(request, "logout.html", _clerk_ctx())
    response.delete_cookie("__session")
    return response
