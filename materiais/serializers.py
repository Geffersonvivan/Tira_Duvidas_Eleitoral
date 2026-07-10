from rest_framework import serializers

from materiais.services import FORMATOS_ACEITOS, extensao_valida
from rag.models import Documento


class AnaliseInputSerializer(serializers.Serializer):
    arquivos = serializers.ListField(
        child=serializers.FileField(),
        allow_empty=False,
        max_length=20,
    )

    def validate_arquivos(self, arquivos):
        for f in arquivos:
            if not extensao_valida(f.name):
                aceitos = ", ".join(sorted(FORMATOS_ACEITOS))
                raise serializers.ValidationError(
                    f"Formato não aceito em '{f.name}'. Aceitos: {aceitos}."
                )
        return arquivos


class FonteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Documento
        fields = ["id", "titulo", "tipo", "vigente"]
