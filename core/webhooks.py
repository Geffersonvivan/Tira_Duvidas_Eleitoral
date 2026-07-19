"""Webhook do Clerk — sincroniza usuários (portado do PJARI).

Assinatura svix é OBRIGATÓRIA (fail-closed): sem svix ou com assinatura
inválida, o evento é rejeitado. A rota cria/atualiza/apaga usuários; aceitar
sem verificar deixaria o endpoint explorável com eventos forjados.
"""

import logging

from django.conf import settings
from django.contrib.auth.models import User
from django.http import HttpResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def clerk_webhook(request):
    secret = settings.CLERK_WEBHOOK_SECRET
    if not secret:
        return HttpResponseForbidden("Webhook secret not configured")

    try:
        from svix.webhooks import Webhook, WebhookVerificationError
    except ImportError:
        logger.error("svix não instalado — webhook Clerk rejeitado (fail-closed)")
        return HttpResponseForbidden("Signature verification unavailable")

    headers = {
        "svix-id": request.headers.get("svix-id"),
        "svix-timestamp": request.headers.get("svix-timestamp"),
        "svix-signature": request.headers.get("svix-signature"),
    }
    try:
        evt = Webhook(secret).verify(request.body.decode("utf-8"), headers)
    except WebhookVerificationError:
        return HttpResponseForbidden("Invalid signature")

    event_type = evt.get("type")
    data = evt.get("data", {})

    if event_type in ("user.created", "user.updated"):
        clerk_id = data.get("id")
        if not clerk_id:
            return HttpResponse("Missing user ID", status=400)

        emails = data.get("email_addresses", [])
        email = emails[0].get("email_address", "") if emails else ""

        user, created = User.objects.update_or_create(
            username=clerk_id,
            defaults={
                "first_name": (data.get("first_name") or "")[:30],
                "last_name": (data.get("last_name") or "")[:30],
                "email": email,
                "is_active": True,
            },
        )
        if created:
            user.set_unusable_password()
            user.save()

        from core.models import UserProfile

        avatar = data.get("image_url") or data.get("profile_image_url") or ""
        UserProfile.objects.update_or_create(
            user=user, defaults={"clerk_id": clerk_id, "avatar_url": avatar}
        )
        # Sem e-mail no log (PII): o clerk_id já correlaciona o usuário.
        logger.info("Clerk sync: %s %s", "created" if created else "updated", clerk_id)

    elif event_type == "user.deleted":
        clerk_id = data.get("id")
        if clerk_id:
            User.objects.filter(username=clerk_id).delete()
            logger.info("Clerk sync: deleted %s", clerk_id)

    return HttpResponse("OK", status=200)
