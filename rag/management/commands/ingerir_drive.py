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
        parser.add_argument(
            "--so-vazios",
            action="store_true",
            help="Só reprocessa docs já existentes que ficaram com 0 trechos "
            "(reembeda do cache, sem re-baixar/OCR). Ideal p/ retomar após falha de cota.",
        )

    def _upsert_doc(
        self,
        arquivo,
        titulo,
        tipo,
        assunto,
        subtema,
        token,
        texto,
        *,
        ocr_paginas=0,
        ocr_completo=True,
    ) -> Documento:
        """Upsert idempotente do Documento do Drive (metadados + estado do texto/OCR)."""
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
                "ocr_paginas": ocr_paginas,
                "ocr_completo": ocr_completo,
            },
        )
        return doc

    def handle(self, *args, **opts) -> None:
        folder_id = settings.RAG_DRIVE_ROOT_FOLDER_ID
        if not folder_id:
            raise CommandError("RAG_DRIVE_ROOT_FOLDER_ID não configurado.")
        mapa = settings.RAG_DRIVE_ASSUNTO_MAP
        pasta, dry, force = opts["pasta"].strip(), opts["dry_run"], opts["force"]
        so_vazios = opts["so_vazios"]

        try:
            servico = drive.abrir_servico()
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        ingeridos = pulados = ignorados = vazios = ocr_feitos = sem_ocr = falhas = 0
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

            # --so-vazios: só age nos docs já registrados que ficaram com 0 trechos
            # (não toca no que já está indexado nem no que nunca foi ingerido).
            if so_vazios and (anterior is None or anterior.trechos.exists()):
                continue

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

            # Obtém o texto: cache OCR completo → nativo → OCR (retomável).
            if mesmo and anterior.ocr_completo and anterior.texto_extraido:
                texto = anterior.texto_extraido  # cache completo: nunca re-OCRa
                doc = self._upsert_doc(arquivo, titulo, tipo, assunto, subtema, token, texto)
            else:
                dados = drive.baixar_bytes(servico, arquivo)
                if not eh_pdf:
                    texto = drive.extrair_texto(arquivo, dados)
                    if not texto.strip():
                        vazios += 1
                        self.stderr.write(f"  ! sem texto: {titulo}")
                        continue
                    doc = self._upsert_doc(arquivo, titulo, tipo, assunto, subtema, token, texto)
                else:
                    texto = drive.texto_de_pdf(dados)
                    if texto.strip():  # PDF com camada de texto nativa
                        doc = self._upsert_doc(
                            arquivo, titulo, tipo, assunto, subtema, token, texto
                        )
                    else:  # escaneado → OCR retomável
                        if not drive.ocr_disponivel():
                            sem_ocr += 1
                            self.stderr.write(f"  ! scan sem OCR disponível: {titulo}")
                            continue
                        # Retoma o OCR de onde parou, se houver parcial do mesmo arquivo.
                        if mesmo and not anterior.ocr_completo and anterior.ocr_paginas:
                            ini_pag, texto_ini = anterior.ocr_paginas, anterior.texto_extraido
                            self.stdout.write(f"  ↻ retoma OCR de {titulo} na pág {ini_pag}")
                        else:
                            ini_pag, texto_ini = 0, ""
                        doc = self._upsert_doc(
                            arquivo,
                            titulo,
                            tipo,
                            assunto,
                            subtema,
                            token,
                            texto_ini,
                            ocr_paginas=ini_pag,
                            ocr_completo=False,
                        )

                        def _prog(feito, total, _t=titulo):
                            self.stdout.write(
                                f"    … OCR {_t[:38]}: {feito}/{total} págs", ending="\r"
                            )

                        def _salvar(t, n, _d=doc):  # persiste o parcial a cada lote
                            _d.texto_extraido, _d.ocr_paginas = t, n
                            _d.save(update_fields=["texto_extraido", "ocr_paginas"])

                        try:
                            texto = drive.ocr_pdf(
                                dados,
                                inicio=ini_pag,
                                texto_inicial=texto_ini,
                                ao_lote=_salvar,
                                progresso=_prog,
                            )
                        except Exception as exc:
                            # Erro de OCR (página corrompida, etc.): o parcial já está
                            # salvo, então o próximo run retoma. Não aborta o lote.
                            falhas += 1
                            self.stdout.write("")
                            self.stderr.write(
                                f"  ✗ OCR interrompido em {titulo}: {exc} — "
                                "parcial salvo (retomável)"
                            )
                            continue
                        doc.texto_extraido, doc.ocr_completo = texto, True
                        doc.save(update_fields=["texto_extraido", "ocr_completo"])
                        self.stdout.write("")
                        ocr_feitos += 1

            if not texto.strip():
                vazios += 1
                self.stderr.write(f"  ! sem texto: {titulo}")
                continue

            doc.trechos.all().delete()
            try:
                trechos = ingest.ingerir(doc, texto)
            except Exception as exc:
                # Falha no embedding (ex.: cota da Voyage esgotada) não deve abortar
                # o lote inteiro. O texto já está em cache (texto_extraido), então o
                # doc fica com 0 trechos e pode ser retomado com --so-vazios.
                falhas += 1
                self.stderr.write(self.style.ERROR(f"  ✗ {titulo} — FALHA no embedding: {exc}"))
                continue

            if not trechos:  # 0 trechos: alerta explícito (não passa mais batido)
                vazios += 1
                self.stderr.write(self.style.WARNING(f"  ! {titulo} — 0 trechos gerados"))
                continue

            ingeridos += 1
            marca = "citável" if tipo in TIPOS_CITAVEIS else "contexto"
            self.stdout.write(f"  ✓ {titulo} [{assunto}/{tipo}·{marca}] — {len(trechos)} trechos")

        # Reconciliação: remove do RAG o que sumiu do Drive (só varredura completa;
        # nunca no modo parcial --pasta/--so-vazios, que não vê a árvore toda).
        removidos = 0
        if not dry and not pasta and not so_vazios:
            orfaos = Documento.objects.filter(origem="drive").exclude(origem_id__in=ids_vistos)
            removidos = orfaos.count()
            orfaos.delete()

        resumo = (
            f"Concluído: {ingeridos} (re)ingeridos, {pulados} sem mudança, {ocr_feitos} OCR, "
            f"{vazios} vazios, {falhas} falhas de embedding, {sem_ocr} scans sem OCR, "
            f"{ignorados} ignorados, {removidos} removidos."
        )
        self.stdout.write(self.style.SUCCESS(resumo) if not dry else resumo)

        # Varredura de saúde: docs do Drive que ficaram SEM trechos (invisíveis à
        # busca). É o alerta que faltava — Ficha Limpa/Financiamento passaram batido.
        if not dry:
            from django.db.models import Count

            vazios_db = list(
                Documento.objects.filter(origem="drive")
                .annotate(_n=Count("trechos"))
                .filter(_n=0)
                .order_by("assunto", "titulo")
            )
            if vazios_db:
                self.stderr.write(
                    self.style.ERROR(f"\n⚠ {len(vazios_db)} doc(s) do Drive com 0 trechos:")
                )
                for d in vazios_db:
                    self.stderr.write(f"  ✗ {d.titulo} [{d.assunto}/{d.tipo}]")
                self.stderr.write("  → retome com: python manage.py ingerir_drive --so-vazios")
