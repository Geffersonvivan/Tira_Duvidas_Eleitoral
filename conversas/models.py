"""Histórico de conversas do chat (Serviço 1), por usuário.

Uma `Conversa` agrupa `Mensagem`s (pergunta do usuário e resposta do assistente).
As mensagens do assistente guardam um snapshot das fontes citadas, para o
histórico exibir a resposta completa mesmo que o corpus mude depois.
"""

from django.conf import settings
from django.db import models


class Conversa(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="conversas"
    )
    titulo = models.CharField(max_length=200, default="Nova conversa")
    arquivada = models.BooleanField(default=False)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-atualizado_em"]
        indexes = [models.Index(fields=["user", "-atualizado_em"])]

    def __str__(self) -> str:
        return self.titulo


class Mensagem(models.Model):
    class Papel(models.TextChoices):
        USUARIO = "user", "Usuário"
        ASSISTENTE = "assistente", "Assistente"

    conversa = models.ForeignKey(Conversa, on_delete=models.CASCADE, related_name="mensagens")
    papel = models.CharField(max_length=12, choices=Papel.choices)
    texto = models.TextField()

    # Metadados da resposta do assistente (vazios para mensagens do usuário).
    assunto = models.CharField(max_length=20, blank=True, default="")
    on_topic = models.BooleanField(default=True)
    disclaimer = models.TextField(blank=True, default="")
    fontes = models.JSONField(default=list, blank=True)  # [{id,titulo,tipo,vigente}]

    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["criado_em"]

    def __str__(self) -> str:
        return f"[{self.papel}] {self.texto[:50]}"
