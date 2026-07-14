"""Ingestão do RAG a partir do Google Drive (fonte viva), com OCR híbrido.

Estrutura no Drive: ``RAG/<Assunto>/<Natureza>/arquivos`` — o 1º nível vira o
`assunto` (settings.RAG_DRIVE_ASSUNTO_MAP) e o 2º a natureza (doutrina/curso →
contexto, não citável).

**OCR híbrido (opção A):** PDFs escaneados passam por OCR **uma vez** e o texto
é gravado de volta no Drive como ``<nome> [OCR].txt``. Nas próximas rodadas a
ingestão lê esse texto e pula o OCR — o livro é "lido" só uma vez na vida.

Fluxo em duas pontas (por causa do banco de prod ser interno e o OCR ser pesado):
  1. OCR — rode onde houver tesseract+poppler (ex.: sua máquina), sem tocar no
     banco:   ``python manage.py ingerir_drive --somente-ocr [--pasta X]``
  2. Ingestão — rode no Railway (lê o texto/[OCR], embeda no pgvector):
     ``railway ssh "/opt/venv/bin/python manage.py ingerir_drive [--pasta X]"``

Incremental pelo md5/revisão do Drive; reconcilia remoções (varredura completa).
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from rag import drive, ingest
from rag.models import TIPOS_CITAVEIS, Assunto, Documento


class Command(BaseCommand):
    help = "Ingere o RAG do Google Drive com OCR híbrido (incremental, fonte viva)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--pasta", default="", help="Restringe a uma pasta-raiz (assunto).")
        parser.add_argument(
            "--somente-ocr",
            action="store_true",
            help="Só faz OCR dos scans e grava o [OCR] no Drive (não embeda; não usa o banco).",
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="Só lista o que faria (sem baixar/OCR/embed)."
        )
        parser.add_argument(
            "--force", action="store_true", help="Refaz OCR/embedding mesmo do que não mudou."
        )

    def handle(self, *args, **opts) -> None:
        folder_id = settings.RAG_DRIVE_ROOT_FOLDER_ID
        if not folder_id:
            raise CommandError("RAG_DRIVE_ROOT_FOLDER_ID não configurado.")
        mapa = settings.RAG_DRIVE_ASSUNTO_MAP
        pasta, somente_ocr = opts["pasta"].strip(), opts["somente_ocr"]
        dry, force = opts["dry_run"], opts["force"]

        try:
            servico = drive.abrir_servico()
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        ingeridos = pulados = ignorados = vazios = ocr_feitos = sem_ocr = 0
        ids_vistos: list[str] = []

        for arquivo, caminho, pasta_id in drive.percorrer(servico, folder_id):
            if drive.eh_artefato_ocr(arquivo):
                continue  # os [OCR].txt são consumidos pelo PDF de origem, não como doc
            if pasta and (not caminho or caminho[0] != pasta):
                continue

            assunto, tipo, subtema = drive.classificar(caminho, mapa)
            nome = arquivo.get("name", "")
            titulo = nome.rsplit(".", 1)[0].strip() or nome
            if assunto not in Assunto.values:
                ignorados += 1
                onde = "/".join(caminho)
                self.stderr.write(f"  ? ignorado (fora do mapa): {onde}/{nome}")
                continue

            ids_vistos.append(arquivo["id"])
            token = arquivo.get("md5Checksum") or arquivo.get("modifiedTime", "")
            eh_pdf = (arquivo.get("mimeType") == "application/pdf") or nome.lower().endswith(".pdf")

            # Artefato [OCR] já pronto para este PDF?
            artefato = drive.achar_artefato_ocr(servico, arquivo["id"]) if eh_pdf else None
            ocr_fresco = bool(
                artefato and (artefato.get("appProperties") or {}).get("ocr_src_md5") == token
            )

            if dry:
                if ocr_fresco:
                    plano = "via [OCR] pronto"
                elif eh_pdf:
                    plano = "baixaria (nativo ou OCR)"
                else:
                    plano = "texto direto"
                self.stdout.write(f"  · [{assunto}/{tipo}] {titulo} — {plano}")
                continue

            # Incremental (ingestão): pula sem baixar nada se o md5 não mudou.
            if not somente_ocr and not force:
                anterior = Documento.objects.filter(origem="drive", origem_id=arquivo["id"]).first()
                if anterior and anterior.conteudo_hash == token and anterior.trechos.exists():
                    pulados += 1
                    self.stdout.write(f"  = {titulo} — sem mudança")
                    continue

            # ---- obtém o texto (preferindo o [OCR] já gravado) ----
            texto = ""
            if ocr_fresco and not force:
                texto = drive.ler_texto_ocr(servico, artefato["id"])
            elif not eh_pdf:
                texto = drive.extrair_texto(arquivo, drive.baixar_bytes(servico, arquivo))
            else:
                dados = drive.baixar_bytes(servico, arquivo)
                texto = drive.texto_de_pdf(dados)
                if not texto.strip():  # PDF escaneado → precisa de OCR
                    if not drive.ocr_disponivel():
                        sem_ocr += 1
                        self.stderr.write(
                            f"  ! scan sem OCR: {titulo} — rode --somente-ocr onde haja tesseract"
                        )
                        continue

                    def _prog(feito, total, _t=titulo):
                        self.stdout.write(f"    … OCR {_t[:40]}: {feito}/{total} págs", ending="\r")

                    texto = drive.ocr_pdf(dados, progresso=_prog)
                    self.stdout.write("")  # quebra a linha do \r
                    drive.gravar_artefato_ocr(
                        servico,
                        nome_pdf=nome,
                        pasta_id=pasta_id,
                        texto=texto,
                        origem_id=arquivo["id"],
                        origem_md5=token,
                        existente_id=artefato["id"] if artefato else None,
                    )
                    ocr_feitos += 1
                    self.stdout.write(f"  ✎ OCR gravado no Drive: {titulo} [OCR].txt")

            if somente_ocr:
                continue  # etapa de OCR não embeda nem toca no banco

            if not texto.strip():
                vazios += 1
                self.stderr.write(f"  ! sem texto: {titulo}")
                continue

            # ---- grava no pgvector ----
            doc, _ = Documento.objects.update_or_create(
                origem="drive",
                origem_id=arquivo["id"],
                defaults={
                    "titulo": titulo,
                    "tipo": tipo,
                    "assunto": assunto,
                    "citavel": tipo in TIPOS_CITAVEIS,
                    "vigente": True,
                    "fonte_url": f"https://drive.google.com/file/d/{arquivo['id']}/view",
                    "conteudo_hash": token,
                    "subtema": subtema,
                },
            )
            doc.trechos.all().delete()
            trechos = ingest.ingerir(doc, texto)
            ingeridos += 1
            marca = "citável" if tipo in TIPOS_CITAVEIS else "contexto"
            self.stdout.write(f"  ✓ {titulo} [{assunto}/{tipo}·{marca}] — {len(trechos)} trechos")

        # Reconciliação: remove do RAG o que sumiu do Drive (só varredura completa e ingestão).
        removidos = 0
        if not dry and not somente_ocr and not pasta:
            orfaos = Documento.objects.filter(origem="drive").exclude(origem_id__in=ids_vistos)
            removidos = orfaos.count()
            orfaos.delete()

        if somente_ocr:
            resumo = f"OCR: {ocr_feitos} gravados no Drive, {sem_ocr} sem OCR possível."
        else:
            resumo = (
                f"Concluído: {ingeridos} (re)ingeridos, {pulados} sem mudança, {ocr_feitos} OCR, "
                f"{vazios} sem texto, {sem_ocr} scans sem OCR, {ignorados} ignorados, "
                f"{removidos} removidos."
            )
        self.stdout.write(self.style.SUCCESS(resumo) if not dry else resumo)
