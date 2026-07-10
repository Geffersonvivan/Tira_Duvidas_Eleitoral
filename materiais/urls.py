from django.urls import path

from materiais import views

urlpatterns = [
    path("analisar/", views.analisar, name="analisar"),
]
