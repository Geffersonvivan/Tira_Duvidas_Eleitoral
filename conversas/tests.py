"""Testes do histórico de conversas (Fase 1)."""

import json

import pytest
from rest_framework.test import APIClient

from conversas.models import Conversa, Mensagem


def test_listar_sem_login_retorna_vazio() -> None:
    resp = APIClient().get("/api/conversas/")
    assert resp.status_code == 200
    assert resp.data == []


@pytest.mark.django_db
def test_listar_so_do_proprio_usuario(django_user_model) -> None:
    a = django_user_model.objects.create(username="a")
    b = django_user_model.objects.create(username="b")
    Conversa.objects.create(user=a, titulo="da A")
    Conversa.objects.create(user=b, titulo="da B")
    c = APIClient()
    c.force_login(a)
    resp = c.get("/api/conversas/")
    assert [x["titulo"] for x in resp.data] == ["da A"]


@pytest.mark.django_db
def test_detalhe_renomear_e_apagar(django_user_model) -> None:
    u = django_user_model.objects.create(username="u")
    conv = Conversa.objects.create(user=u, titulo="Antigo")
    Mensagem.objects.create(conversa=conv, papel="user", texto="oi")
    c = APIClient()
    c.force_login(u)

    r = c.get(f"/api/conversas/{conv.pk}/")
    assert r.data["titulo"] == "Antigo"
    assert len(r.data["mensagens"]) == 1

    c.patch(f"/api/conversas/{conv.pk}/", {"titulo": "Novo nome"}, format="json")
    conv.refresh_from_db()
    assert conv.titulo == "Novo nome"

    assert c.delete(f"/api/conversas/{conv.pk}/").status_code == 204
    assert not Conversa.objects.filter(pk=conv.pk).exists()


@pytest.mark.django_db
def test_detalhe_de_outro_usuario_404(django_user_model) -> None:
    a = django_user_model.objects.create(username="a")
    b = django_user_model.objects.create(username="b")
    conv = Conversa.objects.create(user=a)
    c = APIClient()
    c.force_login(b)
    assert c.get(f"/api/conversas/{conv.pk}/").status_code == 404


@pytest.mark.django_db
def test_stream_persiste_pergunta_e_resposta(client, monkeypatch, django_user_model) -> None:
    from perguntas import services

    def fake_stream(_pergunta):
        yield {"tipo": "meta", "on_topic": True, "assunto": "direito"}
        yield {"tipo": "delta", "texto": "Resposta "}
        yield {"tipo": "delta", "texto": "final."}
        yield {"tipo": "fim", "fontes": [], "disclaimer": "aviso"}

    monkeypatch.setattr(services, "responder_pergunta_stream", fake_stream)
    u = django_user_model.objects.create(username="u")
    client.force_login(u)

    resp = client.post(
        "/api/perguntas/stream/",
        data=json.dumps({"pergunta": "Qual o prazo para registro?"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    b"".join(resp.streaming_content)  # consome o stream (dispara a persistência)

    conv = Conversa.objects.get(user=u)
    assert conv.titulo.startswith("Qual o prazo")
    msgs = list(conv.mensagens.all())
    assert [m.papel for m in msgs] == ["user", "assistente"]
    assert msgs[1].texto == "Resposta final."
    assert msgs[1].assunto == "direito"
    assert msgs[1].disclaimer == "aviso"
