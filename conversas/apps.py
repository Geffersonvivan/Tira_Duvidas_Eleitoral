from django.apps import AppConfig


class ConversasConfig(AppConfig):
    """Histórico de conversas do usuário (Serviço 1 — perguntas)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "conversas"
    verbose_name = "Conversas"
