"""Golden set de recuperação (avaliação de qualidade do RAG).

Um conjunto curado de perguntas com os títulos de documento que DEVEM aparecer
na recuperação. Serve para medir recall@k e pegar regressões (ex.: um filtro
novo que passa a derrubar contexto útil, ou a troca de embedding/threshold).

Formato de cada caso:
    {"pergunta": str, "assunto": str|None, "fontes_esperadas": [substr_do_titulo]}

`fontes_esperadas` casa por substring no título do Documento recuperado — assim o
caso não quebra por variação de pontuação/acento no título.

Popule `CASOS` com perguntas reais do seu domínio (o app `analytics` ranqueia as
mais frequentes — bom ponto de partida). O harness vive em
`rag/management/commands/avaliar_rag.py`.
"""

# Exemplos ilustrativos — SUBSTITUA por casos reais do corpus antes de confiar
# nos números. Mantidos poucos e genéricos de propósito.
CASOS: list[dict] = [
    {
        "pergunta": "Posso impulsionar publicação de campanha nas redes sociais?",
        "assunto": "impulsionamento",
        "fontes_esperadas": ["9.504"],  # Lei das Eleições
    },
    {
        "pergunta": "Qual o prazo para prestação de contas de campanha?",
        "assunto": "contabilidade",
        "fontes_esperadas": ["prestação de contas"],
    },
]


def recall_do_caso(titulos_recuperados: list[str], esperadas: list[str]) -> float:
    """Fração das fontes esperadas presentes (match por substring, caixa-insensível)."""
    if not esperadas:
        return 1.0
    alvo = [t.lower() for t in titulos_recuperados]
    achou = sum(any(e.lower() in t for t in alvo) for e in esperadas)
    return achou / len(esperadas)
