"""Views do billing: página de planos, checkout (redirect) e webhook do Stripe."""

import logging

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from billing import gate, services
from billing.plans import ESSENCIAL, PRO, plano_do

_log = logging.getLogger(__name__)


@require_GET
def planos_view(request):
    """Página de planos: 2 passes (Essencial/Profissional) + consultoria WhatsApp."""
    prof = getattr(request.user, "profile", None) if request.user.is_authenticated else None
    ctx = {
        "essencial": plano_do(ESSENCIAL),
        "pro": plano_do(PRO),
        "whatsapp": settings.BILLING_WHATSAPP,
        "sucesso": request.GET.get("sucesso") == "1",
        "cancelado": request.GET.get("cancelado") == "1",
        "acesso_ate": services.acesso_ate(),
        "plano_atual": gate.plano_efetivo(prof) if prof else None,
        "perguntas_restantes": gate.restante(prof, gate.PERGUNTAS) if prof else None,
    }
    return render(request, "billing/planos.html", ctx)


@require_GET
def checkout_view(request):
    """Cria a sessão Stripe e redireciona para o checkout hospedado."""
    if not request.user.is_authenticated:
        return redirect("/")
    if not settings.BILLING_ENABLED:
        return HttpResponse("Pagamento indisponível no momento.", status=503)

    plan_key = request.GET.get("plan", ESSENCIAL)
    if plan_key not in (ESSENCIAL, PRO):
        plan_key = ESSENCIAL
    try:
        url = services.criar_checkout_session(
            request.user, plan_key, request.build_absolute_uri("/").rstrip("/")
        )
    except Exception:
        _log.exception("Falha ao criar checkout Stripe")
        return HttpResponse("Erro ao gerar o checkout. Tente novamente.", status=502)
    return redirect(url)


@csrf_exempt
@require_POST
def stripe_webhook(request):
    """Recebe eventos do Stripe, verifica a assinatura e processa (idempotente)."""
    import stripe

    secret = settings.STRIPE_WEBHOOK_SECRET
    if not secret:
        _log.error("STRIPE_WEBHOOK_SECRET não configurado")
        return HttpResponse(status=400)

    sig = request.headers.get("Stripe-Signature", "")
    try:
        event = stripe.Webhook.construct_event(request.body, sig, secret)
    except (ValueError, stripe.error.SignatureVerificationError):
        return HttpResponse(status=400)  # fail-closed

    try:
        resultado = services.processar_evento(event)
    except Exception:
        _log.exception("Erro ao processar webhook Stripe")
        return JsonResponse({"erro": "falha interna"}, status=500)
    return JsonResponse({"resultado": resultado})
