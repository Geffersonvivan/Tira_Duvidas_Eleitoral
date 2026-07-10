"""URLs do app core."""

from django.urls import path

from core import views

urlpatterns = [
    path("", views.home, name="home"),
    path("health/", views.health, name="health"),
]
