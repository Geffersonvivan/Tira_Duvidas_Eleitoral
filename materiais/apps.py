from django.apps import AppConfig


class MateriaisConfig(AppConfig):
    """Serviço 2 (§6 lógica): analisa material gráfico (JPG/PNG/PDF) vs. legislação."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "materiais"
