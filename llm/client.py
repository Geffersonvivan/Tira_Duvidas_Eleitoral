"""Wrapper do SDK Anthropic (Claude).

Encapsula a chamada `messages.create`, seguindo a skill claude-api:
- thinking adaptativo apenas em modelos 4.6+ (Haiku 4.5 não suporta);
- system com prompt caching (prefixo estável derivado da lógica);
- guarda do stop_reason "refusal" antes de ler o conteúdo.

Não registra consumo aqui — quem chama usa `llm.budget.registrar_uso`, mantendo
a separação entre I/O da API e persistência.
"""

from dataclasses import dataclass

from anthropic import Anthropic

from llm.config import suporta_thinking

_cliente: Anthropic | None = None


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

    resp = _get_cliente().messages.create(**kwargs)

    # Guarda: em refusal o conteúdo pode vir vazio (skill claude-api).
    texto = "" if resp.stop_reason == "refusal" else _extrair_texto(resp.content)
    return Resposta(
        texto=texto,
        modelo=modelo,
        tokens_entrada=resp.usage.input_tokens,
        tokens_saida=resp.usage.output_tokens,
        stop_reason=resp.stop_reason,
    )
