"""Testes da ingestão do RAG a partir do Google Drive (OCR + cache no banco)."""

import pytest
from django.core.management import call_command

from rag import drive, ingest
from rag.models import Documento, Trecho

MAPA = {"Juridico": "direito", "Contábil": "contabilidade", "Gestão de Tráfego": "impulsionamento"}


def _pdf(fid, nome, md5):
    return {"id": fid, "name": nome, "mimeType": "application/pdf", "md5Checksum": md5}


def _mock(monkeypatch, arquivos, **extra):
    """Configura o cliente Drive falso. `arquivos` = lista de (arq, caminho)."""
    monkeypatch.setattr(drive, "abrir_servico", lambda: object())
    monkeypatch.setattr(drive, "percorrer", lambda *a, **k: iter(arquivos))
    monkeypatch.setattr(drive, "baixar_bytes", extra.get("baixar", lambda s, a: b"bytes"))
    monkeypatch.setattr(drive, "texto_de_pdf", extra.get("texto_pdf", lambda d: "texto nativo"))
    monkeypatch.setattr(drive, "ocr_disponivel", extra.get("ocr_ok", lambda: True))
    monkeypatch.setattr(ingest, "ingerir", extra.get("ingerir", lambda doc, t, **k: []))


# --------------------------------------------------------------- classificação
def test_inferir_tipo_default_seguro_e_curso() -> None:
    assert drive.inferir_tipo(("Juridico", "Livros_Doutrina")) == "doutrina"
    assert drive.inferir_tipo(("Contábil", "Curso - Prestação de contas")) == "curso"
    assert drive.inferir_tipo(("X",)) == "doutrina"


def test_inferir_tipo_citaveis() -> None:
    assert drive.inferir_tipo(("Juridico", "Normas")) == "norma"
    assert drive.inferir_tipo(("Juridico", "Jurisprudência TSE")) == "jurisprudencia"


def test_classificar() -> None:
    assert drive.classificar(("Juridico", "Livros_Doutrina"), MAPA) == (
        "direito",
        "doutrina",
        "Livros_Doutrina",
    )
    assert drive.classificar(("Outra", "Sub"), MAPA)[0] is None


# ------------------------------------------------------------------- comando
@pytest.mark.django_db
def test_ingere_classifica_e_reconcilia(monkeypatch, settings) -> None:
    settings.GOOGLE_SERVICE_ACCOUNT_JSON = '{"fake": true}'
    settings.RAG_DRIVE_ASSUNTO_MAP = MAPA
    arquivos = [
        (_pdf("f1", "livro.pdf", "aaa"), ("Juridico", "Livros_Doutrina")),
        (_pdf("f2", "curso.pdf", "bbb"), ("Contábil", "Curso - Prestação")),
        (_pdf("f3", "x.pdf", "c"), ("Outra",)),  # fora do mapa → ignorado
    ]
    _mock(monkeypatch, arquivos)
    call_command("ingerir_drive")

    docs = Documento.objects.filter(origem="drive")
    assert docs.count() == 2
    d1 = docs.get(origem_id="f1")
    assert (d1.assunto, d1.tipo, d1.citavel, d1.subtema, d1.conteudo_hash) == (
        "direito",
        "doutrina",
        False,
        "Livros_Doutrina",
        "aaa",
    )
    assert d1.texto_extraido == "texto nativo"  # cache preenchido

    _mock(monkeypatch, arquivos[:1])  # f2 sumiu → reconciliação
    call_command("ingerir_drive")
    assert Documento.objects.filter(origem="drive").count() == 1
    assert not Documento.objects.filter(origem_id="f2").exists()


@pytest.mark.django_db
def test_incremental_pula_sem_baixar(monkeypatch, settings) -> None:
    settings.GOOGLE_SERVICE_ACCOUNT_JSON = '{"fake": true}'
    settings.RAG_DRIVE_ASSUNTO_MAP = MAPA
    arq = [(_pdf("f1", "livro.pdf", "aaa"), ("Juridico", "Doutrina"))]
    baixados = []

    def cria_trecho(doc, t, **k):
        Trecho.objects.create(documento=doc, ordem=0, conteudo="x")
        return [1]

    _mock(monkeypatch, arq, baixar=lambda s, a: baixados.append(1) or b"x", ingerir=cria_trecho)
    call_command("ingerir_drive")  # 1ª: baixa + ingere
    assert len(baixados) == 1
    call_command("ingerir_drive")  # 2ª: md5 igual + trechos → pula ANTES de baixar
    assert len(baixados) == 1


@pytest.mark.django_db
def test_scan_faz_ocr_e_cacheia(monkeypatch, settings) -> None:
    settings.GOOGLE_SERVICE_ACCOUNT_JSON = '{"fake": true}'
    settings.RAG_DRIVE_ASSUNTO_MAP = MAPA
    arq = [(_pdf("f1", "scan.pdf", "aaa"), ("Contábil", "Livro - Doutrina"))]
    ocr_chamado = []
    _mock(
        monkeypatch,
        arq,
        texto_pdf=lambda d: "",  # scan: sem texto nativo → OCR
        ingerir=lambda doc, t, **k: [],
    )
    monkeypatch.setattr(drive, "ocr_pdf", lambda dados, **k: ocr_chamado.append(1) or "TEXTO OCR")

    call_command("ingerir_drive")
    assert len(ocr_chamado) == 1
    assert Documento.objects.get(origem_id="f1").texto_extraido == "TEXTO OCR"


