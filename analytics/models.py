"""Registro e ranqueamento das perguntas feitas na plataforma.

Duas tabelas:
- GrupoDuvida: o cluster ranqueável (uma dúvida canônica por assunto), com a
  contagem de quantas vezes foi perguntada — igual (exata) ou de sentido próximo.
- PerguntaRegistrada: o log bruto de toda pergunta, para auditoria e futura
  re-clusterização.

O agrupamento é sempre feito DENTRO de um assunto (direito/contabilidade/
impulsionamento) — ver analytics.services.
"""

from django.db import models
from pgvector.django import VectorField

from rag.models import EMBEDDING_DIM, Assunto


class GrupoDuvida(models.Model):
    """Cluster de perguntas equivalentes, dentro de um assunto."""

    assunto = models.CharField(max_length=20, choices=Assunto.choices, db_index=True)
    pergunta_canonica = models.TextField(help_text="Pergunta representante do grupo.")
    texto_normalizado = models.TextField(help_text="Chave do match exato (normalizada).")
    embedding = VectorField(dimensions=EMBEDDING_DIM, null=True, blank=True)

    frequencia = models.PositiveIntegerField(default=1, help_text="Total de ocorrências.")
    ocorrencias_exatas = models.PositiveIntegerField(default=0, help_text="Perguntas idênticas.")
    variacoes = models.PositiveIntegerField(default=0, help_text="Entradas por sentido próximo.")

    primeira_ocorrencia = models.DateTimeField(auto_now_add=True)
    ultima_ocorrencia = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-frequencia"]
        verbose_name = "Grupo de dúvida"
        verbose_name_plural = "Grupos de dúvida"
        indexes = [models.Index(fields=["assunto", "texto_normalizado"])]

    def __str__(self) -> str:
        return f"[{self.assunto}] ({self.frequencia}) {self.pergunta_canonica[:60]}"


class PerguntaRegistrada(models.Model):
    """Log bruto de toda pergunta feita (dado sensível — acesso restrito)."""

    texto = models.TextField()
    texto_normalizado = models.TextField()
    embedding = VectorField(dimensions=EMBEDDING_DIM, null=True, blank=True)
    assunto = models.CharField(max_length=20, choices=Assunto.choices, blank=True, default="")
    on_topic = models.BooleanField(default=True)
    grupo = models.ForeignKey(
        GrupoDuvida, on_delete=models.SET_NULL, null=True, blank=True, related_name="perguntas"
    )
    criado_em = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "Pergunta registrada"
        verbose_name_plural = "Perguntas registradas"

    def __str__(self) -> str:
        return self.texto[:70]
