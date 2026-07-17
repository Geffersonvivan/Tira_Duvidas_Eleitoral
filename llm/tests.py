"""Testes do app llm: roteamento, custo e client (sem chamar a API)."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from llm import budget, client, config
from llm.config import Tarefa
from llm.router import escolher_modelo


# ---------------------------------------------------------------- config/router
def test_modelo_default_por_tarefa(monkeypatch) -> None:
    for var in ("MODEL_CLASSIFY", "MODEL_ANSWER", "MODEL_VISION", "MODEL_COMPLEX"):
        monkeypatch.delenv(var, raising=False)
    assert config.modelo_para(Tarefa.CLASSIFICAR) == "claude-haiku-4-5"
    assert config.modelo_para(Tarefa.RESPONDER) == "claude-sonnet-4-6"
    assert config.modelo_para(Tarefa.COMPLEXO) == "claude-opus-4-8"


def test_env_sobrescreve_modelo(monkeypatch) -> None:
    monkeypatch.setenv("MODEL_ANSWER", "claude-opus-4-8")
    assert config.modelo_para(Tarefa.RESPONDER) == "claude-opus-4-8"


def test_suporta_thinking() -> None:
    assert config.suporta_thinking("claude-sonnet-4-6") is True
    assert config.suporta_thinking("claude-haiku-4-5") is False


def test_router_escala_para_complexo_em_baixa_confianca(monkeypatch) -> None:
    monkeypatch.delenv("MODEL_COMPLEX", raising=False)
    assert escolher_modelo(Tarefa.RESPONDER, baixa_confianca=True) == "claude-opus-4-8"


def test_router_nao_escala_classificacao(monkeypatch) -> None:
    monkeypatch.delenv("MODEL_CLASSIFY", raising=False)
    assert escolher_modelo(Tarefa.CLASSIFICAR, baixa_confianca=True) == "claude-haiku-4-5"


# ---------------------------------------------------------------------- custo
def test_preco_ausente_e_zero(monkeypatch) -> None:
    monkeypatch.delenv("PRECO_modelo-x", raising=False)
    assert config.preco_por_mtok("modelo-x") == (Decimal(0), Decimal(0))


def test_calcular_custo_com_preco(monkeypatch) -> None:
    monkeypatch.setenv("PRECO_modelo-x", "2.00,10.00")
    # 1M tokens de entrada + 1M de saída → 2 + 10 = 12 USD
    custo = budget.calcular_custo("modelo-x", 1_000_000, 1_000_000)
    assert custo == Decimal("12")


# --------------------------------------------------------------------- orçamento
@pytest.mark.django_db
def test_registrar_uso_e_gasto_no_mes(monkeypatch) -> None:
    monkeypatch.setenv("PRECO_modelo-x", "1.00,1.00")
    budget.registrar_uso("modelo-x", "responder", 1_000_000, 0)  # 1 USD
    budget.registrar_uso("modelo-x", "responder", 0, 1_000_000)  # 1 USD
    assert budget.gasto_no_mes() == Decimal("2")


@pytest.mark.django_db
def test_dentro_do_orcamento(monkeypatch) -> None:
    monkeypatch.setenv("PRECO_modelo-x", "1.00,0")
    monkeypatch.setenv("LLM_MONTHLY_BUDGET_USD", "5")
    budget.registrar_uso("modelo-x", "responder", 3_000_000, 0)  # 3 USD
    assert budget.dentro_do_orcamento() is True
    budget.registrar_uso("modelo-x", "responder", 3_000_000, 0)  # +3 = 6 USD
    assert budget.dentro_do_orcamento() is False


@pytest.mark.django_db
def test_sem_teto_sempre_dentro(monkeypatch) -> None:
    monkeypatch.setenv("LLM_MONTHLY_BUDGET_USD", "0")
    assert budget.dentro_do_orcamento() is True


# ----------------------------------------------------------------------- client
def _fake_resposta(stop_reason: str, texto: str):
    blocos = [SimpleNamespace(type="text", text=texto)] if texto else []
    return SimpleNamespace(
        content=blocos,
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=5, output_tokens=3),
    )


def test_completar_extrai_texto_e_tokens(monkeypatch) -> None:
    fake = SimpleNamespace(
        messages=SimpleNamespace(create=lambda **kw: _fake_resposta("end_turn", "resposta ok"))
    )
    monkeypatch.setattr(client, "_get_cliente", lambda: fake)

    r = client.completar("claude-sonnet-4-6", "sys", [{"role": "user", "content": "oi"}])
    assert r.texto == "resposta ok"
    assert (r.tokens_entrada, r.tokens_saida) == (5, 3)
    assert r.stop_reason == "end_turn"


def test_completar_refusal_retorna_texto_vazio(monkeypatch) -> None:
    fake = SimpleNamespace(
        messages=SimpleNamespace(create=lambda **kw: _fake_resposta("refusal", ""))
    )
    monkeypatch.setattr(client, "_get_cliente", lambda: fake)

    r = client.completar("claude-sonnet-4-6", "sys", [{"role": "user", "content": "x"}])
    assert r.texto == ""
    assert r.stop_reason == "refusal"


# ----------------------------------------------------------- resiliência do client
def _fake_com_create(create):
    return SimpleNamespace(messages=SimpleNamespace(create=create))


def test_completar_repete_em_erro_transitorio(monkeypatch) -> None:
    import httpx
    from anthropic import APITimeoutError

    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    chamadas = {"n": 0}

    def create(**kw):
        chamadas["n"] += 1
        if chamadas["n"] < 3:
            raise APITimeoutError(request=req)  # transitório: deve repetir
        return _fake_resposta("end_turn", "ok após retry")

    monkeypatch.setattr(client, "_get_cliente", lambda: _fake_com_create(create))
    monkeypatch.setattr(client.time, "sleep", lambda *_a: None)  # sem esperar de verdade

    r = client.completar("claude-sonnet-4-6", "sys", [{"role": "user", "content": "oi"}])
    assert r.texto == "ok após retry"
    assert chamadas["n"] == 3


def test_completar_esgota_tentativas_levanta_indisponivel(monkeypatch) -> None:
    import httpx
    from anthropic import APITimeoutError

    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")

    def create(**kw):
        raise APITimeoutError(request=req)

    monkeypatch.setattr(client, "_get_cliente", lambda: _fake_com_create(create))
    monkeypatch.setattr(client.time, "sleep", lambda *_a: None)

    with pytest.raises(client.LLMIndisponivel):
        client.completar("claude-sonnet-4-6", "sys", [{"role": "user", "content": "x"}])


def test_completar_badrequest_propaga_sem_retry(monkeypatch) -> None:
    """BadRequestError (imagem ilegível) NÃO vira LLMIndisponivel — Serviço 2 trata."""
    import httpx
    from anthropic import BadRequestError

    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx.Response(400, request=req)
    chamadas = {"n": 0}

    def create(**kw):
        chamadas["n"] += 1
        raise BadRequestError("imagem ilegível", response=resp, body=None)

    monkeypatch.setattr(client, "_get_cliente", lambda: _fake_com_create(create))

    with pytest.raises(BadRequestError):
        client.completar("claude-sonnet-4-6", "sys", [{"role": "user", "content": "x"}])
    assert chamadas["n"] == 1  # sem retry
