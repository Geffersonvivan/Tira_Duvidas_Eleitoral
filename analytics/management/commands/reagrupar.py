"""Reagrupa dúvidas por intenção (passada offline com Haiku).

Funde grupos de MESMO SENTIDO dentro de cada assunto — o que o embedding do
voyage-3 não pega em paráfrases pesadas. Rode periodicamente:

    python manage.py reagrupar
"""

from django.core.management.base import BaseCommand

from analytics.services import reagrupar_por_intencao
from rag.models import Assunto


class Command(BaseCommand):
    help = "Funde grupos de dúvida de mesmo sentido, por assunto (via Haiku)."

    def handle(self, *args, **opts) -> None:
        total = 0
        for assunto in Assunto.values:
            n = reagrupar_por_intencao(assunto)
            total += n
            self.stdout.write(f"  {assunto}: {n} grupo(s) fundido(s)")
        self.stdout.write(self.style.SUCCESS(f"Concluído: {total} fusão(ões) no total."))
