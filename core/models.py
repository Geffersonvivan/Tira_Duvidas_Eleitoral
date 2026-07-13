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

    # Sementes de plano (evoluem na fase de billing/tiers).
    is_pro = models.BooleanField(default=False)
    credits = models.IntegerField(default=5, verbose_name="Créditos")
    subscription_status = models.CharField(max_length=50, default="inactive")

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Perfil de {self.user.username}"


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def criar_perfil(sender, instance, created, **kwargs):
    """Garante um UserProfile para todo User (inclusive o JIT do Clerk)."""
    if created:
        UserProfile.objects.get_or_create(user=instance)
