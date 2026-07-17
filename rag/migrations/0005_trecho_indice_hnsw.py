"""Índice ANN (HNSW) no embedding dos trechos — busca vetorial deixa de ser
full-scan conforme o corpus cresce.

Só roda no Postgres (SQLite ignora). Defensiva: se a extensão pgvector for antiga
(HNSW exige pgvector >= 0.5), registra aviso e segue — não derruba o deploy.
`atomic = False` para que uma eventual falha do CREATE INDEX não aborte a
transação da migração.
"""

from django.db import migrations

_NOME = "rag_trecho_embedding_hnsw"


def criar_indice(apps, schema_editor) -> None:
    conn = schema_editor.connection
    if conn.vendor != "postgresql":
        return
    try:
        schema_editor.execute(
            f"CREATE INDEX IF NOT EXISTS {_NOME} "
            "ON rag_trecho USING hnsw (embedding vector_cosine_ops)"
        )
    except Exception as e:  # pragma: no cover - depende da versão da extensão
        print(f"[migração 0005] índice HNSW não criado (pgvector < 0.5?): {e}")


def remover_indice(apps, schema_editor) -> None:
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(f"DROP INDEX IF EXISTS {_NOME}")


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("rag", "0004_documento_texto_extraido")]

    operations = [migrations.RunPython(criar_indice, remover_indice)]
