"""Geração de embeddings para a busca semântica.

Provider: Voyage AI (recomendado para Claude). `voyage-3` gera vetores de 1024
dimensões, casando com `rag.models.EMBEDDING_DIM`. Sem `EMBEDDING_PROVIDER`
configurado, falha de forma clara em vez de devolver vetor inválido.
"""

import os

import httpx

_VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"
_DEFAULT_MODEL = "voyage-3"
_TIMEOUT = 30.0


def gerar_embedding(texto: str, *, input_type: str = "query") -> list[float]:
    """Embedding de um texto. Use input_type='query' na busca (default)."""
    return gerar_embeddings([texto], input_type=input_type)[0]


def gerar_embeddings(textos: list[str], *, input_type: str = "document") -> list[list[float]]:
    """Embeddings de vários textos. Use input_type='document' na ingestão."""
    provider = os.environ.get("EMBEDDING_PROVIDER", "")
    if provider != "voyage":
        raise NotImplementedError(
            "EMBEDDING_PROVIDER não configurado (ex.: 'voyage'). Ver ARQUITETURA.md §7."
        )
    return _voyage(textos, input_type)


def _voyage(textos: list[str], input_type: str) -> list[list[float]]:
    chave = os.environ.get("VOYAGE_API_KEY")
    if not chave:
        raise RuntimeError("VOYAGE_API_KEY ausente.")
    modelo = os.environ.get("VOYAGE_MODEL", _DEFAULT_MODEL)

    resp = httpx.post(
        _VOYAGE_URL,
        headers={"Authorization": f"Bearer {chave}"},
        json={"input": textos, "model": modelo, "input_type": input_type},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    dados = resp.json()["data"]
    # Mantém a ordem de entrada (a API retorna cada item com seu index).
    return [item["embedding"] for item in sorted(dados, key=lambda d: d["index"])]
