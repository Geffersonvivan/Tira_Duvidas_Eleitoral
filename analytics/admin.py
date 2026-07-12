"""Admin: ranking das dúvidas por assunto e log bruto (somente leitura)."""

from django.contrib import admin

from analytics.models import GrupoDuvida, PerguntaRegistrada


@admin.register(GrupoDuvida)
class GrupoDuvidaAdmin(admin.ModelAdmin):
    list_display = (
        "pergunta_canonica",
        "assunto",
        "frequencia",
        "ocorrencias_exatas",
        "variacoes",
        "ultima_ocorrencia",
    )
    list_filter = ("assunto",)
    search_fields = ("pergunta_canonica", "texto_normalizado")
    ordering = ("-frequencia",)
    readonly_fields = ("primeira_ocorrencia", "ultima_ocorrencia")
    exclude = ("embedding",)


@admin.register(PerguntaRegistrada)
class PerguntaRegistradaAdmin(admin.ModelAdmin):
    list_display = ("texto", "assunto", "on_topic", "grupo", "criado_em")
    list_filter = ("assunto", "on_topic", "criado_em")
    search_fields = ("texto",)
    ordering = ("-criado_em",)
    # Log imutável: sem edição manual.
    readonly_fields = ("texto", "texto_normalizado", "assunto", "on_topic", "grupo", "criado_em")
    exclude = ("embedding",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
