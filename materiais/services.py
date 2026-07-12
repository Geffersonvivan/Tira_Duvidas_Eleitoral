"""Serviço 2 — Análise de material gráfico (lógica.md §6/§7).

Pipeline por peça: gate (é campanha BR?) → extração (visão+OCR) → RAG → parecer.
Aceita JPG/PNG/PDF e lote. Cada peça recebe um parecer independente.
As etapas que tocam LLM/RAG são injetáveis, para testar sem API nem Postgres.
"""

import base64
import json
from dataclasses import dataclass, field
from enum import StrEnum

from anthropic import BadRequestError

from llm import budget, client
from llm.config import Tarefa
from llm.router import escolher_modelo
from rag import embeddings
from rag.models import Documento
from rag.retriever import Recuperacao, buscar

FORMATOS_ACEITOS = frozenset({"jpg", "jpeg", "png", "pdf"})
_MEDIA_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "pdf": "application/pdf",
}

RESPOSTA_OFF_TOPIC = (
    "Essa peça não parece material de campanha eleitoral brasileira. 🗳️ "
    "Eu analiso santinhos e peças gráficas eleitorais quanto à legislação. "
    "Envie um material de campanha que eu confiro!"
)

RESPOSTA_IMAGEM_INVALIDA = (
    "Não consegui abrir essa imagem. 🖼️ Ela pode estar corrompida, muito pequena "
    "ou num formato que o leitor não processa. Reenvie um JPG, PNG ou PDF nítido da peça."
)

DISCLAIMER = (
    "Análise de apoio — não substitui conferência jurídica nem decisão da Justiça "
    "Eleitoral. A peça pode ter validade temporal conforme o calendário eleitoral."
)


class StatusParecer(StrEnum):
    CONFORME = "conforme"
    PARCIAL = "parcial"
    NAO_CONFORME = "nao_conforme"
    INCONCLUSIVO = "inconclusivo"


@dataclass
class Ponto:
    descricao: str
    conforme: bool | None  # True=ok, False=problema, None=verificar
    fundamento: str = ""


@dataclass
class Parecer:
    status: str
    pontos: list[Ponto] = field(default_factory=list)
    recomendacoes: str = ""
    fontes: list[Documento] = field(default_factory=list)
    disclaimer: str = DISCLAIMER


@dataclass
class ResultadoAnalise:
    peca: str
    on_topic: bool
    parecer: Parecer | None = None
    mensagem: str = ""


# ------------------------------------------------------------- utilidades
def extensao(nome: str) -> str:
    _, _, ext = nome.rpartition(".")
    return ext.lower()


def extensao_valida(nome: str) -> bool:
    return extensao(nome) in FORMATOS_ACEITOS


def media_type(nome: str) -> str:
    return _MEDIA_TYPES[extensao(nome)]


def _bloco_visual(dados: bytes, mtype: str, instrucao: str) -> list[dict]:
    b64 = base64.standard_b64encode(dados).decode()
    tipo = "document" if mtype == "application/pdf" else "image"
    return [
        {"type": tipo, "source": {"type": "base64", "media_type": mtype, "data": b64}},
        {"type": "text", "text": instrucao},
    ]


# ------------------------------------------------------------- etapas reais
def gate_campanha(dados: bytes, mtype: str) -> bool:
    """Gate de intenção da imagem (§6 passo 0): é campanha eleitoral BR?"""
    modelo = escolher_modelo(Tarefa.VISAO)
    conteudo = _bloco_visual(
        dados,
        mtype,
        "Esta peça é material de campanha eleitoral brasileira? Responda 'sim' ou 'nao'.",
    )
    resp = client.completar(
        modelo,
        "Você faz a triagem de peças gráficas.",
        [{"role": "user", "content": conteudo}],
        max_tokens=8,
    )
    budget.registrar_uso(modelo, Tarefa.VISAO, resp.tokens_entrada, resp.tokens_saida)
    return resp.texto.strip().lower().startswith("s")


