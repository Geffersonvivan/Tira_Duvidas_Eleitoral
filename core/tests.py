"""Smoke tests — linha de base verde do CI."""

from django.test import Client, RequestFactory

from core.views import home


def test_health_ok() -> None:
    resp = Client().get("/health/")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_home_renderiza() -> None:
    # RequestFactory + view direta evita o bug do test Client no Python 3.14
    # (Context.__copy__); no CI (3.12) o Client também funcionaria.
    resp = home(RequestFactory().get("/"))
    assert resp.status_code == 200
    conteudo = resp.content.decode()
    assert "Tira-Dúvidas Eleitoral - TDE" in conteudo
    assert "Perguntas eleitorais" in conteudo
    assert "Análise de material gráfico" in conteudo
