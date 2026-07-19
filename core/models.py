"""Perfil do usuário — vínculo com o Clerk e sementes de plano/tier.

Mínimo para o login/logout: guarda o `clerk_id` e alguns campos-semente de
plano (a fase de billing/tiers evolui isto depois). Um perfil é criado junto
com o `User` (signal) e sincronizado pelo webhook do Clerk.
"""

from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    clerk_id = models.CharField(max_length=100, unique=True, null=True, blank=True, db_index=True)
    avatar_url = models.URLField(blank=True, default="", help_text="Foto do perfil (Google/Clerk).")

    # Sementes de plano (mantidas por compat; o billing usa `plano` + contadores).
    is_pro = models.BooleanField(default=False)
    credits = models.IntegerField(default=5, verbose_name="Créditos")
    subscription_status = models.CharField(max_length=50, default="inactive")

    # --- Billing / assinatura (Stripe) ---
    #: Plano vigente: "free" | "essencial" | "pro" (ver billing.plans.PLANS).
    plano = models.CharField(max_length=20, default="free", db_index=True)
    stripe_customer_id = models.CharField(max_length=100, blank=True, default="", db_index=True)
    stripe_subscription_id = models.CharField(max_length=100, blank=True, default="")
    #: Fim do período pago corrente; passou disso, o plano vira "free" na prática.
    subscription_expires_at = models.DateTimeField(null=True, blank=True)
    #: Consumo no período de cota corrente (resetado na renovação/mês).
    perguntas_usadas = models.PositiveIntegerField(default=0)
    materiais_usados = models.PositiveIntegerField(default=0)
    #: Início do período de cota; o gate reseta os contadores a cada ~30 dias.
    uso_reset_em = models.DateTimeField(null=True, blank=True)

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Perfil de {self.user.username}"


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def criar_perfil(sender, instance, created, **kwargs):
    """Garante um UserProfile para todo User (inclusive o JIT do Clerk)."""
    if created:
        UserProfile.objects.get_or_create(user=instance)
