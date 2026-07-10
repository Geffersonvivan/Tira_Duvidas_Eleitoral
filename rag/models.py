"""Modelos do RAG eleitoral.

Materializa a **regra de citação inviolável** (lógica.md §1, §4, §7): apenas
norma válida e jurisprudência válida são citáveis. Doutrina, cursos e anexos
entram como contexto para redigir, mas nunca como fonte.
"""

from django.core.exceptions import ValidationError
from django.db import models
from pgvector.django import VectorField

# Dimensão do embedding. Provider sugerido: Voyage AI (recomendado p/ Claude).
# Alterar a dimensão exige migração. Ver ARQUITETURA.md §7.
EMBEDDING_DIM = 1024


class Assunto(models.TextChoices):
    DIREITO = "direito", "Direito eleitoral"
    CONTABILIDADE = "contabilidade", "Contabilidade eleitoral"
    IMPULSIONAMENTO = "impulsionamento", "Impulsionamento eleitoral"


class TipoFonte(models.TextChoices):
    NORMA = "norma", "Norma (lei/resolução)"
    JURISPRUDENCIA = "jurisprudencia", "Jurisprudência (TSE/TREs)"
    DOUTRINA = "doutrina", "Doutrina"
    CURSO = "curso", "Curso/apostila"
    ANEXO = "anexo", "Anexo interno"


#: Só estes tipos podem ser citados como fonte (lógica.md §1).
TIPOS_CITAVEIS = frozenset({TipoFonte.NORMA, TipoFonte.JURISPRUDENCIA})


class DocumentoQuerySet(models.QuerySet):
    def citaveis(self) -> "DocumentoQuerySet":
        """Documentos que podem ser citados: tipo citável, válido e vigente."""
        return self.filter(tipo__in=TIPOS_CITAVEIS, citavel=True, vigente=True)


class Documento(models.Model):
    """Uma fonte do RAG (lei, resolução, acórdão, apostila...)."""

    titulo = models.CharField("título/identificação", max_length=300)
    tipo = models.CharField(max_length=20, choices=TipoFonte.choices)
    assunto = models.CharField(max_length=20, choices=Assunto.choices)

    #: Derivado do tipo; nunca True para doutrina/curso/anexo (ver clean/save).
    citavel = models.BooleanField("citável como fonte?", default=False)
    vigente = models.BooleanField("vigente/válido?", default=True)
    vigencia_inicio = models.DateField(null=True, blank=True)
    vigencia_fim = models.DateField(null=True, blank=True)

    fonte_url = models.URLField(blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    objects = DocumentoQuerySet.as_manager()

    class Meta:
        ordering = ["titulo"]

    def __str__(self) -> str:
        return self.titulo

    def save(self, *args, **kwargs) -> None:
        # Reforça a regra mesmo se save() for chamado sem full_clean():
        # tipo não-citável nunca persiste como citável.
        if self.tipo not in TIPOS_CITAVEIS:
            self.citavel = False
        super().save(*args, **kwargs)

    def clean(self) -> None:
        # Trava: doutrina/curso/anexo jamais podem ser marcados como citáveis.
        if self.citavel and self.tipo not in TIPOS_CITAVEIS:
            raise ValidationError(
                {"citavel": "Apenas norma e jurisprudência válidas podem ser citadas como fonte."}
            )

    @property
    def pode_citar(self) -> bool:
        """Regra inviolável: citável só se tipo permitido, marcado e vigente."""
        return self.tipo in TIPOS_CITAVEIS and self.citavel and self.vigente


class Trecho(models.Model):
    """Chunk de texto de um Documento, com embedding para busca semântica."""

    documento = models.ForeignKey(Documento, on_delete=models.CASCADE, related_name="trechos")
    ordem = models.PositiveIntegerField(default=0)
    conteudo = models.TextField()
    embedding = VectorField(dimensions=EMBEDDING_DIM, null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["documento", "ordem"]

    def __str__(self) -> str:
        return f"{self.documento.titulo} · trecho {self.ordem}"
