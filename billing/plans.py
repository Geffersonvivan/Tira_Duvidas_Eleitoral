"""Planos do TDE — passe de acesso ÚNICO (pagamento único, sem mensalidade).

Essencial (R$ 349) e Profissional (R$ 499) dão acesso até o fim do ciclo
eleitoral (config BILLING_ACESSO_ATE). Cada nível tem um TETO calibrado de
perguntas + verificações de material PARA O PERÍODO todo — os NÚMEROS abaixo são
placeholders (env) a calibrar para uso moderado, sem estourar a conta de API.

Grátis: 3 perguntas (amostra), 0 análise de material (material é sempre pago).
"""

import os

FREE = "free"
ESSENCIAL = "essencial"
PRO = "pro"


def _int(env: str, default: str) -> int:
    try:
        return int(os.environ.get(env, default))
    except ValueError:
        return int(default)


PLANS: dict[str, dict] = {
    FREE: {
        "nome": "Grátis",
        "preco": 0.0,
        "perguntas": _int("PLANO_FREE_PERGUNTAS", "3"),
        "materiais": _int("PLANO_FREE_MATERIAIS", "0"),
        "is_paid": False,
        "stripe_price": "",
    },
    ESSENCIAL: {
        "nome": "Essencial",
        "preco": 349.0,
        "perguntas": _int("PLANO_ESSENCIAL_PERGUNTAS", "300"),  # placeholder (período)
        "materiais": _int("PLANO_ESSENCIAL_MATERIAIS", "50"),  # placeholder (período)
        "is_paid": True,
    },
    PRO: {
        "nome": "Profissional",
        "preco": 499.0,
        "perguntas": _int("PLANO_PRO_PERGUNTAS", "600"),  # placeholder (mais que o Essencial)
        "materiais": _int("PLANO_PRO_MATERIAIS", "100"),  # placeholder
        "is_paid": True,
    },
}


def plano_do(chave: str) -> dict:
    """Config do plano pela chave (cai no FREE se desconhecida)."""
    return PLANS.get(chave, PLANS[FREE])
