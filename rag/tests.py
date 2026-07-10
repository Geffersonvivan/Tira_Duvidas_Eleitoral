"""Testes do RAG: a regra de citação inviolável (lógica.md §1)."""

import pytest
from django.core.exceptions import ValidationError

from rag.models import Assunto, Documento, TipoFonte, Trecho
from rag.retriever import separar_por_citabilidade


def _doc(tipo: str, *, citavel: bool = False, vigente: bool = True) -> Documento:
    return Documento.objects.create(
        titulo=f"Doc {tipo}",
        tipo=tipo,
        assunto=Assunto.IMPULSIONAMENTO,
        citavel=citavel,
        vigente=vigente,
    )


@pytest.mark.django_db
def test_doutrina_nao_pode_ser_citavel() -> None:
    doc = Documento(
        titulo="Manual de Doutrina",
        tipo=TipoFonte.DOUTRINA,
        assunto=Assunto.DIREITO,
        citavel=True,  # tentativa inválida
    )
    with pytest.raises(ValidationError):
        doc.full_clean()


@pytest.mark.django_db
def test_save_forca_citavel_false_para_tipo_nao_citavel() -> None:
    doc = _doc(TipoFonte.CURSO, citavel=True)
    doc.refresh_from_db()
    assert doc.citavel is False
    assert doc.pode_citar is False


@pytest.mark.django_db
def test_norma_vigente_pode_citar() -> None:
    doc = _doc(TipoFonte.NORMA, citavel=True)
    assert doc.pode_citar is True


@pytest.mark.django_db
def test_norma_revogada_nao_pode_citar() -> None:
    doc = _doc(TipoFonte.NORMA, citavel=True, vigente=False)
    assert doc.pode_citar is False


@pytest.mark.django_db
def test_manager_citaveis_exclui_doutrina() -> None:
    _doc(TipoFonte.NORMA, citavel=True)
    _doc(TipoFonte.DOUTRINA, citavel=True)  # será forçado a False
    citaveis = list(Documento.objects.citaveis())
    assert len(citaveis) == 1
    assert citaveis[0].tipo == TipoFonte.NORMA


@pytest.mark.django_db
def test_separar_por_citabilidade_so_retorna_fontes_validas() -> None:
    norma = _doc(TipoFonte.NORMA, citavel=True)
    juris = _doc(TipoFonte.JURISPRUDENCIA, citavel=True)
    curso = _doc(TipoFonte.CURSO)

    trechos = [
        Trecho.objects.create(documento=norma, ordem=0, conteudo="art. X"),
        Trecho.objects.create(documento=juris, ordem=0, conteudo="acórdão Y"),
        Trecho.objects.create(documento=curso, ordem=0, conteudo="apostila Z"),
    ]

    rec = separar_por_citabilidade(trechos)

    # contexto inclui os 3; fontes citáveis, só norma + jurisprudência.
    assert len(rec.contexto) == 3
    tipos_citaveis = {d.tipo for d in rec.fontes_citaveis}
    assert tipos_citaveis == {TipoFonte.NORMA, TipoFonte.JURISPRUDENCIA}
