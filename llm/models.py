"""Registro de consumo de LLM — base do controle de orçamento e da auditoria.

Guarda metadados de cada chamada (nunca o conteúdo sensível), atendendo tanto
o teto de custo (cost-aware-llm-pipeline) quanto a auditoria (lógica.md §11.1).
"""

from django.db import models


class ConsumoLLM(models.Model):
    modelo = models.CharField(max_length=60)
    tarefa = models.CharField(max_length=20)
    tokens_entrada = models.PositiveIntegerField(default=0)
    tokens_saida = models.PositiveIntegerField(default=0)
    custo_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "consumo de LLM"
        verbose_name_plural = "consumos de LLM"
        ordering = ["-criado_em"]

    def __str__(self) -> str:
        return f"{self.modelo} · {self.tarefa} · US${self.custo_usd}"