def extrair_conteudo(dados: bytes, mtype: str) -> str:
    """Extrai texto e elementos da peça (visão + OCR)."""
    modelo = escolher_modelo(Tarefa.VISAO)
    conteudo = _bloco_visual(
        dados,
        mtype,
        "Transcreva todo o texto e descreva elementos relevantes (número, cargo, "
        "partido, símbolos, dados de identificação/tiragem) desta peça.",
    )
    resp = client.completar(
        modelo, "Você extrai conteúdo de peças gráficas.", [{"role": "user", "content": conteudo}]
    )
    budget.registrar_uso(modelo, Tarefa.VISAO, resp.tokens_entrada, resp.tokens_saida)
    return resp.texto


def recuperar_regras(texto: str) -> Recuperacao:
    """Recupera do RAG as regras de propaganda aplicáveis à peça."""
    vetor = embeddings.gerar_embedding(texto)
    return buscar(vetor, assunto=None)


def _parse_parecer(texto_json: str, fontes: list[Documento]) -> Parecer:
    """Converte a saída JSON da LLM em Parecer; falha segura → inconclusivo."""
    try:
        dados = json.loads(texto_json)
    except (json.JSONDecodeError, TypeError):
        return Parecer(
            status=StatusParecer.INCONCLUSIVO,
            recomendacoes="Não foi possível interpretar a análise da peça.",
            fontes=fontes,
        )
    status = dados.get("status")
    if status not in set(StatusParecer):
        status = StatusParecer.INCONCLUSIVO
    pontos = [
        Ponto(
            descricao=p.get("descricao", ""),
            conforme=p.get("conforme"),
            fundamento=p.get("fundamento", ""),
        )
        for p in dados.get("pontos", [])
    ]
    return Parecer(
        status=status,
        pontos=pontos,
        recomendacoes=dados.get("recomendacoes", ""),
        fontes=fontes,
    )


def avaliar_conformidade(texto: str, recuperacao: Recuperacao) -> Parecer:
    """Confronta a peça contra as regras do RAG e emite o parecer (§7)."""
    modelo = escolher_modelo(Tarefa.RESPONDER)
    contexto = "\n\n".join(t.conteudo for t in recuperacao.contexto)
    system = (
        "Você audita peças gráficas eleitorais contra a legislação. Use SOMENTE o "
        "CONTEXTO. Cite apenas norma e jurisprudência válidas (nunca doutrina/curso). "
        'Responda em JSON: {"status": um de '
        "['conforme','parcial','nao_conforme','inconclusivo'], "
        '"pontos": [{"descricao":str,"conforme":bool|null,"fundamento":str}], '
        '"recomendacoes": str}.\n\n'
        f"CONTEXTO:\n{contexto}"
    )
    resp = client.completar(modelo, system, [{"role": "user", "content": f"PEÇA:\n{texto}"}])
    budget.registrar_uso(modelo, Tarefa.RESPONDER, resp.tokens_entrada, resp.tokens_saida)
    return _parse_parecer(resp.texto, recuperacao.fontes_citaveis)


# ------------------------------------------------------------- orquestração
def analisar_peca(
    nome: str,
    dados: bytes,
    mtype: str,
    *,
    gate=None,
    extrair=None,
    recuperar=None,
    avaliar=None,
) -> ResultadoAnalise:
    """Analisa uma peça. Dependências resolvidas em tempo de chamada (injetáveis)."""
    gate = gate or gate_campanha
    extrair = extrair or extrair_conteudo
    recuperar = recuperar or recuperar_regras
    avaliar = avaliar or avaliar_conformidade

    try:
        if not gate(dados, mtype):
            return ResultadoAnalise(peca=nome, on_topic=False, mensagem=RESPOSTA_OFF_TOPIC)

        texto = extrair(dados, mtype)
        recuperacao = recuperar(texto)
        parecer = avaliar(texto, recuperacao)
        return ResultadoAnalise(peca=nome, on_topic=True, parecer=parecer)
    except BadRequestError:
        # Claude recusou a imagem (ex.: minúscula/corrompida) → 400. Degrada esta
        # peça com mensagem amigável em vez de derrubar a requisição inteira (500).
        return ResultadoAnalise(peca=nome, on_topic=False, mensagem=RESPOSTA_IMAGEM_INVALIDA)


def analisar_lote(pecas: list[tuple[str, bytes, str]], **seams) -> list[ResultadoAnalise]:
    """Analisa um lote: uma peça por vez, um parecer por peça (§6)."""
    return [analisar_peca(nome, dados, mtype, **seams) for nome, dados, mtype in pecas]
