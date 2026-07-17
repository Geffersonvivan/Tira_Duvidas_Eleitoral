"""Smoke tests — linha de base verde do CI."""

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.test import Client, RequestFactory, override_settings
from django.utils import timezone

from analytics.models import PerguntaRegistrada
from conversas.models import Conversa
from core.views import home


def test_health_ok() -> None:
    resp = Client().get("/health/")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_home_renderiza() -> None:
    # RequestFactory + view direta evita o bug do test Client no Python 3.14
    # (Context.__copy__); no CI (3.12) o Client também funcionaria.
    resp = home(RequestFactory().get("/"))
    assert resp.status_code == 200
    conteudo = resp.content.decode()
    assert "Tira-Dúvidas Eleitoral - TDE" in conteudo
    assert "Perguntas eleitorais" in conteudo
    assert "Análise de material gráfico" in conteudo


# ----------------------------------------------------- expurgo LGPD (item 10)
def _envelhecer(obj, campo: str, dias: int) -> None:
    """Recua o timestamp auto_now/auto_now_add do objeto direto no banco."""
    antigo = timezone.now() - timedelta(days=dias)
    type(obj).objects.filter(pk=obj.pk).update(**{campo: antigo})


@pytest.mark.django_db
@override_settings(LGPD_RETENCAO_PERGUNTAS_DIAS=30, LGPD_RETENCAO_CONVERSAS_DIAS=30)
def test_expurgar_dados_apaga_alem_do_prazo(django_user_model) -> None:
    velha = PerguntaRegistrada.objects.create(texto="antiga", texto_normalizado="antiga")
    _envelhecer(velha, "criado_em", 40)
    PerguntaRegistrada.objects.create(texto="recente", texto_normalizado="recente")

    u = django_user_model.objects.create(username="u")
    conv_velha = Conversa.objects.create(user=u, titulo="velha")
    _envelhecer(conv_velha, "atualizado_em", 40)
    Conversa.objects.create(user=u, titulo="recente")

    call_command("expurgar_dados")

    assert [p.texto for p in PerguntaRegistrada.objects.all()] == ["recente"]
    assert [c.titulo for c in Conversa.objects.all()] == ["recente"]


@pytest.mark.django_db
@override_settings(LGPD_RETENCAO_PERGUNTAS_DIAS=0, LGPD_RETENCAO_CONVERSAS_DIAS=0)
def test_expurgar_dados_desligado_nao_apaga() -> None:
    velha = PerguntaRegistrada.objects.create(texto="antiga", texto_normalizado="antiga")
    _envelhecer(velha, "criado_em", 999)
    call_command("expurgar_dados")
    assert PerguntaRegistrada.objects.count() == 1  # retenção 0 = desligada


@pytest.mark.django_db
@override_settings(LGPD_RETENCAO_PERGUNTAS_DIAS=30)
def test_expurgar_dados_dry_run_nao_apaga() -> None:
    velha = PerguntaRegistrada.objects.create(texto="antiga", texto_normalizado="antiga")
    _envelhecer(velha, "criado_em", 40)
    call_command("expurgar_dados", "--dry-run")
    assert PerguntaRegistrada.objects.count() == 1  # dry-run só conta
