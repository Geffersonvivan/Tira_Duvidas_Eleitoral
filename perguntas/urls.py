from django.urls import path

from perguntas import views

urlpatterns = [
    path("perguntar/", views.perguntar, name="perguntar"),
    path("stream/", views.perguntar_stream, name="perguntar_stream"),
]
