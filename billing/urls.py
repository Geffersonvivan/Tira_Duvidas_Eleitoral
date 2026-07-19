from django.urls import path

from billing import views

urlpatterns = [
    path("planos/", views.planos_view, name="planos"),
    path("billing/checkout/", views.checkout_view, name="checkout"),
    path("webhooks/stripe/", views.stripe_webhook, name="stripe_webhook"),
]
