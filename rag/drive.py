"""Cliente do Google Drive para a ingestão do RAG (fonte viva).

Autentica com uma **conta de serviço** (sem login interativo — roda no
servidor), varre a árvore de pastas e baixa/extrai o texto dos arquivos.

PDFs escaneados (sem camada de texto) passam por **OCR uma única vez**: o texto
é gravado de volta no Drive como um artefato ``<nome> [OCR].txt`` (marcado em
`appProperties` com o id/md5 do PDF de origem). Nas próximas rodadas, a
ingestão lê esse texto e **pula o OCR** — o livro é "lido" só uma vez na vida.
Por isso o escopo é de leitura **e escrita** no Drive.

A classificação (`classificar`/`inferir_tipo`) é pura e testável, sem tocar na
rede. Os imports do Google/OCR ficam dentro das funções de I/O, de propósito.
"""

import io
import shutil

from django.conf import settings

# Leitura + escrita: precisamos criar/atualizar os artefatos [OCR] no Drive.
_SCOPES = ["https://www.googleapis.com/auth/drive"]
_MIME_PASTA = "application/vnd.google-apps.folder"
_MIME_GDOC = "application/vnd.google-apps.document"

#: appProperty que liga o .txt de OCR ao PDF de origem (id) e ao md5 da origem.
_PROP_ORIGEM = "ocr_source"
_PROP_MD5 = "ocr_src_md5"
_SUFIXO_OCR = " [OCR].txt"


# --------------------------------------------------------------- classificação
def inferir_tipo(caminho: tuple[str, ...]) -> str:
    """Deriva o `tipo` (rag.models.TipoFonte) pelo nome das subpastas.

    Default **seguro**: doutrina (contexto, não citável). Só vira citável
    (norma/jurisprudência) se a subpasta disser isso explicitamente.
    """
    junto = " ".join(caminho).lower()
    if any(k in junto for k in ("jurisprud", "acórdão", "acordao", "ementa", "acordãos")):
        return "jurisprudencia"
    if any(k in junto for k in ("norma", "legisla", "resolu", "lei ", "leis")):
        return "norma"
    if "curso" in junto:
        return "curso"
    return "doutrina"


def classificar(caminho: tuple[str, ...], assunto_map: dict) -> tuple[str | None, str, str]:
    """Do caminho de pastas (sem a raiz) deriva (assunto, tipo, subtema).

    `caminho[0]` = pasta-raiz (assunto, via mapa); demais níveis = subtema.
    Retorna assunto=None quando a pasta-raiz não está no mapa (arquivo ignorado).
    """
    if not caminho:
        return None, "doutrina", ""
    assunto = assunto_map.get(caminho[0])
    tipo = inferir_tipo(caminho)
    subtema = "/".join(caminho[1:])
    return assunto, tipo, subtema


def eh_artefato_ocr(arquivo: dict) -> bool:
    """True se o arquivo é um texto [OCR] que geramos (não é doc primário)."""
    props = arquivo.get("appProperties") or {}
    return _PROP_ORIGEM in props or (arquivo.get("name", "").endswith(_SUFIXO_OCR))


# ------------------------------------------------------------------- extração
def texto_de_pdf(dados: bytes) -> str:
    """Texto da camada nativa do PDF (vazio se for escaneado/imagem)."""
    from pypdf import PdfReader

    leitor = PdfReader(io.BytesIO(dados))
    return "\n".join((pag.extract_text() or "") for pag in leitor.pages)


def extrair_texto(arquivo: dict, dados: bytes) -> str:
    """Texto direto de txt/markdown/Google Docs (sem OCR). PDF: camada nativa."""
    nome = (arquivo.get("name") or "").lower()
    mime = arquivo.get("mimeType") or ""
    if mime == _MIME_GDOC or nome.endswith((".txt", ".md")):
        return dados.decode("utf-8", errors="ignore")
    if mime == "application/pdf" or nome.endswith(".pdf"):
        return texto_de_pdf(dados)
    return ""  # formato não suportado (ex.: .docx) — ignora por ora


def ocr_disponivel() -> bool:
    """True se tesseract + poppler estão instalados no sistema."""
    return bool(shutil.which("tesseract") and shutil.which("pdftoppm"))


def ocr_pdf(
    dados: bytes, *, lang: str = "por", dpi: int = 300, lote: int = 5, progresso=None
) -> str:
    """OCR de um PDF escaneado → texto. Requer tesseract+poppler no sistema.

    Renderiza em lotes pequenos (memória previsível) e chama `progresso(feito,
    total)` a cada lote, para o acompanhamento ao vivo em livros longos.
    """
    import pytesseract
    from pdf2image import convert_from_bytes, pdfinfo_from_bytes

    total = int(pdfinfo_from_bytes(dados)["Pages"])
    partes: list[str] = []
    for ini in range(1, total + 1, lote):
        fim = min(ini + lote - 1, total)
        for img in convert_from_bytes(dados, dpi=dpi, first_page=ini, last_page=fim):
            partes.append(pytesseract.image_to_string(img, lang=lang))
        if progresso:
            progresso(fim, total)
    return "\n".join(partes)


