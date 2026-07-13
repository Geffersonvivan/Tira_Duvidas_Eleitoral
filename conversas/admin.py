"""Admin das conversas (dado sensível — somente leitura)."""

from django.contrib import admin

from conversas.models import Conversa, Mensagem


class MensagemInline(admin.TabularInline):
    model = Mensagem
    extra = 0
    can_delete = False
    readonly_fields = ("papel", "texto", "assunto", "on_topic", "criado_em")
    fields = ("papel", "texto", "assunto", "on_topic", "criado_em")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Conversa)
class ConversaAdmin(admin.ModelAdmin):
    list_display = ("titulo", "user", "atualizado_em", "arquivada")
    list_filter = ("arquivada", "atualizado_em")
    search_fields = ("titulo", "user__username", "user__email")
    ordering = ("-atualizado_em",)
    readonly_fields = ("user", "titulo", "criado_em", "atualizado_em")
    inlines = [MensagemInline]

    def has_add_permission(self, request):
        return False
