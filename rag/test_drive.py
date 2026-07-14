"""Testes da ingestão do RAG a partir do Google Drive (com OCR híbrido)."""

import pytest
from django.core.management import call_command

from rag import drive, ingest
from rag.models import Documento, Trecho

MAPA = {"Juridico": "direito", "Contábil": "contabilidade", "Gestão de Tráfego": "impulsionamento"}


def _pdf(fid, nome, md5, appprops=None):
    d = {"id": fid, "name": nome, "mimeType": "application/pdf", "md5Checksum": md5}
    if appprops is not None:
        d["appProperties"] = appprops
    return d


def _mock_drive(monkeypatch, arquivos, **extra):
    """Configura o cliente Drive falso. `arquivos` = lista de (arq, caminho, pasta_id)."""
    monkeypatch.setattr(drive, "abrir_servico", lambda: object())
    monkeypatch.setattr(drive, "percorrer", lambda *a, **k: iter(arquivos))
    monkeypatch.setattr(drive, "achar_artefato_ocr", extra.get("achar", lambda s, i: None))
    monkeypatch.setattr(drive, "baixar_bytes", extra.get("baixar", lambda s, a: b"bytes"))
    monkeypatch.setattr(drive, "texto_de_pdf", extra.get("texto_pdf", lambda d: "texto nativo"))
    monkeypatch.setattr(drive, "ocr_disponivel", extra.get("ocr_ok", lambda: False))
    monkeypatch.setattr(ingest, "ingerir", extra.get("ingerir", lambda doc, t, **k: []))


# --------------------------------------------------------------- classificação
def test_inferir_tipo_default_seguro_e_curso() -> None:
    assert drive.inferir_tipo(("Juridico", "Livros_Doutrina")) == "doutrina"
    assert drive.inferir_tipo(("Contábil", "Curso - Prestação de contas")) == "curso"
    assert drive.inferir_tipo(("X",)) == "doutrina"


def test_inferir_tipo_citaveis() -> None:
    assert drive.inferir_tipo(("Juridico", "Normas")) == "norma"
    assert drive.inferir_tipo(("Juridico", "Jurisprudência TSE")) == "jurisprudencia"


def test_classificar_mapeia_assunto_tipo_subtema() -> None:
    assert drive.classificar(("Juridico", "Livros_Doutrina"), MAPA) == (
        "direito",
        "doutrina",
        "Livros_Doutrina",
    )


def test_classificar_pasta_fora_do_mapa_retorna_none() -> None:
    assert drive.classificar(("Outra", "Sub"), MAPA)[0] is None


def test_eh_artefato_ocr() -> None:
    assert drive.eh_artefato_ocr({"name": "livro [OCR].txt"})
    assert drive.eh_artefato_ocr({"name": "x", "appProperties": {"ocr_source": "f1"}})
    assert not drive.eh_artefato_ocr({"name": "livro.pdf"})


# ------------------------------------------------------------------- comando
@pytest.mark.django_db
def test_comando_ingere_classifica_e_reconcilia(monkeypatch, settings) -> None:
    settings.GOOGLE_SERVICE_ACCOUNT_JSON = '{"fake": true}'
    settings.RAG_DRIVE_ASSUNTO_MAP = MAPA
    arquivos = [
        (_pdf("f1", "livro.pdf", "aaa"), ("Juridico", "Livros_Doutrina"), "p1"),
        (_pdf("f2", "curso.pdf", "bbb"), ("Contábil", "Curso - Prestação"), "p2"),
        (_pdf("f3", "x.pdf", "c"), ("Outra",), "p3"),  # fora do mapa → ignorado
    ]
    _mock_drive(monkeypatch, arquivos)
    call_command("ingerir_drive")

    docs = Documento.objects.filter(origem="drive")
    assert docs.count() == 2  # f3 ignorado
    d1 = docs.get(origem_id="f1")
    assert (d1.assunto, d1.tipo, d1.citavel, d1.subtema, d1.conteudo_hash) == (
        "direito",
        "doutrina",
        False,
        "Livros_Doutrina",
        "aaa",
    )

    # 2ª rodada: f2 sumiu do Drive → reconciliação
    _mock_drive(monkeypatch, arquivos[:1])
    call_command("ingerir_drive")
    assert Documento.objects.filter(origem="drive").count() == 1
    assert not Documento.objects.filter(origem_id="f2").exists()


