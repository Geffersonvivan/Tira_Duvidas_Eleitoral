#!/usr/bin/env python
"""Utilitário de linha de comando do Django."""

import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Django não encontrado. Ative o venv e rode `pip install -e '.[dev]'`."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
