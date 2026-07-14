"""Cliente do Google Drive para a ingestão do RAG (fonte viva).

Autentica com uma **conta de serviço** (sem login interativo — roda no
servidor), varre a árvore de pastas e baixa/extrai o texto dos arquivos.

A classificação (`classificar`/`inferir_tipo`) é pura e testável, sem tocar na
rede nem depender das libs do Google. Os imports do Google ficam dentro das
funções de I/O, de propósito: importar este módulo não exige as libs.
"""

import io

from django.conf import settings

_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
_MIME_PASTA = "application/vnd.google-apps.folder"
_MIME_GDOC = "application/vnd.google-apps.document"


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


# ------------------------------------------------------------------- extração
def extrair_texto(arquivo: dict, dados: bytes) -> str:
    """Extrai texto do conteúdo baixado, conforme o tipo de arquivo."""
    nome = (arquivo.get("name") or "").lower()
    mime = arquivo.get("mimeType") or ""
    if mime == _MIME_GDOC or nome.endswith((".txt", ".md")):
        return dados.decode("utf-8", errors="ignore")
    if mime == "application/pdf" or nome.endswith(".pdf"):
        from pypdf import PdfReader

        leitor = PdfReader(io.BytesIO(dados))
        return "\n".join((pag.extract_text() or "") for pag in leitor.pages)
    return ""  # formato não suportado (ex.: .docx) — ignora por ora


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
    campos = "nextPageToken, files(id, name, mimeType, md5Checksum, modifiedTime)"
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
    """Gera (arquivo, caminho) para cada arquivo (não-pasta) na árvore.

    `caminho` são os nomes das pastas do folder-raiz até o arquivo (exclusive
    a raiz passada na primeira chamada).
    """
    for item in _listar_filhos(servico, folder_id):
        if item.get("mimeType") == _MIME_PASTA:
            yield from percorrer(servico, item["id"], caminho + (item["name"],))
        else:
            yield item, caminho


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