@pytest.mark.django_db
def test_incremental_pula_sem_baixar(monkeypatch, settings) -> None:
    settings.GOOGLE_SERVICE_ACCOUNT_JSON = '{"fake": true}'
    settings.RAG_DRIVE_ASSUNTO_MAP = MAPA
    arq = [(_pdf("f1", "livro.pdf", "aaa"), ("Juridico", "Doutrina"), "p1")]
    baixados = []

    def fake_ingerir(doc, texto, **k):
        Trecho.objects.create(documento=doc, ordem=0, conteudo="x")
        return [1]

    _mock_drive(
        monkeypatch, arq, ingerir=fake_ingerir, baixar=lambda s, a: baixados.append(1) or b"x"
    )
    call_command("ingerir_drive")  # 1ª: baixa + ingere
    assert len(baixados) == 1

    call_command("ingerir_drive")  # 2ª: md5 igual + trechos existem → pula ANTES de baixar
    assert len(baixados) == 1  # não baixou de novo


@pytest.mark.django_db
def test_artefato_ocr_e_pulado_na_varredura(monkeypatch, settings) -> None:
    settings.GOOGLE_SERVICE_ACCOUNT_JSON = '{"fake": true}'
    settings.RAG_DRIVE_ASSUNTO_MAP = MAPA
    arquivos = [
        (_pdf("f1", "livro.pdf", "aaa"), ("Juridico", "Doutrina"), "p1"),
        # artefato [OCR] não deve virar documento
        ({"id": "a1", "name": "livro [OCR].txt", "mimeType": "text/plain"}, ("Juridico",), "p1"),
    ]
    _mock_drive(monkeypatch, arquivos)
    call_command("ingerir_drive")
    assert Documento.objects.filter(origem="drive").count() == 1


@pytest.mark.django_db
def test_somente_ocr_grava_artefato_sem_embed(monkeypatch, settings) -> None:
    settings.GOOGLE_SERVICE_ACCOUNT_JSON = '{"fake": true}'
    settings.RAG_DRIVE_ASSUNTO_MAP = MAPA
    arq = [(_pdf("f1", "scan.pdf", "aaa"), ("Contábil", "Livro - Doutrina"), "p1")]
    gravou = {}

    def fake_gravar(servico, **kw):
        gravou.update(kw)
        return "novoid"

    _mock_drive(
        monkeypatch,
        arq,
        texto_pdf=lambda d: "",  # scan: sem texto nativo → OCR
        ocr_ok=lambda: True,
    )
    monkeypatch.setattr(drive, "ocr_pdf", lambda dados, **k: "TEXTO OCR")
    monkeypatch.setattr(drive, "gravar_artefato_ocr", fake_gravar)

    call_command("ingerir_drive", "--somente-ocr")
    assert gravou["texto"] == "TEXTO OCR"
    assert gravou["origem_id"] == "f1"
    assert Documento.objects.filter(origem="drive").count() == 0  # não embeda


@pytest.mark.django_db
def test_ingest_usa_ocr_cache_sem_baixar(monkeypatch, settings) -> None:
    settings.GOOGLE_SERVICE_ACCOUNT_JSON = '{"fake": true}'
    settings.RAG_DRIVE_ASSUNTO_MAP = MAPA
    arq = [(_pdf("f1", "scan.pdf", "aaa"), ("Contábil", "Livro - Doutrina"), "p1")]
    textos_embed = []

    def sem_baixar(s, a):
        raise AssertionError("não deveria baixar o PDF quando há [OCR] fresco")

    _mock_drive(
        monkeypatch,
        arq,
        achar=lambda s, i: {"id": "a1", "appProperties": {"ocr_src_md5": "aaa"}},
        baixar=sem_baixar,
        ingerir=lambda doc, t, **k: textos_embed.append(t) or [],
    )
    monkeypatch.setattr(drive, "ler_texto_ocr", lambda s, fid: "TEXTO DO CACHE OCR")

    call_command("ingerir_drive")
    assert textos_embed == ["TEXTO DO CACHE OCR"]
    assert Documento.objects.filter(origem="drive").count() == 1
