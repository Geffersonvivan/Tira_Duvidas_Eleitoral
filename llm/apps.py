from django.apps import AppConfig


class LlmConfig(AppConfig):
    """Cliente Claude, roteamento por complexidade, orçamento e cache (cost-aware-llm-pipeline)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "llm"
