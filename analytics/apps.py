from django.apps import AppConfig


class AnalyticsConfig(AppConfig):
    """Captura e ranqueia as perguntas feitas na plataforma (por assunto)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "analytics"
    verbose_name = "Análise de perguntas"
