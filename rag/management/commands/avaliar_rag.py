"""Avalia a qualidade da recuperação do RAG contra o golden set (recall@k).

Requer Postgres/pgvector e o corpus ingerido. Para cada caso de `rag.golden`,
gera o embedding da pergunta, recupera top-k e mede o recall das fontes
esperadas. Imprime o recall médio e falha (exit != 0) se ficar abaixo do mínimo
— assim dá para plugar num passo de CI/agendamento e barrar regressões.

Uso:
    python manage.py avaliar_rag            # k=8, mínimo 0.8
    python manage.py avaliar_rag --k 5 --min-recall 0.9
"""

from django.core.management.base import BaseCommand, CommandError

from rag import embeddings
from rag.golden import CASOS, recall_do_caso
from rag.retriever import buscar


class Command(BaseCommand):
    help = "Mede recall@k da recuperação do RAG contra o golden set (rag/golden.py)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--k", type=int, default=8, help="Top-k da recuperação.")
        parser.add_argument(
            "--min-recall",
            type=float,
            default=0.8,
            help="Recall médio mínimo aceitável (senão o comando falha).",
        )

    def handle(self, *args, **opts) -> None:
        if not CASOS:
            raise CommandError("Golden set vazio — popule rag/golden.py:CASOS.")

        k, minimo = opts["k"], opts["min_recall"]
        total = 0.0
        for caso in CASOS:
            vetor = embeddings.gerar_embedding(caso["pergunta"])
            rec = buscar(vetor, assunto=caso.get("assunto"), k=k)
            titulos = [t.documento.titulo for t in rec.contexto]
            r = recall_do_caso(titulos, caso["fontes_esperadas"])
            total += r
            marca = self.style.SUCCESS("ok") if r >= 1.0 else self.style.WARNING(f"{r:.0%}")
            self.stdout.write(f"[{marca}] {caso['pergunta'][:70]}")

        medio = total / len(CASOS)
        linha = f"Recall@{k} médio: {medio:.1%} ({len(CASOS)} casos; mínimo {minimo:.0%})"
        if medio < minimo:
            raise CommandError(linha + " — ABAIXO do mínimo.")
        self.stdout.write(self.style.SUCCESS(linha))
