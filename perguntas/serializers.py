from rest_framework import serializers

from rag.models import Documento


class PerguntaInputSerializer(serializers.Serializer):
    pergunta = serializers.CharField(max_length=2000, trim_whitespace=True)


class FonteSerializer(serializers.ModelSerializer):
    """Só expõe fontes citáveis (norma/jurisprudência) — nunca doutrina/curso."""

    class Meta:
        model = Documento
        fields = ["id", "titulo", "tipo", "vigente"]
