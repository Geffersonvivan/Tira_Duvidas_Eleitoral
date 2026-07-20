"""Regras do billing: data de acesso, criação de checkout e processamento de
webhook (idempotente). A view só faz HTTP + verificação de assinatura.
"""

import datetime
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from billing import gate
from billing.models import EventoStripe, Pagamento
from billing.plans import PLANS, plano_do

_log = logging.getLogger(__name__)
User = get_user_model()


def acesso_ate() -> datetime.datetime:
    """Fim do acesso (fixo p/ todos): BILLING_ACESSO_ATE, default 2026-10-05
    (dia seguinte ao 1º turno de 04/10/2026)."""
    raw = getattr(settings, "BILLING_ACESSO_ATE", "2026-10-05")
    d = datetime.date.fromisoformat(raw)
    return timezone.make_aware(datetime.datetime(d.year, d.month, d.day, 23, 59, 59))


def criar_checkout_session(user, plan_key: str, base_url: str) -> str:
    """Cria uma sessão Stripe Checkout (pagamento ÚNICO) e devolve a URL."""
    import stripe

    stripe.api_key = settings.STRIPE_SECRET_KEY
    plano = PLANS.get(plan_key)
    if not plano or not plano["is_paid"]:
        raise ValueError(f"Plano inválido para checkout: {plan_key}")

    email = user.email or f"user_{user.id}@tiraduvidaseleitoral.com.br"
    session = stripe.checkout.Session.create(
        mode="payment",  # passe único (sem mensalidade)
        payment_method_types=["card"],
        customer_email=email,
        client_reference_id=str(user.id),
        metadata={"plan_key": plan_key},
        line_items=[
            {
                "price_data": {
                    "currency": "brl",
                    "product_data": {
                        "name": f"TDE — Passe {plano['nome']}",
                        "description": "Acesso ao TDE até o fim do ciclo eleitoral.",
                    },
                    "unit_amount": int(round(plano["preco"] * 100)),
                },
                "quantity": 1,
            }
        ],
        success_url=f"{base_url}/planos/?sucesso=1",
        cancel_url=f"{base_url}/planos/?cancelado=1",
    )
    return session.url


def _ativar_passe(user, plan_key: str, session: dict) -> None:
    plano = plano_do(plan_key)
    ate = acesso_ate()
    profile = user.profile
    profile.plano = plan_key
    profile.is_pro = True
    profile.subscription_status = "active"
    profile.subscription_expires_at = ate
    profile.stripe_customer_id = session.get("customer") or profile.stripe_customer_id
    profile.save(
        update_fields=[
            "plano",
            "is_pro",
            "subscription_status",
            "subscription_expires_at",
            "stripe_customer_id",
        ]
    )
    gate.resetar_cota(profile)  # zera o consumo do novo período
    Pagamento.objects.create(
        user=user,
        plano=plan_key,
        valor=plano["preco"],
        stripe_session_id=session.get("id", ""),
        stripe_customer_id=session.get("customer") or "",
        acesso_ate=ate,
    )
    _log.info("Passe ativado: user=%s plano=%s ate=%s", user.id, plan_key, ate.date())


def processar_evento(event) -> str:
    """Processa um evento do Stripe JÁ verificado. Idempotente (via event.id).

    Devolve um rótulo do que fez ('ignorado'|'duplicado'|'ativado'|'sem_pagamento').
    Recebe `event` como objeto/dict do stripe.
    """
    event_id = event.get("id")
    tipo = event.get("type")
    if not event_id:
        return "ignorado"

    _, criado = EventoStripe.objects.get_or_create(event_id=event_id, defaults={"tipo": tipo or ""})
    if not criado:
        return "duplicado"  # Stripe reenviou — não reprocessa

    if tipo not in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        return "ignorado"

    session = event["data"]["object"]
    if session.get("payment_status") != "paid":
        return "sem_pagamento"

    user_id = session.get("client_reference_id")
    plan_key = (session.get("metadata") or {}).get("plan_key")
    if not user_id or plan_key not in PLANS:
        _log.warning("Webhook sem user/plano válido: %s", session.get("id"))
        return "ignorado"

    try:
        with transaction.atomic():
            user = User.objects.select_for_update().get(id=user_id)
            _ativar_passe(user, plan_key, session)
    except User.DoesNotExist:
        _log.error("Webhook: usuário %s não existe", user_id)
        return "ignorado"
    return "ativado"
