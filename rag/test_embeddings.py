"""Testes de embeddings — a chamada de rede Voyage é mockada."""

from types import SimpleNamespace

import pytest

from rag import embeddings


def _fake_post(captura: dict):
    def post(url, *, headers, json, timeout):
        captura["url"] = url
        captura["headers"] = headers
        captura["json"] = json
        # Voyage devolve itens fora de ordem, cada um com seu index.
        data = [
            {"embedding": [0.2, 0.2], "index": 1},
            {"embedding": [0.1, 0.1], "index": 0},
        ]
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"data": data})

    return post


def test_sem_provider_levanta(monkeypatch) -> None:
    monkeypatch.delenv("EMBEDDING_PROVIDER", raising=False)
    with pytest.raises(NotImplementedError):
        embeddings.gerar_embedding("texto")


def test_voyage_sem_chave_levanta(monkeypatch) -> None:
    monkeypatch.setenv("EMBEDDING_PROVIDER", "voyage")
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        embeddings.gerar_embeddings(["a"])


def test_voyage_retorna_vetores_em_ordem(monkeypatch) -> None:
    monkeypatch.setenv("EMBEDDING_PROVIDER", "voyage")
    monkeypatch.setenv("VOYAGE_API_KEY", "pa-teste")
    captura: dict = {}
    monkeypatch.setattr(embeddings.httpx, "post", _fake_post(captura))

    vetores = embeddings.gerar_embeddings(["doc a", "doc b"], input_type="document")

    assert vetores == [[0.1, 0.1], [0.2, 0.2]]  # reordenado por index
    assert captura["json"]["input_type"] == "document"
    assert captura["headers"]["Authorization"] == "Bearer pa-teste"


def test_gerar_embedding_usa_query(monkeypatch) -> None:
    monkeypatch.setenv("EMBEDDING_PROVIDER", "voyage")
    monkeypatch.setenv("VOYAGE_API_KEY", "pa-teste")
    captura: dict = {}
    monkeypatch.setattr(embeddings.httpx, "post", _fake_post(captura))

    vetor = embeddings.gerar_embedding("minha pergunta")

    assert vetor == [0.1, 0.1]  # primeiro item, reordenado
    assert captura["json"]["input_type"] == "query"
