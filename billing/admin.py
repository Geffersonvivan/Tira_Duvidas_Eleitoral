from django.contrib import admin

from billing.models import EventoStripe, Pagamento


@admin.register(Pagamento)
class PagamentoAdmin(admin.ModelAdmin):
    list_display = ["user", "plano", "valor", "acesso_ate", "criado_em"]
    list_filter = ["plano", "criado_em"]
    search_fields = ["user__username", "user__email", "stripe_session_id"]
    readonly_fields = ["criado_em"]


@admin.register(EventoStripe)
class EventoStripeAdmin(admin.ModelAdmin):
    list_display = ["event_id", "tipo", "criado_em"]
    search_fields = ["event_id"]
    readonly_fields = ["criado_em"]
