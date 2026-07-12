"""Testes do agrupamento de perguntas (exato + novo grupo; separado por assunto).

O passo semântico (pgvector) só roda em Postgres; aqui, em SQLite, valida-se o
caminho exato/novo — que é o cerne da contagem.
"""

import pytest

from analytics import services
from analytics.models import GrupoDuvida, PerguntaRegistrada


def test_normalizar_remove_acento_pontuacao_e_caixa() -> None:
    assert services.normalizar("Posso IMPULSIONAR, na Eleição?") == "posso impulsionar na eleicao"


@pytest.mark.django_db
def test_registrar_cria_grupo_novo() -> None:
    services.registrar_pergunta("Posso impulsionar?", assunto="impulsionamento", vetor=None)
    g = GrupoDuvida.objects.get()
    assert g.assunto == "impulsionamento"
    assert g.frequencia == 1
    assert g.ocorrencias_exatas == 1
    assert PerguntaRegistrada.objects.count() == 1


@pytest.mark.django_db
def test_perguntas_iguais_somam_no_mesmo_grupo() -> None:
    for _ in range(3):
        services.registrar_pergunta("Posso impulsionar?", assunto="impulsionamento", vetor=None)
    # variação só de caixa/pontuação também é "igual" pela normalização
    services.registrar_pergunta("posso impulsionar", assunto="impulsionamento", vetor=None)

    assert GrupoDuvida.objects.count() == 1
    g = GrupoDuvida.objects.get()
    assert g.frequencia == 4
    assert g.ocorrencias_exatas == 4
    assert PerguntaRegistrada.objects.count() == 4


@pytest.mark.django_db
def test_assuntos_diferentes_nao_fundem() -> None:
    services.registrar_pergunta("Qual o prazo?", assunto="direito", vetor=None)
    services.registrar_pergunta("Qual o prazo?", assunto="contabilidade", vetor=None)
    assert GrupoDuvida.objects.count() == 2  # mesmo texto, assuntos distintos → grupos distintos


@pytest.mark.django_db
def test_off_topic_registra_sem_grupo() -> None:
    services.registrar_pergunta("Bolo de cenoura?", assunto=None, vetor=None, on_topic=False)
    assert GrupoDuvida.objects.count() == 0
    p = PerguntaRegistrada.objects.get()
    assert p.on_topic is False
    assert p.grupo is None


def test_capturar_seguro_nao_propaga_erro(monkeypatch) -> None:
    def _explode(*a, **k):
        raise RuntimeError("db fora")

    monkeypatch.setattr(services, "registrar_pergunta", _explode)
    # não deve levantar — captura é best-effort
    services.capturar_seguro("q", assunto="direito", vetor=None)
