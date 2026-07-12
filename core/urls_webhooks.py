"""Rotas de webhooks (Clerk)."""

from django.urls import path

from core.webhooks import clerk_webhook

urlpatterns = [
    path("clerk/", clerk_webhook, name="clerk_webhook"),
]
