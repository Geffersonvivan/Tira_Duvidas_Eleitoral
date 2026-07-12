"""URLs raiz do projeto."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("webhooks/", include("core.urls_webhooks")),
    path("", include("core.urls")),
    path("api/perguntas/", include("perguntas.urls")),
    path("api/materiais/", include("materiais.urls")),
]
