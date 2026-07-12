"""URLs do app core: landing pública, app protegido e fluxo de auth."""

from django.urls import path

from core import views
from core.views_auth import auth_sync_view, landing_view, logout_view

urlpatterns = [
    path("", landing_view, name="landing"),
    path("app/", views.home, name="app"),
    path("auth-sync/", auth_sync_view, name="auth_sync"),
    path("logout/", logout_view, name="logout"),
    path("health/", views.health, name="health"),
]
