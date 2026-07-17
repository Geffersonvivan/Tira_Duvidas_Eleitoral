"""Wrapper do SDK Anthropic (Claude).

Encapsula a chamada `messages.create`, seguindo a skill claude-api:
- thinking adaptativo apenas em modelos 4.6+ (Haiku 4.5 não suporta);
- system com prompt caching (prefixo estável derivado da lógica);
- guarda do stop_reason "refusal" antes de ler o conteúdo.

Não registra consumo aqui — quem chama usa `llm.budget.registrar_uso`, mantendo
a separação entre I/O da API e persistência.

Resiliência: chamadas transitórias (timeout, rate limit, 5xx, conexão) são
repetidas com backoff; esgotadas as tentativas, ou num erro de API não
transitório, levanta `LLMIndisponivel` (a view converte em 503 amigável).
`BadRequestError` é deixado passar de propósito — o Serviço 2 o trata como
"imagem ilegível" (materiais/services.py).
"""

import logging
import time
from dataclasses import dataclass

from anthropic import (
    Anthropic,
    APIConnectionError,
    APIError,
    APITimeoutError,
    BadRequestError,
    InternalServerError,
    RateLimitError,
)

from llm.config import suporta_thinking

logger = logging.getLogger(__name__)

_cliente: Anthropic | None = None

#: Erros que valem nova tentativa (indisponibilidade momentânea do provedor).
_TRANSIENTES = (APIConnectionError, APITimeoutError, InternalServerError, RateLimitError)
_TENTATIVAS = 3
_BACKOFF_BASE = 1.0  # segundos: 1s, 2s entre as tentativas


class LLMIndisponivel(RuntimeError):
    """Falha ao falar com o provedor LLM (após as tentativas ou erro não tratável)."""


def _executar(descricao: str, fn):
    """Executa `fn` com retry/backoff nos erros transitórios.

    Deixa `BadRequestError` propagar (entrada inválida, ex.: imagem ilegível);
    demais `APIError` viram `LLMIndisponivel` sem retry.
    """
    ultimo: Exception | None = None
    for tentativa in range(_TENTATIVAS):
        try:
            return fn()
        except BadRequestError:
            raise  # 400: quem chama trata (não é indisponibilidade)
        except _TRANSIENTES as e:
            ultimo = e
            logger.warning(
                "LLM %s: tentativa %d/%d falhou: %s", descricao, tentativa + 1, _TENTATIVAS, e
            )
            if tentativa < _TENTATIVAS - 1:
                time.sleep(_BACKOFF_BASE * (2**tentativa))
        except APIError as e:
            raise LLMIndisponivel(f"Falha ao consultar o modelo ({descricao}).") from e
    raise LLMIndisponivel(
        f"Modelo indisponível ({descricao}) após {_TENTATIVAS} tentativas."
    ) from ultimo


def _get_cliente() -> Anthropic:
    global _cliente  # noqa: PLW0603 — singleton preguiçoso do SDK
    if _cliente is None:
        _cliente = Anthropic()  # resolve credenciais do ambiente/perfil
    return _cliente


@dataclass
class Resposta:
    texto: str
    modelo: str
    tokens_entrada: int
    tokens_saida: int
    stop_reason: str | None


def _extrair_texto(blocos) -> str:
    partes = [b.text for b in blocos if getattr(b, "type", None) == "text"]
    return "".join(partes)


def completar(
    modelo: str,
    system: str,
    mensagens: list[dict],
    *,
    max_tokens: int = 16000,
) -> Resposta:
    """Chama o Claude e devolve texto + contagem de tokens."""
    kwargs: dict = {
        "model": modelo,
        "max_tokens": max_tokens,
        # system como bloco cacheável (prefixo estável = regras da lógica).
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "messages": mensagens,
    }
    if suporta_thinking(modelo):
        kwargs["thinking"] = {"type": "adaptive"}

    resp = _executar("completar", lambda: _get_cliente().messages.create(**kwargs))

    # Guarda: em refusal o conteúdo pode vir vazio (skill claude-api).
    texto = "" if resp.stop_reason == "refusal" else _extrair_texto(resp.content)
    return Resposta(
        texto=texto,
        modelo=modelo,
        tokens_entrada=resp.usage.input_tokens,
        tokens_saida=resp.usage.output_tokens,
        stop_reason=resp.stop_reason,
    )


def completar_stream(
    modelo: str,
    system: str,
    mensagens: list[dict],
    *,
    max_tokens: int = 16000,
    uso: dict | None = None,
):
    """Gera a resposta em streaming: yield dos deltas de texto conforme saem.

    Ao término, se `uso` for passado, preenche os tokens/stop_reason para
    contabilização (o gerador não pode retornar valor de forma prática)."""
    kwargs: dict = {
        "model": modelo,
        "max_tokens": max_tokens,
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "messages": mensagens,
    }
    if suporta_thinking(modelo):
        kwargs["thinking"] = {"type": "adaptive"}

    # Sem retry aqui: repetir um stream que já emitiu deltas duplicaria a saída.
    # Uma falha ao abrir/consumir vira LLMIndisponivel; a view mostra erro amigável.
    try:
        with _get_cliente().messages.stream(**kwargs) as stream:
            yield from stream.text_stream
            if uso is not None:
                final = stream.get_final_message()
                uso["entrada"] = final.usage.input_tokens
                uso["saida"] = final.usage.output_tokens
                uso["stop_reason"] = final.stop_reason
    except BadRequestError:
        raise
    except APIError as e:
        raise LLMIndisponivel("Falha no streaming do modelo.") from e
