"""Testes da ingestão — chunking puro e persistência com embeddings mockados."""

import pytest

from rag import embeddings, ingest
from rag.models import Assunto, Documento, TipoFonte


# --------------------------------------------------------------- chunking
def test_dividir_em_chunks_vazio() -> None:
    assert ingest.dividir_em_chunks("   ") == []


def test_dividir_em_chunks_com_sobreposicao() -> None:
    texto = "abcdefghij"  # 10 chars
    chunks = ingest.dividir_em_chunks(texto, tamanho=4, sobreposicao=1)
    # janelas de 4 avançando 3: [0:4], [3:7], [6:10]
    assert chunks == ["abcd", "defg", "ghij"]


def test_dividir_em_chunks_sobreposicao_invalida() -> None:
    with pytest.raises(ValueError, match="sobreposicao"):
        ingest.dividir_em_chunks("abc", tamanho=2, sobreposicao=2)


# --------------------------------------------------------------- ingestão
@pytest.mark.django_db
def test_ingerir_cria_trechos(monkeypatch) -> None:
    doc = Documento.objects.create(
        titulo="Lei 9.504/97", tipo=TipoFonte.NORMA, assunto=Assunto.DIREITO, citavel=True
    )
    # Um vetor por chunk (dim pequena; sqlite não valida dimensão).
    monkeypatch.setattr(
        embeddings,
        "gerar_embeddings",
        lambda textos, **k: [[0.1, 0.2, 0.3] for _ in textos],
    )

    trechos = ingest.ingerir(doc, "abcdefghij", tamanho=4, sobreposicao=1)

    assert len(trechos) == 3
    assert doc.trechos.count() == 3
    assert [t.ordem for t in doc.trechos.all()] == [0, 1, 2]


@pytest.mark.django_db
def test_ingerir_texto_vazio_nao_cria(monkeypatch) -> None:
    doc = Documento.objects.create(titulo="Vazio", tipo=TipoFonte.NORMA, assunto=Assunto.DIREITO)
    monkeypatch.setattr(embeddings, "gerar_embeddings", lambda textos, **k: [])
    assert ingest.ingerir(doc, "   ") == []
    assert doc.trechos.count() == 0
