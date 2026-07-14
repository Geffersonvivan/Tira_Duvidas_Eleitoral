"""Ingestão do RAG a partir do Google Drive (fonte viva).

A pasta-raiz "RAG" no Drive é compartilhada (leitura) com uma conta de serviço.
Estrutura esperada: ``RAG/<Assunto>/<Natureza>/arquivos`` — o 1º nível vira o
`assunto` (settings.RAG_DRIVE_ASSUNTO_MAP) e o 2º define a natureza
(doutrina/curso → contexto, não citável; norma/jurisprudência → citável).

Reexecutar é **incremental** (usa o md5/revisão do Drive: só re-embeda o que
mudou, poupando a cota Voyage) e **reconcilia** remoções (arquivo apagado no
Drive sai do RAG) — exceto quando restrito a uma pasta com ``--pasta``.

Uso:
    python manage.py ingerir_drive [--pasta "Contábil"] [--dry-run] [--force]
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from rag import drive, ingest
from rag.models import TIPOS_CITAVEIS, Assunto, Documento


class Command(BaseCommand):
    help = "Ingere o RAG a partir da pasta do Google Drive (incremental, fonte viva)."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--pasta",
            default="",
            help="Restringe a uma pasta-raiz (assunto), ex.: --pasta 'Contábil'.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Só lista o que faria (não baixa nem gera embeddings).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-embeda tudo, mesmo o que não mudou (ignora o md5).",
        )

    def handle(self, *args, **opts) -> None:
        folder_id = settings.RAG_DRIVE_ROOT_FOLDER_ID
        if not folder_id:
            raise CommandError("RAG_DRIVE_ROOT_FOLDER_ID não configurado.")
        mapa = settings.RAG_DRIVE_ASSUNTO_MAP
        pasta = opts["pasta"].strip()
        dry = opts["dry_run"]
        force = opts["force"]

        try:
            servico = drive.abrir_servico()
        except Exception as exc:  # credencial ausente/ inválida
            raise CommandError(str(exc)) from exc

        ingeridos = pulados = ignorados = vazios = 0
        ids_vistos: list[str] = []

        for arquivo, caminho in drive.percorrer(servico, folder_id):
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
            marca = "citável" if tipo in TIPOS_CITAVEIS else "contexto"

            # Incremental: md5 do Drive (Google Docs não têm md5 → usa modifiedTime).
            token = arquivo.get("md5Checksum") or arquivo.get("modifiedTime", "")
            anterior = Documento.objects.filter(origem="drive", origem_id=arquivo["id"]).first()
            inalterado = (
                anterior is not None
                and anterior.conteudo_hash == token
                and anterior.trechos.exists()
            )

            if dry:
                acao = "= sem mudança" if (inalterado and not force) else "↑ (re)ingeriria"
                self.stdout.write(f"  {acao} [{assunto}/{tipo}·{marca}] {titulo}")
                continue

            if inalterado and not force:
                pulados += 1
                self.stdout.write(f"  = {titulo} — sem mudança")
                continue

            dados = drive.baixar_bytes(servico, arquivo)
            texto = drive.extrair_texto(arquivo, dados)
            if not texto.strip():
                vazios += 1
                self.stderr.write(f"  ! sem texto extraível: {titulo}")
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
                },
            )
            doc.trechos.all().delete()  # re-ingestão limpa
            trechos = ingest.ingerir(doc, texto)
            ingeridos += 1
            self.stdout.write(f"  ✓ {titulo} [{assunto}/{tipo}·{marca}] — {len(trechos)} trechos")

        # Reconciliação: remove do RAG o que sumiu do Drive (só em varredura completa).
        removidos = 0
        if not dry and not pasta:
            orfaos = Documento.objects.filter(origem="drive").exclude(origem_id__in=ids_vistos)
            removidos = orfaos.count()
            orfaos.delete()

        resumo = (
            f"Concluído: {ingeridos} (re)ingeridos, {pulados} sem mudança, "
            f"{vazios} sem texto, {ignorados} ignorados, {removidos} removidos."
        )
        self.stdout.write(self.style.SUCCESS(resumo) if not dry else resumo)
