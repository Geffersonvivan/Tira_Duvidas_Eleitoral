"""Rate limiting simples por janela fixa, sobre o cache do Django.

Guarda básico contra abuso e estouro de custo nos endpoints que chamam LLM
(perguntas, materiais). A chave é por usuário autenticado (id) ou, no público,
por IP do cliente.

Observação de operação: com o cache padrão (LocMemCache) a contagem é POR
PROCESSO/worker — com N workers do gunicorn o teto efetivo é ~N× o configurado.
Para um teto global entre workers, configurar um cache compartilhado (Redis) via
CACHES no settings. Ver OPERACAO.md.
"""

from django.core.cache import cache

JANELA_PADRAO = 60  # segundos


def _identidade(request) -> str:
    """Identidade do chamador: usuário autenticado (id) ou IP do cliente."""
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        return f"u:{user.pk}"
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    ip = xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR", "")
    return f"ip:{ip or 'desconhecido'}"


def limite_excedido(request, *, escopo: str, limite: int, janela: int = JANELA_PADRAO) -> bool:
    """True se o chamador já passou de `limite` requisições na `janela` (segundos).

    `limite <= 0` desliga o controle (retorna sempre False).
    """
    if limite <= 0:
        return False
    chave = f"rl:{escopo}:{_identidade(request)}"
    cache.add(chave, 0, janela)  # inicia a janela na 1ª requisição (não renova depois)
    try:
        return cache.incr(chave) > limite
    except ValueError:
        # A chave expirou entre o add e o incr: recomeça a janela (1ª desta janela).
        cache.set(chave, 1, janela)
        return False  # limite >= 1 aqui, então a 1ª requisição nunca excede
