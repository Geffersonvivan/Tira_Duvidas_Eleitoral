"""Modelos do billing: idempotência de webhook e auditoria de pagamento."""

from django.conf import settings
from django.db import models


class EventoStripe(models.Model):
    """Idempotência: guarda o `event.id` já processado (Stripe reenvia eventos)."""

    event_id = models.CharField(max_length=255, unique=True, db_index=True)
    tipo = models.CharField(max_length=100, blank=True, default="")
    criado_em = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.tipo} {self.event_id}"


class Pagamento(models.Model):
    """Auditoria de cada passe comprado (metadados, sem dado de cartão)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="pagamentos"
    )
    plano = models.CharField(max_length=20)
    valor = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    stripe_session_id = models.CharField(max_length=255, blank=True, default="")
    stripe_customer_id = models.CharField(max_length=255, blank=True, default="")
    acesso_ate = models.DateTimeField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em"]

    def __str__(self) -> str:
        return f"{self.user} · {self.plano} · R${self.valor}"
