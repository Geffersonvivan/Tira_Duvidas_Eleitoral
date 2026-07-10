from django.contrib import admin

from llm.models import ConsumoLLM


@admin.register(ConsumoLLM)
class ConsumoLLMAdmin(admin.ModelAdmin):
    list_display = ["criado_em", "modelo", "tarefa", "tokens_entrada", "tokens_saida", "custo_usd"]
    list_filter = ["modelo", "tarefa"]
    date_hierarchy = "criado_em"
