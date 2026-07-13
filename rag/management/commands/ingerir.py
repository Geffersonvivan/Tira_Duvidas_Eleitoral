"""Ingestão de documentos no RAG a partir de um manifesto JSON.

Uso:
    python manage.py ingerir caminho/para/manifesto.json

Cada item do manifesto descreve um documento (norma/jurisprudência/doutrina...)
com o texto inline (`texto`) ou apontando para um arquivo (`arquivo`, relativo
ao manifesto). Re-executar atualiza o documento e re-indexa os trechos.
"""

import hashlib
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from rag import ingest
from rag.models import TIPOS_CITAVEIS, Assunto, Documento, TipoFonte


class Command(BaseCommand):
    help = "Ingere documentos no RAG a partir de um manifesto JSON (incremental)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("manifesto", help="Caminho para o JSON com a lista de documentos.")
        parser.add_argument(
            "--force",
            action="store_true",
            help="Reembeda todos os docs, mesmo os inalterados (ignora o hash).",
        )

    def handle(self, *args, **opts) -> None:
        caminho = Path(opts["manifesto"])
        if not caminho.exists():
            raise CommandError(f"Manifesto não encontrado: {caminho}")

        try:
            itens = json.loads(caminho.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(f"JSON inválido: {exc}") from exc

        base = caminho.parent
        force = opts.get("force", False)
        total_docs = total_trechos = pulados = 0

        for item in itens:
            titulo = item.get("titulo")
            tipo = item.get("tipo")
            assunto = item.get("assunto")
            if not (titulo and tipo and assunto):
                raise CommandError(f"Item incompleto (titulo/tipo/assunto): {item!r}")
            if tipo not in TipoFonte.values:
                raise CommandError(f"tipo inválido '{tipo}' em '{titulo}'. Use: {TipoFonte.values}")
            if assunto not in Assunto.values:
                raise CommandError(f"assunto inválido '{assunto}' em '{titulo}'.")

            texto = item.get("texto")
            if not texto and item.get("arquivo"):
                texto = (base / item["arquivo"]).read_text(encoding="utf-8")
            if not texto or not texto.strip():
                self.stderr.write(f"pulando '{titulo}' — sem texto")
                continue

            # citável por padrão só para norma/jurisprudência (regra de citação).
            citavel = item.get("citavel", tipo in TIPOS_CITAVEIS)
            conteudo_hash = hashlib.sha256(texto.encode("utf-8")).hexdigest()

            # Incremental: se o texto não mudou e já há trechos, atualiza só os
            # metadados e pula a re-embedding (não gasta cota da Voyage).
            anterior = Documento.objects.filter(titulo=titulo).first()
            inalterado = (
                anterior is not None
                and anterior.conteudo_hash == conteudo_hash
                and anterior.trechos.exists()
            )
            doc, _ = Documento.objects.update_or_create(
                titulo=titulo,
                defaults={
                    "tipo": tipo,
                    "assunto": assunto,
                    "citavel": citavel,
                    "vigente": item.get("vigente", True),
                    "fonte_url": item.get("fonte_url", ""),
                    "conteudo_hash": conteudo_hash,
                },
            )
            if inalterado and not force:
                pulados += 1
                self.stdout.write(f"  = {doc.titulo} — sem mudança ({doc.trechos.count()} trechos)")
                continue

            doc.trechos.all().delete()  # re-ingestão limpa
            trechos = ingest.ingerir(doc, texto)

            total_docs += 1
            total_trechos += len(trechos)
            marca = "citável" if doc.pode_citar else "contexto"
            self.stdout.write(f"  ✓ {doc.titulo} [{marca}] — {len(trechos)} trechos")

        resumo = f"Concluído: {total_docs} (re)ingeridos, {total_trechos} trechos"
        if pulados:
            resumo += f"; {pulados} sem mudança (pulados)"
        self.stdout.write(self.style.SUCCESS(resumo + "."))
