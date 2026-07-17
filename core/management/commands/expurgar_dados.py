"""Expurgo de dados por retenção (LGPD).

Apaga, por idade:
- PerguntaRegistrada (log bruto e anônimo) além de LGPD_RETENCAO_PERGUNTAS_DIAS —
  os GrupoDuvida (estatística agregada) são preservados;
- Conversa inativa (sem atualização) além de LGPD_RETENCAO_CONVERSAS_DIAS — as
  Mensagem em cascata.

Prazos vêm do settings (env). 0 = desligado para aquele alvo. Agende via cron/
Railway. Use --dry-run para só contar, sem apagar.
"""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from analytics.models import PerguntaRegistrada
from conversas.models import Conversa


class Command(BaseCommand):
    help = "Apaga dados além do prazo de retenção (LGPD). 0 dias = alvo desligado."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Apenas conta o que seria apagado, sem apagar.",
        )

    def _expurgar(self, qs, dias: int, rotulo: str, campo: str, dry: bool) -> None:
        if dias <= 0:
            self.stdout.write(f"{rotulo}: retenção desligada (0 dias) — nada a fazer.")
            return
        limite = timezone.now() - timedelta(days=dias)
        alvo = qs.filter(**{f"{campo}__lt": limite})
        n = alvo.count()
        if dry:
            self.stdout.write(f"{rotulo}: {n} registro(s) além de {dias} dias (dry-run).")
            return
        apagados, _ = alvo.delete()
        self.stdout.write(self.style.SUCCESS(f"{rotulo}: {apagados} objeto(s) apagado(s)."))

    def handle(self, *args, **opts) -> None:
        dry = opts["dry_run"]
        self._expurgar(
            PerguntaRegistrada.objects.all(),
            settings.LGPD_RETENCAO_PERGUNTAS_DIAS,
            "Perguntas registradas",
            "criado_em",
            dry,
        )
        self._expurgar(
            Conversa.objects.all(),
            settings.LGPD_RETENCAO_CONVERSAS_DIAS,
            "Conversas inativas",
            "atualizado_em",
            dry,
        )
