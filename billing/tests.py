"""Testes do billing: gate de cota + processamento de webhook (sem Stripe)."""

from datetime import timedelta

import pytest
from django.utils import timezone

from billing import gate, services
from billing.models import EventoStripe, Pagamento
from billing.plans import ESSENCIAL, FREE, PRO


def _perfil(django_user_model, plano=FREE, **extra):
    u = django_user_model.objects.create(username=f"u{plano}{extra.get('_s', '')}")
    p = u.profile
    p.plano = plano
    for k, v in extra.items():
        if not k.startswith("_"):
            setattr(p, k, v)
    p.save()
    return p


@pytest.mark.django_db
def test_free_tem_3_perguntas_e_zero_materiais(django_user_model) -> None:
    p = _perfil(django_user_model, FREE)
    assert gate.restante(p, gate.PERGUNTAS) == 3
    assert gate.restante(p, gate.MATERIAIS) == 0
    assert gate.pode(p, gate.PERGUNTAS) is True
    assert gate.pode(p, gate.MATERIAIS) is False  # material nunca é grátis


@pytest.mark.django_db
def test_consumir_perguntas_ate_esgotar(django_user_model) -> None:
    p = _perfil(django_user_model, FREE)
    for _ in range(3):
        assert gate.pode(p, gate.PERGUNTAS)
        gate.consumir(p, gate.PERGUNTAS)
    assert gate.pode(p, gate.PERGUNTAS) is False
    assert gate.restante(p, gate.PERGUNTAS) == 0


@pytest.mark.django_db
def test_essencial_libera_material(django_user_model) -> None:
    venc = timezone.now() + timedelta(days=15)
    p = _perfil(django_user_model, ESSENCIAL, subscription_expires_at=venc)
    assert gate.limite(p, gate.MATERIAIS) > 0
    assert gate.pode(p, gate.MATERIAIS) is True


@pytest.mark.django_db
def test_pro_e_o_dobro_do_essencial(django_user_model) -> None:
    venc = timezone.now() + timedelta(days=15)
    ess = _perfil(django_user_model, ESSENCIAL, subscription_expires_at=venc, _s="e")
    pro = _perfil(django_user_model, PRO, subscription_expires_at=venc, _s="p")
    assert gate.limite(pro, gate.PERGUNTAS) == 2 * gate.limite(ess, gate.PERGUNTAS)
    assert gate.limite(pro, gate.MATERIAIS) == 2 * gate.limite(ess, gate.MATERIAIS)


@pytest.mark.django_db
def test_plano_pago_vencido_vira_free(django_user_model) -> None:
    ontem = timezone.now() - timedelta(days=1)
    p = _perfil(django_user_model, ESSENCIAL, subscription_expires_at=ontem)
    assert gate.plano_efetivo(p) == FREE
    assert gate.pode(p, gate.MATERIAIS) is False  # perdeu o acesso pago


@pytest.mark.django_db
def test_resetar_cota_zera_contadores(django_user_model) -> None:
    """A compra de um passe zera o consumo do período (webhook chama isto)."""
    p = _perfil(django_user_model, FREE, perguntas_usadas=3, materiais_usados=7)
    gate.resetar_cota(p)
    assert (p.perguntas_usadas, p.materiais_usados) == (0, 0)
    assert p.uso_reset_em is not None


# ------------------------------------------------------- webhook (services)
def _evento(user_id, plan_key, event_id="evt_1", pago="paid"):
    return {
        "id": event_id,
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_123",
                "payment_status": pago,
                "client_reference_id": str(user_id),
                "customer": "cus_123",
                "metadata": {"plan_key": plan_key},
            }
        },
    }


@pytest.mark.django_db
def test_webhook_ativa_passe(django_user_model) -> None:
    u = django_user_model.objects.create(username="comprador")
    assert services.processar_evento(_evento(u.id, ESSENCIAL)) == "ativado"
    u.profile.refresh_from_db()
    assert u.profile.plano == ESSENCIAL
    assert u.profile.is_pro is True
    assert u.profile.subscription_expires_at is not None
    assert gate.pode(u.profile, gate.MATERIAIS) is True  # material liberado
    assert Pagamento.objects.filter(user=u, plano=ESSENCIAL).exists()


@pytest.mark.django_db
def test_webhook_idempotente(django_user_model) -> None:
    u = django_user_model.objects.create(username="comprador2")
    ev = _evento(u.id, PRO, event_id="evt_dup")
    assert services.processar_evento(ev) == "ativado"
    assert services.processar_evento(ev) == "duplicado"  # 2ª vez não reprocessa
    assert EventoStripe.objects.filter(event_id="evt_dup").count() == 1
    assert Pagamento.objects.filter(user=u).count() == 1  # não cobrou duas vezes


@pytest.mark.django_db
def test_webhook_sem_pagamento_nao_ativa(django_user_model) -> None:
    u = django_user_model.objects.create(username="naopagou")
    assert services.processar_evento(_evento(u.id, ESSENCIAL, pago="unpaid")) == "sem_pagamento"
    u.profile.refresh_from_db()
    assert u.profile.plano == FREE
