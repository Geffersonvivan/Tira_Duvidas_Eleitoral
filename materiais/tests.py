"""Testes do Serviço 2 — análise de peças, sem tocar visão/RAG."""

import json

from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from materiais import services
from materiais.services import (
    Parecer,
    ResultadoAnalise,
    StatusParecer,
    _parse_parecer,
    analisar_lote,
    analisar_peca,
)
from rag.models import Assunto, Documento, TipoFonte
from rag.retriever import Recuperacao


# ------------------------------------------------------------- utilidades
def test_extensao_valida() -> None:
    assert services.extensao_valida("santinho.JPG") is True
    assert services.extensao_valida("arte.pdf") is True
    assert services.extensao_valida("planilha.xlsx") is False


def test_media_type() -> None:
    assert services.media_type("a.jpg") == "image/jpeg"
    assert services.media_type("a.pdf") == "application/pdf"


# --------------------------------------------------------------- parser
def test_parse_parecer_json_valido() -> None:
    payload = json.dumps(
        {
            "status": "parcial",
            "pontos": [{"descricao": "Falta CNPJ", "conforme": False, "fundamento": "Lei 9.504"}],
            "recomendacoes": "Inserir CNPJ.",
        }
    )
    parecer = _parse_parecer(payload, fontes=[])
    assert parecer.status == StatusParecer.PARCIAL
    assert parecer.pontos[0].conforme is False
    assert parecer.recomendacoes == "Inserir CNPJ."


def test_parse_parecer_json_invalido_vira_inconclusivo() -> None:
    parecer = _parse_parecer("isso não é json", fontes=[])
    assert parecer.status == StatusParecer.INCONCLUSIVO


def test_parse_parecer_status_desconhecido_vira_inconclusivo() -> None:
    parecer = _parse_parecer(json.dumps({"status": "talvez"}), fontes=[])
    assert parecer.status == StatusParecer.INCONCLUSIVO


# --------------------------------------------------------- orquestração
def test_analisar_peca_off_topic() -> None:
    r = analisar_peca("foto.jpg", b"x", "image/jpeg", gate=lambda _d, _m: False)
    assert r.on_topic is False
    assert r.mensagem == services.RESPOSTA_OFF_TOPIC
    assert r.parecer is None


def test_analisar_peca_on_topic_com_seams() -> None:
    norma = Documento(titulo="Lei 9.504/97", tipo=TipoFonte.NORMA, assunto=Assunto.DIREITO)
    rec = Recuperacao(contexto=[], fontes_citaveis=[norma])
    r = analisar_peca(
        "santinho.jpg",
        b"bytes",
        "image/jpeg",
        gate=lambda _d, _m: True,
        extrair=lambda _d, _m: "número 12345, sem CNPJ",
        recuperar=lambda _t: rec,
        avaliar=lambda _t, _r: Parecer(status=StatusParecer.PARCIAL, fontes=_r.fontes_citaveis),
    )
    assert r.on_topic is True
    assert r.parecer.status == StatusParecer.PARCIAL
    assert r.parecer.fontes == [norma]


def test_analisar_lote_um_parecer_por_peca() -> None:
    pecas = [("a.jpg", b"1", "image/jpeg"), ("b.png", b"2", "image/png")]
    resultados = analisar_lote(
        pecas,
        gate=lambda _d, _m: False,  # ambas fora de escopo, mas 2 resultados
    )
    assert len(resultados) == 2
    assert [r.peca for r in resultados] == ["a.jpg", "b.png"]


# ---------------------------------------------------------------- view
def test_view_analisar_formato_invalido() -> None:
    arq = SimpleUploadedFile("planilha.xlsx", b"data", content_type="application/octet-stream")
    resp = APIClient().post("/api/materiais/analisar/", {"arquivos": [arq]}, format="multipart")
    assert resp.status_code == 400


def test_view_analisar_retorna_resultados(monkeypatch) -> None:
    monkeypatch.setattr(
        services,
        "analisar_lote",
        lambda pecas, **k: [
            ResultadoAnalise(peca=nome, on_topic=False, mensagem="fora") for nome, _b, _m in pecas
        ],
    )
    arq = SimpleUploadedFile("santinho.jpg", b"fakejpeg", content_type="image/jpeg")
    resp = APIClient().post("/api/materiais/analisar/", {"arquivos": [arq]}, format="multipart")
    assert resp.status_code == 200
    assert resp.data["resultados"][0]["peca"] == "santinho.jpg"
    assert resp.data["resultados"][0]["on_topic"] is False
