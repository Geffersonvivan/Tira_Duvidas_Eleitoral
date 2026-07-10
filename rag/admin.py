from django.contrib import admin

from rag.models import Documento, Trecho


class TrechoInline(admin.TabularInline):
    model = Trecho
    extra = 0
    fields = ["ordem", "conteudo"]


@admin.register(Documento)
class DocumentoAdmin(admin.ModelAdmin):
    list_display = ["titulo", "tipo", "assunto", "citavel", "vigente"]
    list_filter = ["tipo", "assunto", "citavel", "vigente"]
    search_fields = ["titulo"]
    inlines = [TrechoInline]


@admin.register(Trecho)
class TrechoAdmin(admin.ModelAdmin):
    list_display = ["documento", "ordem"]
    list_filter = ["documento__assunto", "documento__tipo"]
