"""Ingestão de documentos no RAG: divide em chunks, gera embeddings e persiste.

A citabilidade não é decidida aqui — vem do `Documento` (tipo/vigência). A
ingestão apenas indexa o conteúdo para busca semântica.
"""

from rag import embeddings
from rag.models import Documento, Trecho


def dividir_em_chunks(texto: str, *, tamanho: int = 1000, sobreposicao: int = 150) -> list[str]:
    """Divide o texto em janelas de `tamanho` com `sobreposicao` entre elas."""
    if sobreposicao >= tamanho:
        raise ValueError("sobreposicao deve ser menor que tamanho")
    texto = texto.strip()
    if not texto:
        return []

    chunks: list[str] = []
    inicio, n = 0, len(texto)
    while inicio < n:
        fim = inicio + tamanho
        chunks.append(texto[inicio:fim])
        if fim >= n:
            break
        inicio = fim - sobreposicao
    return chunks


def ingerir(
    documento: Documento,
    texto_completo: str,
    *,
    tamanho: int = 1000,
    sobreposicao: int = 150,
) -> list[Trecho]:
    """Indexa um documento: chunk + embedding + persistência dos trechos."""
    chunks = dividir_em_chunks(texto_completo, tamanho=tamanho, sobreposicao=sobreposicao)
    if not chunks:
        return []

    vetores = embeddings.gerar_embeddings(chunks, input_type="document")
    trechos = [
        Trecho(documento=documento, ordem=i, conteudo=chunk, embedding=vetor)
        for i, (chunk, vetor) in enumerate(zip(chunks, vetores, strict=True))
    ]
    return Trecho.objects.bulk_create(trechos)
