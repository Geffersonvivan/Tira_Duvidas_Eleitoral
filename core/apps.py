import os

from django.apps import AppConfig
from django.core.checks import Error, Warning, register


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self) -> None:
        register(_checar_config_producao)


def _checar_config_producao(app_configs, **kwargs):
    """Falha cedo em produção (DEBUG=False) se faltar configuração crítica.

    Em vez de o erro só aparecer no primeiro request (ex.: ANTHROPIC_API_KEY
    ausente), o `manage.py check`/deploy sinaliza na largada. Só o SECRET_KEY
    inseguro bloqueia (Error); o resto é aviso (Warning) para não travar tarefas
    como collectstatic quando uma integração ainda não foi configurada.
    """
    from django.conf import settings

    if settings.DEBUG:
        return []

    problemas = []
    if settings.SECRET_KEY == "dev-inseguro-troque-no-env":  # noqa: S105 — é o default a detectar
        problemas.append(
            Error(
                "DJANGO_SECRET_KEY não configurada em produção (usando o default inseguro).",
                hint="Defina DJANGO_SECRET_KEY no ambiente (Railway).",
                id="core.E001",
            )
        )
    if not os.environ.get("ANTHROPIC_API_KEY"):
        problemas.append(
            Warning(
                "ANTHROPIC_API_KEY ausente — as chamadas ao Claude vão falhar.",
                hint="Defina ANTHROPIC_API_KEY no ambiente.",
                id="core.W001",
            )
        )
    if not os.environ.get("VOYAGE_API_KEY"):
        problemas.append(
            Warning(
                "VOYAGE_API_KEY ausente — a recuperação do RAG (embeddings) vai falhar.",
                hint="Defina VOYAGE_API_KEY no ambiente.",
                id="core.W002",
            )
        )
    return problemas
