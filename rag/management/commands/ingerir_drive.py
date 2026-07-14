"""Ingestão do RAG a partir do Google Drive (fonte viva), com OCR + cache.

Estrutura no Drive: ``RAG/<Assunto>/<Natureza>/arquivos`` — o 1º nível vira o
`assunto` (settings.RAG_DRIVE_ASSUNTO_MAP) e o 2º a natureza (doutrina/curso →
contexto, não citável).

PDFs escaneados passam por **OCR** (tesseract). O texto extraído é guardado em
`Documento.texto_extraido`: enquanto o md5 do arquivo não mudar, a reindexação
usa esse cache e **não re-OCRa nem re-baixa** — o livro é "lido" uma vez só.

Incremental pelo md5/revisão do Drive (checado antes de baixar); reconcilia
remoções (varredura completa). O OCR roda onde houver tesseract+poppler; no
Railway os pacotes vêm do nixpacks.toml.

Uso:
    python manage.py ingerir_drive [--pasta "Contábil"] [--dry-run] [--force]
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from rag import drive, ingest
from rag.models import TIPOS_CITAVEIS, Assunto, Documento


class Command(BaseCommand):
    help = "Ingere o RAG do Google Drive (OCR + cache do texto; incremental)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--pasta", default="", help="Restringe a uma pasta-raiz (assunto).")
        parser.add_argument(
            "--dry-run", action="store_true", help="Só lista o que faria (sem baixar/OCR/embed)."
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Reindexa mesmo sem mudança (usa o cache de texto).",
        )

    def handle(self, *args, **opts) -> None:
        folder_id = settings.RAG_DRIVE_ROOT_FOLDER_ID
        if not folder_id:
            raise CommandError("RAG_DRIVE_ROOT_FOLDER_ID não configurado.")
        mapa = settings.RAG_DRIVE_ASSUNTO_MAP
        pasta, dry, force = opts["pasta"].strip(), opts["dry_run"], opts["force"]

        try:
            servico = drive.abrir_servico()
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        ingeridos = pulados = ignorados = vazios = ocr_feitos = sem_ocr = 0
        ids_vistos: list[str] = []

        for arquivo, caminho in drive.percorrer(servico, folder_id):
            if pasta and (not caminho or caminho[0] != pasta):
                continue
            assunto, tipo, subtema = drive.classificar(caminho, mapa)
            nome = arquivo.get("name", "")
            titulo = nome.rsplit(".", 1)[0].strip() or nome
            if assunto not in Assunto.values:
                ignorados += 1
                self.stderr.write(f"  ? ignorado (fora do mapa): {'/'.join(caminho)}/{nome}")
                continue

            ids_vistos.append(arquivo["id"])
            token = arquivo.get("md5Checksum") or arquivo.get("modifiedTime", "")
            eh_pdf = (arquivo.get("mimeType") == "application/pdf") or nome.lower().endswith(".pdf")

            anterior = Documento.objects.filter(origem="drive", origem_id=arquivo["id"]).first()
            mesmo = anterior is not None and anterior.conteudo_hash == token

            if dry:
                if mesmo and anterior.trechos.exists() and not force:
                    plano = "sem mudança"
                elif mesmo and anterior.texto_extraido:
                    plano = "reindexa do cache (sem OCR)"
                else:
                    plano = "baixa + OCR/extrai"
                self.stdout.write(f"  · [{assunto}/{tipo}] {titulo} — {plano}")
                continue

            # Nada mudou e já está indexado → pula sem baixar.
            if mesmo and anterior.trechos.exists() and not force:
                pulados += 1
                self.stdout.write(f"  = {titulo} — sem mudança")
                continue

            # Obtém o texto: cache (md5 igual) → nativo → OCR.
            if mesmo and anterior.texto_extraido:
                texto = anterior.texto_extraido  # nunca re-OCRa
            else:
                dados = drive.baixar_bytes(servico, arquivo)
                if not eh_pdf:
                    texto = drive.extrair_texto(arquivo, dados)
                else:
                    texto = drive.texto_de_pdf(dados)
                    if not texto.strip():  # escaneado → OCR
                        if not drive.ocr_disponivel():
                            sem_ocr += 1
                            self.stderr.write(f"  ! scan sem OCR disponível: {titulo}")
                            continue

                        def _prog(feito, total, _t=titulo):
                            self.stdout.write(
                                f"    … OCR {_t[:38]}: {feito}/{total} págs", ending="\r"
                            )

                        # OCR longo não deve segurar a conexão ociosa; fecha aqui
                        # e o próximo acesso ao banco reconecta (keepalives cobrem
                        # a fase de embedding). Evita "connection dropped" pós-OCR.
                        connection.close()
                        texto = drive.ocr_pdf(dados, progresso=_prog)
                        self.stdout.write("")
                        ocr_feitos += 1

            if not texto.strip():
                vazios += 1
                self.stderr.write(f"  ! sem texto: {titulo}")
                continue

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
                    "texto_extraido": texto,
                },
            )
            doc.trechos.all().delete()
            trechos = ingest.ingerir(doc, texto)
            ingeridos += 1
            marca = "citável" if tipo in TIPOS_CITAVEIS else "contexto"
            self.stdout.write(f"  ✓ {titulo} [{assunto}/{tipo}·{marca}] — {len(trechos)} trechos")

        # Reconciliação: remove do RAG o que sumiu do Drive (só varredura completa).
        removidos = 0
        if not dry and not pasta:
            orfaos = Documento.objects.filter(origem="drive").exclude(origem_id__in=ids_vistos)
            removidos = orfaos.count()
            orfaos.delete()

        resumo = (
            f"Concluído: {ingeridos} (re)ingeridos, {pulados} sem mudança, {ocr_feitos} OCR, "
            f"{vazios} sem texto, {sem_ocr} scans sem OCR, {ignorados} ignorados, "
            f"{removidos} removidos."
        )
        self.stdout.write(self.style.SUCCESS(resumo) if not dry else resumo)
