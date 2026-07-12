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


# ---------------------------------------------------------- reagrupamento LLM
def _grupo(canonica, norm, freq, exatas):
    return GrupoDuvida.objects.create(
        assunto="impulsionamento",
        pergunta_canonica=canonica,
        texto_normalizado=norm,
        frequencia=freq,
        ocorrencias_exatas=exatas,
    )


def test_extrair_json_tolera_cercas() -> None:
    assert services._extrair_json('```json\n{"grupos": [[0,1]]}\n```') == {"grupos": [[0, 1]]}


@pytest.mark.django_db
def test_reagrupar_funde_grupos_de_mesmo_sentido() -> None:
    # ordem por -frequencia: c(3)=idx0, a(2)=idx1, b(1)=idx2
    c = _grupo("Qual o valor máximo?", "qual o valor maximo", 3, 3)
    a = _grupo("Posso impulsionar no Instagram?", "posso impulsionar no instagram", 2, 2)
    b = _grupo("Dá pra promover post pago no Insta?", "da pra promover post pago no insta", 1, 1)
    PerguntaRegistrada.objects.create(
        texto="Dá pra promover post pago no Insta?",
        texto_normalizado="da pra promover post pago no insta",
        assunto="impulsionamento",
        grupo=b,
    )

    # clusterizador falso: funde idx1 (a) e idx2 (b); c fica sozinho
    fundidos = services.reagrupar_por_intencao(
        "impulsionamento", clusterizar=lambda _perguntas: [[0], [1, 2]]
    )

    assert fundidos == 1
    assert GrupoDuvida.objects.count() == 2  # c + a (b foi fundido em a)
    a.refresh_from_db()
    assert a.frequencia == 3  # 2 + 1
    assert a.ocorrencias_exatas == 2
    assert a.variacoes == 1  # frequencia - exatas
    assert not GrupoDuvida.objects.filter(pk=b.pk).exists()
    assert PerguntaRegistrada.objects.get().grupo_id == a.pk
    assert GrupoDuvida.objects.filter(pk=c.pk).exists()  # intocado


@pytest.mark.django_db
def test_reagrupar_sem_fusao_mantem_tudo() -> None:
    _grupo("A?", "a", 2, 2)
    _grupo("B?", "b", 1, 1)
    fundidos = services.reagrupar_por_intencao("impulsionamento", clusterizar=lambda _p: [[0], [1]])
    assert fundidos == 0
    assert GrupoDuvida.objects.count() == 2


@pytest.mark.django_db
def test_reagrupar_ignora_assunto_com_um_grupo() -> None:
    _grupo("Só uma?", "so uma", 1, 1)
    assert services.reagrupar_por_intencao("impulsionamento", clusterizar=lambda _p: [[0]]) == 0
