from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Mapping


def load_env_file(path: Path) -> None:
    """Carrega um .env simples sem sobrescrever variáveis já definidas."""

    if not path.exists():
        return
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ValueError(f"{path}:{line_number}: linha inválida; esperado NOME=VALOR")
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not name:
            raise ValueError(f"{path}:{line_number}: nome de variável vazio")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(name, value)


def find_secret(aliases: Iterable[str], environ: Mapping[str, str] | None = None) -> tuple[str | None, str | None]:
    source = os.environ if environ is None else environ
    # Windows não diferencia caixa em variáveis; este índice mantém o mesmo
    # comportamento quando os testes rodam em outros sistemas.
    indexed = {key.casefold(): (key, value) for key, value in source.items()}
    for alias in aliases:
        match = indexed.get(alias.casefold())
        if match and match[1].strip():
            return match[1].strip(), match[0]
    return None, None

