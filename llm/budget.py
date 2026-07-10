"""Controle de orçamento (cost-aware-llm-pipeline).

Calcula custo por tokens, registra o consumo e verifica o teto mensal.
"""

import os
from datetime import date
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from llm.config import preco_por_mtok
from llm.models import ConsumoLLM

_UM_MILHAO = Decimal(1_000_000)


def calcular_custo(modelo: str, tokens_entrada: int, tokens_saida: int) -> Decimal:
    """Custo em USD a partir dos tokens e do preço configurado do modelo."""
    p_entrada, p_saida = preco_por_mtok(modelo)
    return (Decimal(tokens_entrada) * p_entrada + Decimal(tokens_saida) * p_saida) / _UM_MILHAO


def registrar_uso(
    modelo: str,
    tarefa: str,
    tokens_entrada: int,
    tokens_saida: int,
) -> ConsumoLLM:
    """Persiste o consumo de uma chamada (metadados apenas)."""
    return ConsumoLLM.objects.create(
        modelo=modelo,
        tarefa=tarefa,
        tokens_entrada=tokens_entrada,
        tokens_saida=tokens_saida,
        custo_usd=calcular_custo(modelo, tokens_entrada, tokens_saida),
    )


def gasto_no_mes(referencia: date | None = None) -> Decimal:
    """Soma do custo no mês da data de referência (default: mês corrente)."""
    ref = referencia or timezone.now().date()
    total = ConsumoLLM.objects.filter(
        criado_em__year=ref.year,
        criado_em__month=ref.month,
    ).aggregate(total=Sum("custo_usd"))["total"]
    return total or Decimal(0)


def teto_mensal() -> Decimal:
    """Teto configurado em LLM_MONTHLY_BUDGET_USD (0 = sem teto)."""
    return Decimal(os.environ.get("LLM_MONTHLY_BUDGET_USD", "0") or 0)


def dentro_do_orcamento(referencia: date | None = None) -> bool:
    """True se o gasto do mês ainda está sob o teto (ou se não há teto)."""
    teto = teto_mensal()
    if teto <= 0:
        return True
    return gasto_no_mes(referencia) < teto