@pytest.mark.django_db
def test_reindexa_do_cache_sem_reocr(monkeypatch, settings) -> None:
    """md5 igual mas sem trechos (ex.: reembed): usa o cache, não baixa nem OCRa."""
    settings.GOOGLE_SERVICE_ACCOUNT_JSON = '{"fake": true}'
    settings.RAG_DRIVE_ASSUNTO_MAP = MAPA
    Documento.objects.create(
        origem="drive",
        origem_id="f1",
        titulo="scan",
        tipo="doutrina",
        assunto="contabilidade",
        conteudo_hash="aaa",
        texto_extraido="TEXTO EM CACHE",
    )
    arq = [(_pdf("f1", "scan.pdf", "aaa"), ("Contábil", "Livro - Doutrina"))]
    embutidos = []

    def nao_baixa(s, a):
        raise AssertionError("não deveria baixar quando há cache com md5 igual")

    _mock(monkeypatch, arq, baixar=nao_baixa, ingerir=lambda doc, t, **k: embutidos.append(t) or [])
    monkeypatch.setattr(drive, "ocr_pdf", lambda *a, **k: pytest.fail("não deveria re-OCRar"))

    call_command("ingerir_drive")
    assert embutidos == ["TEXTO EM CACHE"]


# ---------------------------------------------- resiliência e 0 trechos
@pytest.mark.django_db
def test_falha_de_embedding_nao_aborta_lote(monkeypatch, settings) -> None:
    """Cota estourada num doc não derruba os outros; doc fica p/ --so-vazios."""
    settings.GOOGLE_SERVICE_ACCOUNT_JSON = '{"fake": true}'
    settings.RAG_DRIVE_ASSUNTO_MAP = MAPA
    arquivos = [
        (_pdf("f1", "quebra.pdf", "aaa"), ("Juridico", "Doutrina")),
        (_pdf("f2", "ok.pdf", "bbb"), ("Juridico", "Doutrina")),
    ]

    def ingerir(doc, t, **k):
        if doc.origem_id == "f1":
            raise RuntimeError("Voyage: esgotadas as tentativas (rate limit).")
        Trecho.objects.create(documento=doc, ordem=0, conteudo="x")
        return [1]

    _mock(monkeypatch, arquivos, ingerir=ingerir)
    call_command("ingerir_drive")  # não deve levantar

    # f1 persiste com 0 trechos (cache guardado); f2 indexado normalmente.
    assert Documento.objects.get(origem_id="f1").trechos.count() == 0
    assert Documento.objects.get(origem_id="f1").texto_extraido == "texto nativo"
    assert Documento.objects.get(origem_id="f2").trechos.count() == 1


@pytest.mark.django_db
def test_so_vazios_reprocessa_apenas_docs_sem_trechos(monkeypatch, settings) -> None:
    settings.GOOGLE_SERVICE_ACCOUNT_JSON = '{"fake": true}'
    settings.RAG_DRIVE_ASSUNTO_MAP = MAPA
    # f1 já indexado (tem trecho); f2 registrado mas vazio (falhou antes).
    cheio = Documento.objects.create(
        origem="drive",
        origem_id="f1",
        titulo="cheio",
        tipo="doutrina",
        assunto="direito",
        conteudo_hash="aaa",
        texto_extraido="T1",
    )
    Trecho.objects.create(documento=cheio, ordem=0, conteudo="ja tem")
    Documento.objects.create(
        origem="drive",
        origem_id="f2",
        titulo="vazio",
        tipo="doutrina",
        assunto="direito",
        conteudo_hash="bbb",
        texto_extraido="T2",
    )
    arquivos = [
        (_pdf("f1", "cheio.pdf", "aaa"), ("Juridico", "Doutrina")),
        (_pdf("f2", "vazio.pdf", "bbb"), ("Juridico", "Doutrina")),
    ]
    tocados = []

    def ingerir(doc, t, **k):
        tocados.append(doc.origem_id)
        Trecho.objects.create(documento=doc, ordem=0, conteudo="novo")
        return [1]

    _mock(monkeypatch, arquivos, ingerir=ingerir)
    call_command("ingerir_drive", "--so-vazios")

    assert tocados == ["f2"]  # só o vazio foi reprocessado
    assert Documento.objects.get(origem_id="f2").trechos.count() == 1


@pytest.mark.django_db
def test_so_vazios_nao_reconcilia(monkeypatch, settings) -> None:
    """Modo parcial não pode apagar docs ausentes da lista (visão incompleta)."""
    settings.GOOGLE_SERVICE_ACCOUNT_JSON = '{"fake": true}'
    settings.RAG_DRIVE_ASSUNTO_MAP = MAPA
    Documento.objects.create(
        origem="drive",
        origem_id="outro",
        titulo="não listado",
        tipo="doutrina",
        assunto="direito",
        conteudo_hash="zzz",
    )
    _mock(monkeypatch, [])  # árvore "vazia" nesta chamada
    call_command("ingerir_drive", "--so-vazios")
    assert Documento.objects.filter(origem_id="outro").exists()  # não foi reconciliado
