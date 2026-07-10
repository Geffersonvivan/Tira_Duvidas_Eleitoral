"""Configuração do roteamento e custo de modelos (cost-aware-llm-pipeline).

IDs de modelo seguem a skill claude-api: **sem sufixo de data**.
Preços não são hardcodados (os valores da skill vêm mascarados) — são lidos do
ambiente e, sem eles, o custo calculado é 0 (apenas contabiliza tokens).
"""

import os
from decimal import Decimal
from enum import StrEnum


class Tarefa(StrEnum):
    """Etapas do pipeline, mapeadas a um perfil de modelo (lógica.md §13)."""

    CLASSIFICAR = "classificar"
    DESAMBIGUAR = "desambiguar"
    RESPONDER = "responder"
    VISAO = "visao"
    COMPLEXO = "complexo"


# Cada tarefa lê uma variável de ambiente, com default seguro (skill claude-api).
_ENV_POR_TAREFA: dict[Tarefa, str] = {
    Tarefa.CLASSIFICAR: "MODEL_CLASSIFY",
    Tarefa.DESAMBIGUAR: "MODEL_CLASSIFY",
    Tarefa.RESPONDER: "MODEL_ANSWER",
    Tarefa.VISAO: "MODEL_VISION",
    Tarefa.COMPLEXO: "MODEL_COMPLEX",
}

_DEFAULT_POR_TAREFA: dict[Tarefa, str] = {
    Tarefa.CLASSIFICAR: "claude-haiku-4-5",
    Tarefa.DESAMBIGUAR: "claude-haiku-4-5",
    Tarefa.RESPONDER: "claude-sonnet-4-6",
    Tarefa.VISAO: "claude-sonnet-4-6",
    Tarefa.COMPLEXO: "claude-opus-4-8",
}

#: Modelos que suportam thinking adaptativo (4.6+). Haiku 4.5 não suporta.
_SUPORTA_THINKING = ("claude-sonnet-4-6", "claude-opus-4-8", "claude-opus-4-7", "claude-fable-5")


def modelo_para(tarefa: Tarefa) -> str:
    """ID do modelo para a tarefa (env sobrescreve o default)."""
    return os.environ.get(_ENV_POR_TAREFA[tarefa], _DEFAULT_POR_TAREFA[tarefa])


def suporta_thinking(modelo: str) -> bool:
    return modelo in _SUPORTA_THINKING


def preco_por_mtok(modelo: str) -> tuple[Decimal, Decimal]:
    """Preço (entrada, saída) por 1M de tokens, lido de PRECO_<modelo>.

    Formato: ``PRECO_claude-sonnet-4-6=3.00,15.00``. Ausente → (0, 0).
    """
    bruto = os.environ.get(f"PRECO_{modelo}")
    if not bruto:
        return Decimal(0), Decimal(0)
    entrada, _, saida = bruto.partition(",")
    return Decimal(entrada.strip() or 0), Decimal(saida.strip() or 0)
