from django.apps import AppConfig


class RagConfig(AppConfig):
    """RAG eleitoral: ingestão, embeddings e recuperação (iterative-retrieval)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "rag"
