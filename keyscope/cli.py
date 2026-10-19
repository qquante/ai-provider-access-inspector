from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from . import __version__
from .env import find_secret, load_env_file
from .http import HttpClient
from .providers import PROVIDERS, PROVIDER_BY_SLUG, ProviderSpec, audit_provider, missing_result


STATUS_LABELS = {
    "valid": "VÁLIDA",
    "partial": "VÁLIDA/PARCIAL",
    "invalid": "INVÁLIDA",
    "restricted": "RESTRITA",
    "rate_limited": "LIMITADA",
    "unavailable": "INDISPONÍVEL",
    "missing": "NÃO CONFIGURADA",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="key_audit.py",
        description="Valida chaves de IA usando somente endpoints GET oficiais e resume modelos/saldo disponível.",
    )
    parser.add_argument(
        "--provider",
        nargs="+",
        choices=[provider.slug for provider in PROVIDERS],
        help="Audita apenas os provedores selecionados (padrão: todos).",
    )
    parser.add_argument("--env-file", default=".env", help="Arquivo .env (padrão: .env).")
    parser.add_argument(
        "--models-limit",
        type=int,
        default=20,
        help="Máximo de modelos guardados/exibidos por provedor; 0 inclui todos (padrão: 20).",
    )
    parser.add_argument("--timeout", type=float, default=15.0, help="Timeout por chamada em segundos (padrão: 15).")
    parser.add_argument("--workers", type=int, default=5, help="Chamadas paralelas máximas (padrão: 5).")
    parser.add_argument("--json", action="store_true", help="Imprime o relatório como JSON.")
    parser.add_argument("--output", type=Path, help="Também grava o relatório JSON neste caminho.")
    parser.add_argument("--summary-only", action="store_true", help="Na tabela, não imprime a lista de modelos.")
    parser.add_argument(
        "--strict-missing",
        action="store_true",
        help="Retorna erro se algum provedor selecionado não tiver chave configurada.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _selected_specs(slugs: Iterable[str] | None) -> list[ProviderSpec]:
    if not slugs:
        return list(PROVIDERS)
    return [PROVIDER_BY_SLUG[slug] for slug in dict.fromkeys(slugs)]


def run_audit(
    specs: list[ProviderSpec],
    *,
    timeout: float,
    workers: int,
    model_limit: int,
) -> dict[str, Any]:
    located: list[tuple[int, ProviderSpec, str | None, str | None]] = []
    for index, spec in enumerate(specs):
        key, source = find_secret(spec.aliases)
        located.append((index, spec, key, source))

    results: dict[int, dict[str, Any]] = {}
    configured = [item for item in located if item[2] is not None]
    for index, spec, key, source in located:
        if key is None:
            results[index] = missing_result(spec)

    if configured:
        max_workers = min(max(1, workers), len(configured))
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="key-audit") as executor:
            futures = {
                executor.submit(
                    audit_provider,
                    spec,
                    key,
                    source or spec.aliases[0],
                    HttpClient(timeout=timeout),
                    model_limit,
                ): index
                for index, spec, key, source in configured
                if key is not None
            }
            for future in as_completed(futures):
                index = futures[future]
                try:
                    results[index] = future.result()
                except Exception as exc:  # barreira final: nunca deixa uma chave aparecer em traceback
                    spec = specs[index]
                    results[index] = missing_result(spec)
                    results[index].update(
                        {
                            "configured": True,
                            "status": "unavailable",
                            "error": {
                                "kind": "internal_error",
                                "http_status": None,
                                "message": f"erro interno seguro: {type(exc).__name__}",
                            },
                        }
                    )

    ordered = [results[index] for index in range(len(specs))]
    return {
        "schema_version": 1,
        "tool_version": __version__,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "safety": {
            "mode": "read_only",
            "http_methods": ["GET"],
            "keys_persisted": False,
            "keys_printed": False,
            "paid_inference_requests": False,
        },
        "providers": ordered,
    }


