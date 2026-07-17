"""Ingestão de documentos no RAG: divide em chunks, gera embeddings e persiste.

A citabilidade não é decidida aqui — vem do `Documento` (tipo/vigência). A
ingestão apenas indexa o conteúdo para busca semântica.
"""

import re

from rag import embeddings
from rag.models import Documento, Trecho

#: Marcadores de estrutura jurídica onde é preferível cortar um chunk (início de
#: linha): "Art. 5º", "Artigo 5", "§ 2", "Parágrafo único", "Capítulo II",
#: "Seção I", "TÍTULO III", incisos "I -"/"II -". Preserva a unidade normativa
#: no mesmo trecho, em vez de cortá-la no meio como a janela cega fazia.
_MARCADOR_JURIDICO = re.compile(
    r"(?m)^\s*(?:"
    r"Art(?:igo|\.)\s*\d+|"
    r"§\s*\d+|Parágrafo\s+único|"
    r"(?:Cap[íi]tulo|Se[çc][ãa]o|T[íi]tulo|Livro)\s+[IVXLCDM0-9]+|"
    r"[IVXLCDM]+\s*[-–—)]"
    r")",
    re.IGNORECASE,
)


def _quebrar_por_marcadores(texto: str) -> list[str]:
    """Fatia o texto nos marcadores jurídicos (cada fatia começa num marcador).

    Se não houver marcador (ex.: doutrina em prosa), devolve o texto inteiro numa
    fatia só — a janela deslizante em `dividir_em_chunks` cuida do tamanho depois.
    """
    posicoes = [m.start() for m in _MARCADOR_JURIDICO.finditer(texto)]
    if not posicoes:
        return [texto]
    if posicoes[0] != 0:
        posicoes.insert(0, 0)  # preâmbulo antes do 1º artigo vira a 1ª fatia
    limites = posicoes[1:] + [len(texto)]
    fatias = [texto[ini:fim] for ini, fim in zip(posicoes, limites, strict=True)]
    return [f for f in (s.strip() for s in fatias) if f]


def _janela(texto: str, *, tamanho: int, sobreposicao: int) -> list[str]:
    """Janela deslizante de `tamanho` com `sobreposicao` (fallback e sub-divisão)."""
    chunks: list[str] = []
    inicio, n = 0, len(texto)
    while inicio < n:
        fim = inicio + tamanho
        chunks.append(texto[inicio:fim])
        if fim >= n:
            break
        inicio = fim - sobreposicao
    return chunks


def dividir_em_chunks(texto: str, *, tamanho: int = 1000, sobreposicao: int = 150) -> list[str]:
    """Divide o texto respeitando a estrutura jurídica quando existir.

    Primeiro corta nos marcadores (Art./§/Capítulo/inciso); cada unidade que
    ainda passar de `tamanho` é sub-dividida por janela com `sobreposicao`.
    Texto sem estrutura (prosa) cai direto na janela — comportamento antigo.
    """
    if sobreposicao >= tamanho:
        raise ValueError("sobreposicao deve ser menor que tamanho")
    texto = texto.strip()
    if not texto:
        return []

    chunks: list[str] = []
    for unidade in _quebrar_por_marcadores(texto):
        if len(unidade) <= tamanho:
            chunks.append(unidade)
        else:
            chunks.extend(_janela(unidade, tamanho=tamanho, sobreposicao=sobreposicao))
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
