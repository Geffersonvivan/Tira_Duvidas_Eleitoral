"""Cota de uso por plano — o portão que libera/bloqueia perguntas e materiais.

Modelo: passe de acesso ÚNICO (pagamento único) válido até uma data fixa
(fim do ciclo eleitoral). Cada nível tem um TETO calibrado de perguntas e
verificações de material para o período todo — generoso p/ uso moderado, mas
com limite de segurança para não estourar a conta de API.

Lógica pura sobre o `UserProfile` (fácil de testar, sem Stripe nem HTTP):
- limites vêm do plano vigente (billing.plans);
- os contadores `perguntas_usadas`/`materiais_usados` valem para o período de
  acesso e são zerados NA COMPRA (webhook), não pelo tempo;
- se o passe pago venceu (`subscription_expires_at` no passado), vale FREE.
"""

from django.db.models import F
from django.utils import timezone

from billing.plans import FREE, plano_do

PERGUNTAS = "perguntas"
MATERIAIS = "materiais"


def plano_efetivo(profile) -> str:
    """Plano que realmente vale agora (passe pago vencido → free)."""
    if profile.plano != FREE:
        venc = profile.subscription_expires_at
        if venc is not None and venc < timezone.now():
            return FREE
    return profile.plano


def limite(profile, tipo: str) -> int:
    return plano_do(plano_efetivo(profile))[tipo]


def usados(profile, tipo: str) -> int:
    return profile.perguntas_usadas if tipo == PERGUNTAS else profile.materiais_usados


def restante(profile, tipo: str) -> int:
    return max(0, limite(profile, tipo) - usados(profile, tipo))


def pode(profile, tipo: str, n: int = 1) -> bool:
    """Há saldo para consumir `n` do recurso `tipo` no período de acesso?"""
    return restante(profile, tipo) >= n


def consumir(profile, tipo: str, n: int = 1) -> None:
    """Registra o consumo de `n` unidades (chamar após o uso bem-sucedido).

    Incremento atômico no banco (F()) para não sofrer lost-update em requisições
    concorrentes — dois consumos paralelos somam de fato +n cada, mantendo o
    contador fiel ao teto do passe.
    """
    campo = "perguntas_usadas" if tipo == PERGUNTAS else "materiais_usados"
    type(profile).objects.filter(pk=profile.pk).update(**{campo: F(campo) + n})
    profile.refresh_from_db(fields=[campo])


def resetar_cota(profile) -> None:
    """Zera os contadores do período (chamado na ativação de um passe pago)."""
    profile.perguntas_usadas = 0
    profile.materiais_usados = 0
    profile.uso_reset_em = timezone.now()
    profile.save(update_fields=["perguntas_usadas", "materiais_usados", "uso_reset_em"])


# ---------------------------------------------- conveniências para as views
def _perfil_de(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return None  # público (Clerk desligado) — billing não se aplica
    return getattr(user, "profile", None)


def bloqueio_por_cota(request, tipo: str, n: int = 1):
    """(mensagem, 402) se o usuário logado não tem cota; None se ok ou público.

    Inerte enquanto `BILLING_ENFORCE` estiver desligado (a cobrança não vale até
    o Stripe estar configurado — evita travar usuários sem forma de pagar)."""
    from django.conf import settings

    if not getattr(settings, "BILLING_ENFORCE", False):
        return None
    prof = _perfil_de(request)
    if prof is None or pode(prof, tipo, n):
        return None
    p = plano_efetivo(prof)
    if p == FREE and tipo == MATERIAIS:
        msg = "A análise de material exige um passe. Veja os planos em /planos/."
    elif p == FREE:
        msg = "Você usou suas perguntas de amostra. Adquira um passe em /planos/."
    else:
        msg = "Você atingiu o limite de uso do seu passe."
    return (msg, 402)


def registrar_uso(request, tipo: str, n: int = 1) -> None:
    """Consome `n` do recurso para o usuário logado (no-op para público)."""
    prof = _perfil_de(request)
    if prof is not None and n > 0:
        consumir(prof, tipo, n)
