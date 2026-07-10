"""Roteamento por complexidade (cost-aware-llm-pipeline, lógica.md §13).

Escolhe o modelo pela tarefa e permite **escalar** para o modelo forte quando a
resposta sai com baixa confiança (ex.: caso jurídico ambíguo).
"""

from llm.config import Tarefa, modelo_para


def escolher_modelo(tarefa: Tarefa, *, baixa_confianca: bool = False) -> str:
    """ID do modelo para a tarefa; escala para COMPLEXO se baixa confiança."""
    if baixa_confianca and tarefa in (Tarefa.RESPONDER, Tarefa.VISAO):
        return modelo_para(Tarefa.COMPLEXO)
    return modelo_para(tarefa)
