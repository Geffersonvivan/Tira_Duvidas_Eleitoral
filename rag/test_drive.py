"""Testes da ingestão do RAG a partir do Google Drive."""

import pytest
from django.core.management import call_command

from rag import drive
from rag.models import Documento

MAPA = {"Juridico": "direito", "Contábil": "contabilidade", "Gestão de Tráfego": "impulsionamento"}


# --------------------------------------------------------------- classificação
def test_inferir_tipo_default_seguro_e_curso() -> None:
    assert drive.inferir_tipo(("Juridico", "Livros_Doutrina")) == "doutrina"
    assert drive.inferir_tipo(("Contábil", "Curso - Prestação de contas")) == "curso"
    assert drive.inferir_tipo(("X",)) == "doutrina"  # desconhecido → contexto


def test_inferir_tipo_citaveis() -> None:
    assert drive.inferir_tipo(("Juridico", "Normas")) == "norma"
    assert drive.inferir_tipo(("Juridico", "Jurisprudência TSE")) == "jurisprudencia"


def test_classificar_mapeia_assunto_tipo_subtema() -> None:
    assunto, tipo, subtema = drive.classificar(("Juridico", "Livros_Doutrina"), MAPA)
    assert (assunto, tipo, subtema) == ("direito", "doutrina", "Livros_Doutrina")


def test_classificar_pasta_fora_do_mapa_retorna_none() -> None:
    assunto, _, _ = drive.classificar(("Outra", "Sub"), MAPA)
    assert assunto is None


def test_extrair_texto_txt() -> None:
    arq = {"name": "nota.txt", "mimeType": "text/plain"}
    assert drive.extrair_texto(arq, "olá mundo".encode()) == "olá mundo"


# ------------------------------------------------------------------- comando
@pytest.mark.django_db
def test_comando_ingere_classifica_e_reconcilia(monkeypatch, settings) -> None:
    settings.GOOGLE_SERVICE_ACCOUNT_JSON = '{"fake": true}'
    settings.RAG_DRIVE_ROOT_FOLDER_ID = "raiz"
    settings.RAG_DRIVE_ASSUNTO_MAP = MAPA

    arquivos = [
        (
            {"id": "f1", "name": "livro.pdf", "mimeType": "application/pdf", "md5Checksum": "aaa"},
            ("Juridico", "Livros_Doutrina"),
        ),
        (
            {"id": "f2", "name": "curso.pdf", "mimeType": "application/pdf", "md5Checksum": "bbb"},
            ("Contábil", "Curso - Prestação de contas"),
        ),
        # pasta fora do mapa → ignorado
        (
            {"id": "f3", "name": "x.pdf", "mimeType": "application/pdf", "md5Checksum": "c"},
            ("Outra",),
        ),
    ]
    monkeypatch.setattr(drive, "abrir_servico", lambda: object())
    monkeypatch.setattr(drive, "percorrer", lambda *a, **k: iter(arquivos))
    monkeypatch.setattr(drive, "baixar_bytes", lambda servico, arq: b"bytes")
    monkeypatch.setattr(drive, "extrair_texto", lambda arq, dados: "texto do " + arq["name"])
    # não gera embeddings de verdade (sem Voyage / pgvector no teste)
    from rag import ingest

    monkeypatch.setattr(ingest, "ingerir", lambda doc, texto, **k: [])

    call_command("ingerir_drive")

    docs = Documento.objects.filter(origem="drive")
    assert docs.count() == 2  # f3 (fora do mapa) foi ignorado
    d1 = docs.get(origem_id="f1")
    assert d1.assunto == "direito"
    assert d1.tipo == "doutrina"
    assert d1.citavel is False  # doutrina nunca é citável
    assert d1.subtema == "Livros_Doutrina"
    assert d1.conteudo_hash == "aaa"

    # 2ª rodada: f2 sumiu do Drive → reconciliação remove
    monkeypatch.setattr(drive, "percorrer", lambda *a, **k: iter(arquivos[:1]))
    call_command("ingerir_drive")
    assert Documento.objects.filter(origem="drive").count() == 1
    assert not Documento.objects.filter(origem_id="f2").exists()


@pytest.mark.django_db
def test_comando_incremental_pula_inalterado(monkeypatch, settings) -> None:
    from rag import ingest
    from rag.models import Trecho

    settings.GOOGLE_SERVICE_ACCOUNT_JSON = '{"fake": true}'
    settings.RAG_DRIVE_ASSUNTO_MAP = MAPA
    arq = (
        {"id": "f1", "name": "livro.pdf", "mimeType": "application/pdf", "md5Checksum": "aaa"},
        ("Juridico", "Livros_Doutrina"),
    )
    monkeypatch.setattr(drive, "abrir_servico", lambda: object())
    monkeypatch.setattr(drive, "percorrer", lambda *a, **k: iter([arq]))
    monkeypatch.setattr(drive, "baixar_bytes", lambda servico, a: b"x")
    monkeypatch.setattr(drive, "extrair_texto", lambda a, dados: "texto")

    chamadas = []

    def fake_ingerir(doc, texto, **k):
        chamadas.append(doc)
        Trecho.objects.create(documento=doc, ordem=0, conteudo="x")  # embedding None
        return [1]

    monkeypatch.setattr(ingest, "ingerir", fake_ingerir)

    call_command("ingerir_drive")  # 1ª: ingere f1 (cria trecho)
    assert len(chamadas) == 1

    call_command("ingerir_drive")  # 2ª: md5 igual + trechos existem → pula
    assert len(chamadas) == 1  # não re-ingeriu
