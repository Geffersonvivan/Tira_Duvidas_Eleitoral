"""Configuração de testes (pytest).

Os testes cobrem o comportamento público das APIs, independente de um `.env`
local com chaves do Clerk. Este fixture garante `CLERK_ENABLED=False` em todos
os testes, tornando-os determinísticos onde quer que rodem.
"""

import pytest


@pytest.fixture(autouse=True)
def _clerk_desligado(settings):
    settings.CLERK_ENABLED = False
