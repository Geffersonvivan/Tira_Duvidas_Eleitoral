from django.urls import path

from conversas import views

urlpatterns = [
    path("", views.listar, name="conversas_listar"),
    path("<int:pk>/", views.detalhe, name="conversa_detalhe"),
]
