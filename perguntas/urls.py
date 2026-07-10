from django.urls import path

from perguntas import views

urlpatterns = [
    path("perguntar/", views.perguntar, name="perguntar"),
]
