"""Geração de embeddings para a busca semântica.

Provider: Voyage AI (recomendado para Claude). `voyage-3` gera vetores de 1024
dimensões, casando com `rag.models.EMBEDDING_DIM`. Sem `EMBEDDING_PROVIDER`
configurado, falha de forma clara em vez de devolver vetor inválido.

Requests são **paginadas em lotes** (a Voyage limita textos e tokens por
request) com backoff em 429/5xx. Para o tier gratuito (3 RPM / 10K TPM) dá para
apertar o passo via env: `VOYAGE_MAX_TOKENS_LOTE` e `VOYAGE_PAUSA` (segundos
entre lotes).
"""

import logging
import os
import time

import httpx

logger = logging.getLogger(__name__)

_VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"
_DEFAULT_MODEL = "voyage-3"
_TIMEOUT = 60.0
_MAX_TENTATIVAS = 8  # retries em 429/5xx (rate limit da Voyage)
_MAX_TEXTOS_LOTE = 128  # máx de textos por request


def _max_tokens_lote() -> int:
    # Cabe no TPM: no tier grátis (10K TPM) mantenha < 10000; padrão conservador.
    return int(os.environ.get("VOYAGE_MAX_TOKENS_LOTE", "7000"))


def _pausa() -> float:
    # Segundos entre lotes (respeita RPM). 0 no tier pago; ~21 no grátis (3 RPM).
    return float(os.environ.get("VOYAGE_PAUSA", "0"))


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


def _lotes(textos: list[str]):
    """Agrupa textos em lotes que respeitam o limite de textos e de tokens."""
    teto = _max_tokens_lote()
    lote: list[str] = []
    tokens = 0
    for t in textos:
        tk = max(1, len(t) // 4)  # estimativa grosseira de tokens
        if lote and (len(lote) >= _MAX_TEXTOS_LOTE or tokens + tk > teto):
            yield lote
            lote, tokens = [], 0
        lote.append(t)
        tokens += tk
    if lote:
        yield lote


def _voyage(textos: list[str], input_type: str) -> list[list[float]]:
    chave = os.environ.get("VOYAGE_API_KEY")
    if not chave:
        raise RuntimeError("VOYAGE_API_KEY ausente.")
    modelo = os.environ.get("VOYAGE_MODEL", _DEFAULT_MODEL)
    pausa = _pausa()

    saida: list[list[float]] = []
    lotes = list(_lotes(textos))
    for i, lote in enumerate(lotes):
        if i and pausa:
            time.sleep(pausa)
        saida.extend(_voyage_lote(lote, input_type, chave, modelo))
    return saida


def _voyage_lote(lote: list[str], input_type: str, chave: str, modelo: str) -> list[list[float]]:
    for tentativa in range(1, _MAX_TENTATIVAS + 1):
        resp = httpx.post(
            _VOYAGE_URL,
            headers={"Authorization": f"Bearer {chave}"},
            json={"input": lote, "model": modelo, "input_type": input_type},
            timeout=_TIMEOUT,
        )
        # 429 (rate limit) e 5xx: espera com backoff e tenta de novo.
        if resp.status_code in (429, 500, 502, 503, 529) and tentativa < _MAX_TENTATIVAS:
            espera = float(resp.headers.get("retry-after") or min(2**tentativa, 60))
            logger.warning(
                "Voyage %s — retry %d/%d em %.0fs",
                resp.status_code,
                tentativa,
                _MAX_TENTATIVAS,
                espera,
            )
            time.sleep(espera)
            continue
        resp.raise_for_status()
        dados = resp.json()["data"]
        # Mantém a ordem de entrada (a API retorna cada item com seu index).
        return [item["embedding"] for item in sorted(dados, key=lambda d: d["index"])]
    raise RuntimeError("Voyage: esgotadas as tentativas (rate limit).")
