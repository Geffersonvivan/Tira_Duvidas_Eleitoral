from django.urls import path

from conversas import views

urlpatterns = [
    path("", views.listar, name="conversas_listar"),
    path("tudo/", views.apagar_todas, name="conversas_apagar_todas"),
    path("<int:pk>/", views.detalhe, name="conversa_detalhe"),
]
