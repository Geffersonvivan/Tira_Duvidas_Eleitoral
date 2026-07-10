from django.apps import AppConfig


class PerguntasConfig(AppConfig):
    """Serviço 1 (§4 lógica): responde dúvidas eleitorais ancoradas no RAG."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "perguntas"