def _balance_summary(balance: dict[str, Any]) -> str:
    if not balance.get("reported"):
        return "não exposto pela API"
    kind = balance.get("kind")
    if kind == "account_balance":
        chunks = []
        for item in balance.get("balances", []):
            chunks.append(f"{item.get('currency', '?')} {item.get('total_balance', '?')}")
        suffix = "disponível" if balance.get("is_available") is True else "indisponível p/ chamadas"
        return f"{', '.join(chunks) or 'sem valores'} ({suffix})"
    if kind == "account_credits":
        return f"USD {balance.get('remaining', '?')} restante (conta)"
    if kind == "api_key_limit":
        remaining = balance.get("remaining")
        if remaining is None:
            return f"limite da chave: ilimitado; uso USD {balance.get('usage', '?')}"
        return f"USD {remaining} restante no limite da chave"
    return str(kind)


def _account_summary(account: dict[str, Any] | None) -> str:
    if not account:
        return "-"
    for key in ("username", "name", "label", "type"):
        value = account.get(key)
        if value:
            return str(value)
    return "identificada"


def _print_table(report: dict[str, Any], *, show_models: bool) -> None:
    rows: list[list[str]] = []
    for result in report["providers"]:
        count = str(result["model_count"])
        if not result.get("model_list_complete") and result["model_count"]:
            count += "+"
        note = _account_summary(result.get("account"))
        if result.get("error"):
            note = result["error"].get("message", note)
        rows.append(
            [
                result["provider_name"],
                STATUS_LABELS.get(result["status"], result["status"]),
                result.get("key_source") or "-",
                count,
                _balance_summary(result["balance"]),
                note,
            ]
        )

    headers = ["Provedor", "Status", "Variável", "Modelos", "Saldo/limite", "Conta/erro"]
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = min(60, max(widths[index], len(cell)))

    def render(row: list[str]) -> str:
        cells = []
        for index, cell in enumerate(row):
            clipped = cell if len(cell) <= widths[index] else cell[: widths[index] - 1] + "…"
            cells.append(clipped.ljust(widths[index]))
        return " | ".join(cells)

    print(render(headers))
    print("-+-".join("-" * width for width in widths))
    for row in rows:
        print(render(row))

    if not show_models:
        return
    for result in report["providers"]:
        if not result["models"]:
            continue
        print(f"\n{result['provider_name']} — modelos retornados:")
        for model in result["models"]:
            details = []
            if model.get("context_length") is not None:
                details.append(f"contexto={model['context_length']}")
            if model.get("max_output_tokens") is not None:
                details.append(f"saída={model['max_output_tokens']}")
            if model.get("type"):
                details.append(f"tipo={model['type']}")
            pricing = model.get("pricing")
            if isinstance(pricing, dict) and pricing:
                compact = ", ".join(f"{key}={value}" for key, value in list(pricing.items())[:4])
                details.append(f"preço_api=({compact})")
            suffix = f" | {'; '.join(details)}" if details else ""
            print(f"  - {model['id']}{suffix}")
        for warning in result.get("warnings", []):
            print(f"    aviso: {warning}")


def _exit_code(report: dict[str, Any], strict_missing: bool) -> int:
    providers = report["providers"]
    if not any(result["configured"] for result in providers):
        return 2
    failing = {"invalid", "restricted", "rate_limited", "unavailable"}
    if any(result["status"] in failing for result in providers):
        return 1
    if strict_missing and any(result["status"] == "missing" for result in providers):
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = _parser()
    args = parser.parse_args(argv)
    if args.models_limit < 0:
        parser.error("--models-limit deve ser 0 ou positivo")
    if args.timeout <= 0:
        parser.error("--timeout deve ser positivo")
    if args.workers <= 0:
        parser.error("--workers deve ser positivo")

    try:
        load_env_file(Path(args.env_file))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    specs = _selected_specs(args.provider)
    report = run_audit(
        specs,
        timeout=args.timeout,
        workers=args.workers,
        model_limit=args.models_limit,
    )
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")

    if args.json:
        print(serialized)
    else:
        _print_table(report, show_models=not args.summary_only)
        if args.output:
            print(f"\nRelatório JSON: {args.output.resolve()}")
        if _exit_code(report, args.strict_missing) == 2:
            print("\nNenhuma chave configurada. Copie .env.example para .env e preencha as chaves disponíveis.")

    return _exit_code(report, args.strict_missing)
