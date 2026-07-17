"""Testes do Serviço 1 — pipeline de perguntas, sem tocar API/RAG."""

from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient

from llm import budget, client
from llm.client import LLMIndisponivel
from perguntas import services
from perguntas.services import Classificacao, RespostaPergunta, responder_pergunta
from rag.models import Assunto, Documento, TipoFonte
from rag.retriever import Recuperacao


# ------------------------------------------------------------- orquestração
def test_off_topic_retorna_resposta_descontraida() -> None:
    resp = responder_pergunta(
        "Como faço bolo de cenoura?",
        classificar=lambda _p: Classificacao(on_topic=False),
        registrar=lambda *a, **k: None,  # captura desligada no teste
    )
    assert resp.on_topic is False
    assert resp.texto == services.RESPOSTA_OFF_TOPIC
    assert resp.fontes == []
    assert resp.disclaimer == ""  # off-topic não leva disclaimer jurídico


def test_on_topic_monta_resposta_com_fontes(monkeypatch) -> None:
    monkeypatch.setattr(services.embeddings, "gerar_embedding", lambda *a, **k: [0.0])
    norma = Documento(titulo="Lei 9.504/97", tipo=TipoFonte.NORMA, assunto=Assunto.IMPULSIONAMENTO)
    rec = Recuperacao(contexto=[], fontes_citaveis=[norma])

    resp = responder_pergunta(
        "Posso impulsionar publicação?",
        classificar=lambda _p: Classificacao(on_topic=True, assunto="impulsionamento"),
        recuperar=lambda _p, _a, _v=None: rec,
        gerar=lambda _p, _r: "Sim, com identificação e registro.",
        registrar=lambda *a, **k: None,
    )
    assert resp.on_topic is True
    assert resp.assunto == "impulsionamento"
    assert resp.texto == "Sim, com identificação e registro."
    assert resp.fontes == [norma]
    assert resp.disclaimer  # on-topic sempre leva disclaimer


# ------------------------------------------------------------- classificador
def _mock_completar(monkeypatch, texto: str) -> None:
    resposta = client.Resposta(
        texto=texto,
        modelo="claude-haiku-4-5",
        tokens_entrada=5,
        tokens_saida=1,
        stop_reason="end_turn",
    )
    monkeypatch.setattr(client, "completar", lambda *a, **k: resposta)
    monkeypatch.setattr(budget, "registrar_uso", lambda *a, **k: None)  # evita DB


def test_classificar_intencao_reconhece_assunto(monkeypatch) -> None:
    _mock_completar(monkeypatch, "impulsionamento")
    cls = services.classificar_intencao("posso impulsionar?")
    assert cls.on_topic is True
    assert cls.assunto == "impulsionamento"


def test_classificar_intencao_marca_fora_de_escopo(monkeypatch) -> None:
    _mock_completar(monkeypatch, "fora")
    cls = services.classificar_intencao("como faz bolo?")
    assert cls.on_topic is False
    assert cls.assunto is None


# -------------------------------------------------------------------- view
def test_view_perguntar_off_topic(monkeypatch) -> None:
    monkeypatch.setattr(services, "classificar_intencao", lambda _p: Classificacao(on_topic=False))
    resp = APIClient().post("/api/perguntas/perguntar/", {"pergunta": "bolo?"}, format="json")
    assert resp.status_code == 200
    assert resp.data["on_topic"] is False
    assert resp.data["fontes"] == []


def test_view_perguntar_valida_entrada_vazia() -> None:
    resp = APIClient().post("/api/perguntas/perguntar/", {}, format="json")
    assert resp.status_code == 400


def test_view_perguntar_on_topic(monkeypatch) -> None:
    monkeypatch.setattr(
        services,
        "responder_pergunta",
        lambda _p: RespostaPergunta(
            on_topic=True, texto="ok", assunto="direito", disclaimer="d", fontes=[]
        ),
    )
    resp = APIClient().post("/api/perguntas/perguntar/", {"pergunta": "prazo?"}, format="json")
    assert resp.status_code == 200
    assert resp.data["texto"] == "ok"
    assert resp.data["assunto"] == "direito"


# ------------------------------------------------- portões de custo/abuso
@override_settings(RATE_LIMIT_PERGUNTAS_POR_MIN=1)
def test_view_perguntar_rate_limit_retorna_429(monkeypatch) -> None:
    cache.clear()
    monkeypatch.setattr(
        services, "responder_pergunta", lambda _p: RespostaPergunta(on_topic=True, texto="ok")
    )
    cli = APIClient()
    r1 = cli.post("/api/perguntas/perguntar/", {"pergunta": "x"}, format="json")
    r2 = cli.post("/api/perguntas/perguntar/", {"pergunta": "x"}, format="json")
    assert r1.status_code == 200
    assert r2.status_code == 429


def test_view_perguntar_orcamento_estourado_retorna_503(monkeypatch) -> None:
    cache.clear()
    monkeypatch.setattr(budget, "dentro_do_orcamento", lambda *a, **k: False)
    resp = APIClient().post("/api/perguntas/perguntar/", {"pergunta": "x"}, format="json")
    assert resp.status_code == 503


def test_view_perguntar_llm_indisponivel_retorna_503(monkeypatch) -> None:
    cache.clear()

    def boom(_p):
        raise LLMIndisponivel("provedor fora")

    monkeypatch.setattr(services, "responder_pergunta", boom)
    resp = APIClient().post("/api/perguntas/perguntar/", {"pergunta": "x"}, format="json")
    assert resp.status_code == 503
