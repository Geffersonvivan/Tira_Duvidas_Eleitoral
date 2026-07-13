"""Helpers de persistência das conversas."""

from conversas.models import Conversa, Mensagem


def _titulo(pergunta: str) -> str:
    p = (pergunta or "").strip()
    if not p:
        return "Nova conversa"
    return p[:60].rstrip() + "…" if len(p) > 60 else p


def get_or_create_conversa(user, conversa_id, primeira_pergunta):
    """Retorna (conversa, nova?). Reusa a conversa do usuário se `conversa_id` for
    dele; senão cria uma nova com título derivado da primeira pergunta."""
    if conversa_id:
        existente = Conversa.objects.filter(pk=conversa_id, user=user).first()
        if existente:
            return existente, False
    return Conversa.objects.create(user=user, titulo=_titulo(primeira_pergunta)), True


def salvar_mensagem(conversa, papel, texto, **meta):
    Mensagem.objects.create(conversa=conversa, papel=papel, texto=texto, **meta)
    conversa.save(update_fields=["atualizado_em"])  # sobe a conversa na lista