# --------------------------------------------------------------------- I/O Drive
def abrir_servico():
    """Cria o cliente da Drive API a partir da chave da conta de serviço."""
    import json

    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    raw = settings.GOOGLE_SERVICE_ACCOUNT_JSON
    if not raw:
        raise RuntimeError(
            "GOOGLE_SERVICE_ACCOUNT_JSON não configurado (chave JSON da conta de serviço)."
        )
    info = json.loads(raw)
    cred = service_account.Credentials.from_service_account_info(info, scopes=_SCOPES)
    return build("drive", "v3", credentials=cred, cache_discovery=False)


def _listar_filhos(servico, folder_id: str):
    campos = "nextPageToken, files(id, name, mimeType, md5Checksum, modifiedTime, appProperties)"
    q = f"'{folder_id}' in parents and trashed = false"
    token = None
    while True:
        resp = (
            servico.files()
            .list(
                q=q,
                fields=campos,
                pageToken=token,
                pageSize=1000,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        yield from resp.get("files", [])
        token = resp.get("nextPageToken")
        if not token:
            break


def percorrer(servico, folder_id: str, caminho: tuple[str, ...] = ()):
    """Gera (arquivo, caminho, pasta_id) para cada arquivo (não-pasta) da árvore.

    `caminho` são os nomes das pastas do folder-raiz até o arquivo (exclusive a
    raiz); `pasta_id` é o id da pasta onde o arquivo está (para gravar o [OCR]).
    """
    for item in _listar_filhos(servico, folder_id):
        if item.get("mimeType") == _MIME_PASTA:
            yield from percorrer(servico, item["id"], caminho + (item["name"],))
        else:
            yield item, caminho, folder_id


def baixar_bytes(servico, arquivo: dict) -> bytes:
    """Baixa o conteúdo do arquivo (Google Docs são exportados como texto)."""
    from googleapiclient.http import MediaIoBaseDownload

    file_id = arquivo["id"]
    if arquivo.get("mimeType") == _MIME_GDOC:
        req = servico.files().export_media(fileId=file_id, mimeType="text/plain")
    else:
        req = servico.files().get_media(fileId=file_id, supportsAllDrives=True)
    buf = io.BytesIO()
    baixador = MediaIoBaseDownload(buf, req)
    concluido = False
    while not concluido:
        _, concluido = baixador.next_chunk()
    return buf.getvalue()


# ------------------------------------------------------------- artefatos [OCR]
def achar_artefato_ocr(servico, origem_id: str) -> dict | None:
    """Localiza o .txt de OCR associado a um PDF de origem (por appProperties)."""
    q = f"trashed = false and appProperties has {{ key='{_PROP_ORIGEM}' and value='{origem_id}' }}"
    resp = (
        servico.files()
        .list(
            q=q,
            fields="files(id, name, appProperties)",
            spaces="drive",
            pageSize=1,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
    )
    arquivos = resp.get("files", [])
    return arquivos[0] if arquivos else None


def ler_texto_ocr(servico, file_id: str) -> str:
    """Lê o conteúdo de um artefato [OCR] (arquivo texto no Drive)."""
    return baixar_bytes(servico, {"id": file_id, "mimeType": "text/plain"}).decode(
        "utf-8", errors="ignore"
    )


def gravar_artefato_ocr(
    servico,
    *,
    nome_pdf: str,
    pasta_id: str,
    texto: str,
    origem_id: str,
    origem_md5: str,
    existente_id: str | None = None,
) -> str:
    """Cria/atualiza o artefato ``<nome> [OCR].txt`` no Drive e retorna o id."""
    from googleapiclient.http import MediaInMemoryUpload

    stem = nome_pdf.rsplit(".", 1)[0]
    media = MediaInMemoryUpload(texto.encode("utf-8"), mimetype="text/plain", resumable=False)
    props = {_PROP_ORIGEM: origem_id, _PROP_MD5: origem_md5}
    if existente_id:
        servico.files().update(
            fileId=existente_id,
            media_body=media,
            body={"appProperties": props},
            supportsAllDrives=True,
        ).execute()
        return existente_id
    corpo = {
        "name": stem + _SUFIXO_OCR,
        "parents": [pasta_id],
        "mimeType": "text/plain",
        "appProperties": props,
    }
    novo = (
        servico.files()
        .create(body=corpo, media_body=media, fields="id", supportsAllDrives=True)
        .execute()
    )
    return novo["id"]
