"""Serviço 1 — Perguntas eleitorais (lógica.md §4).

Pipeline: classificar intenção (gate) → RAG → LLM ancorada → citação → auditoria.
As três etapas de fora (classificar/recuperar/gerar) são injetáveis, para testar
o pipeline sem tocar API, Postgres ou provedor de embeddings.
"""

from dataclasses import dataclass, field

from llm import budget, client
from llm.config import Tarefa
from llm.router import escolher_modelo
from rag import embeddings
from rag.models import Assunto, Documento
from rag.retriever import Recuperacao, buscar

# Resposta descontraída para fora de escopo (lógica.md §5).
RESPOSTA_OFF_TOPIC = (
    "Haha, adoraria — mas confesso que minha praia é urna, não forno. 🗳️ "
    "Eu cuido de **direito eleitoral, contabilidade de campanha e impulsionamento**. "
    "Se tiver alguma dúvida nesses temas, é só mandar!"
)

DISCLAIMER = (
    "Esta resposta tem caráter informativo e de apoio, não substitui análise "
    "jurídica individualizada nem parecer oficial da Justiça Eleitoral. Confirme "
    "sempre a legislação vigente e os prazos aplicáveis ao seu caso."
)

_LABEL_PARA_ASSUNTO = {a.value: a for a in Assunto}


@dataclass
class Classificacao:
    on_topic: bool
    assunto: str | None = None


@dataclass
class RespostaPergunta:
    on_topic: bool
    texto: str
    assunto: str | None = None
    disclaimer: str = ""
    fontes: list[Documento] = field(default_factory=list)


# ------------------------------------------------------------- etapas reais
def classificar_intencao(pergunta: str) -> Classificacao:
    """Gate (§3): decide o assunto ou marca fora de escopo, via modelo leve."""
    modelo = escolher_modelo(Tarefa.CLASSIFICAR)
    system = (
        "Você classifica dúvidas para um assistente eleitoral brasileiro. "
        "Responda com UMA palavra, exatamente uma de: "
        "direito, contabilidade, impulsionamento, fora. "
        "Use 'fora' para qualquer assunto que não seja direito eleitoral, "
        "contabilidade eleitoral ou impulsionamento eleitoral."
    )
    resp = client.completar(modelo, system, [{"role": "user", "content": pergunta}], max_tokens=16)
    budget.registrar_uso(modelo, Tarefa.CLASSIFICAR, resp.tokens_entrada, resp.tokens_saida)

    rotulo = resp.texto.strip().lower()
    assunto = _LABEL_PARA_ASSUNTO.get(rotulo)
    if assunto is None:
        return Classificacao(on_topic=False)
    return Classificacao(on_topic=True, assunto=assunto.value)


def recuperar_contexto(pergunta: str, assunto: str, vetor: list | None = None) -> Recuperacao:
    """Recupera trechos do RAG (contexto + fontes citáveis).

    Aceita um `vetor` já calculado (reuso pelo orquestrador — evita embutir a
    pergunta duas vezes); se ausente, calcula.
    """
    if vetor is None:
        vetor = embeddings.gerar_embedding(pergunta)
    return buscar(vetor, assunto=assunto)


def gerar_resposta(pergunta: str, recuperacao: Recuperacao) -> str:
    """Redige a resposta ancorada no contexto recuperado (§4)."""
    modelo = escolher_modelo(Tarefa.RESPONDER)
    contexto = "\n\n".join(t.conteudo for t in recuperacao.contexto)
    system = (
        "Você é um assistente jurídico eleitoral brasileiro. Responda SOMENTE com "
        "base no CONTEXTO fornecido. Nunca invente artigo, resolução ou prazo. "
        "Cite apenas norma e jurisprudência válidas; jamais cite doutrina, curso ou "
        "material de apoio. Se o contexto não cobrir o ponto, admita a incerteza.\n\n"
        f"CONTEXTO:\n{contexto}"
    )
    resp = client.completar(modelo, system, [{"role": "user", "content": pergunta}])
    budget.registrar_uso(modelo, Tarefa.RESPONDER, resp.tokens_entrada, resp.tokens_saida)
    return resp.texto


# ------------------------------------------------------------- orquestração
def responder_pergunta(
    pergunta: str,
    *,
    classificar=None,
    recuperar=None,
    gerar=None,
    registrar=None,
) -> RespostaPergunta:
    """Orquestra o Serviço 1. Dependências resolvidas em tempo de chamada
    (permite injeção nos testes; em produção usa as etapas reais).

    `registrar` captura a pergunta para o ranqueamento (analytics), reusando o
    embedding já calculado. É best-effort e nunca deve quebrar a resposta."""
    classificar = classificar or classificar_intencao
    recuperar = recuperar or recuperar_contexto
    gerar = gerar or gerar_resposta
    if registrar is None:
        from analytics.services import capturar_seguro

        registrar = capturar_seguro

    cls = classificar(pergunta)
    if not cls.on_topic:
        registrar(pergunta, assunto=None, vetor=None, on_topic=False)
        return RespostaPergunta(on_topic=False, texto=RESPOSTA_OFF_TOPIC)

    vetor = embeddings.gerar_embedding(pergunta)  # calculado uma vez, reusado abaixo
    recuperacao = recuperar(pergunta, cls.assunto, vetor)
    texto = gerar(pergunta, recuperacao)
    registrar(pergunta, assunto=cls.assunto, vetor=vetor, on_topic=True)
    return RespostaPergunta(
        on_topic=True,
        texto=texto,
        assunto=cls.assunto,
        disclaimer=DISCLAIMER,
        fontes=recuperacao.fontes_citaveis,
    )
