"""Teste do comando de ingestão (embeddings mockados)."""

import json

import pytest
from django.core.management import call_command

from rag import embeddings
from rag.models import Documento


@pytest.mark.django_db
def test_comando_ingerir_cria_documento_e_trechos(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        embeddings, "gerar_embeddings", lambda textos, **k: [[0.1, 0.2, 0.3] for _ in textos]
    )
    manifesto = tmp_path / "manifesto.json"
    manifesto.write_text(
        json.dumps(
            [
                {
                    "titulo": "Lei nº 9.504/1997 — art. 57-C",
                    "tipo": "norma",
                    "assunto": "impulsionamento",
                    "fonte_url": "https://www.planalto.gov.br/",
                    "texto": "Da propaganda na internet. " * 80,
                }
            ]
        ),
        encoding="utf-8",
    )

    call_command("ingerir", str(manifesto))

    doc = Documento.objects.get(titulo="Lei nº 9.504/1997 — art. 57-C")
    assert doc.pode_citar is True  # norma vigente marcada como citável
    assert doc.trechos.count() > 0


@pytest.mark.django_db
def test_comando_ingerir_reingestao_nao_duplica(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(embeddings, "gerar_embeddings", lambda textos, **k: [[0.0] for _ in textos])
    manifesto = tmp_path / "m.json"
    manifesto.write_text(
        json.dumps([{"titulo": "Doc", "tipo": "norma", "assunto": "direito", "texto": "x" * 500}]),
        encoding="utf-8",
    )

    call_command("ingerir", str(manifesto))
    n1 = Documento.objects.get(titulo="Doc").trechos.count()
    call_command("ingerir", str(manifesto))  # re-ingestão
    n2 = Documento.objects.get(titulo="Doc").trechos.count()

    assert Documento.objects.filter(titulo="Doc").count() == 1  # não duplica documento
    assert n1 == n2  # nem trechos
