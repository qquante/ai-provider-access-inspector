from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from .http import ApiError, ApiResponse, HttpClient, rate_limit_headers


@dataclass(frozen=True)
class ProviderSpec:
    slug: str
    name: str
    aliases: tuple[str, ...]
    strategy: str
    models_url: str
    auth_kind: str = "bearer"
    model_list_complete: bool = True
    balance_note: str = "Saldo não exposto pela API oficial para esta credencial."
    docs: tuple[str, ...] = ()


PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        slug="openai",
        name="OpenAI",
        aliases=("OPENAI_API_KEY", "openai_proj", "OPENAI_PROJ"),
        strategy="models",
        models_url="https://api.openai.com/v1/models",
        balance_note="Chave de projeto lista modelos, mas não expõe saldo pré-pago. Custos organizacionais exigem credencial administrativa.",
        docs=(
            "https://developers.openai.com/api/reference/resources/models",
            "https://developers.openai.com/api/reference/resources/admin/subresources/organization/subresources/usage",
        ),
    ),
    ProviderSpec(
        slug="anthropic",
        name="Anthropic",
        aliases=("ANTHROPIC_API_KEY", "anthropic_api_key"),
        strategy="models",
        models_url="https://api.anthropic.com/v1/models?limit=1000",
        auth_kind="anthropic",
        balance_note="A chave comum não expõe saldo. Relatórios de custo/uso usam Admin API e credencial administrativa separada.",
        docs=(
            "https://platform.claude.com/docs/en/api/models/list",
            "https://platform.claude.com/docs/en/api/admin/cost_report/retrieve",
        ),
    ),
    ProviderSpec(
        slug="openrouter",
        name="OpenRouter",
        aliases=("OPENROUTER_API_KEY", "openrouter_api_key"),
        strategy="openrouter",
        models_url="https://openrouter.ai/api/v1/models?output_modalities=all",
        balance_note="Chave comum expõe uso e limite próprio; saldo total da conta exige Management API Key.",
        docs=(
            "https://openrouter.ai/docs/api/api-reference/api-keys/get-current-key",
            "https://openrouter.ai/docs/api/api-reference/credits/get-credits",
            "https://openrouter.ai/docs/api/api-reference/models/get-models",
        ),
    ),
    ProviderSpec(
        slug="groq",
        name="Groq",
        aliases=("GROQ_API_KEY", "groq_api_key"),
        strategy="models",
        models_url="https://api.groq.com/openai/v1/models",
        balance_note="Não há endpoint oficial público documentado para saldo com a chave de inferência; consulte o Console GroqCloud.",
        docs=("https://console.groq.com/docs/models",),
    ),
    ProviderSpec(
        slug="cerebras",
        name="Cerebras",
        aliases=("CEREBRAS_API_KEY", "cerebras_api_key_context"),
        strategy="cerebras",
        models_url="https://api.cerebras.ai/v1/models",
        balance_note="Não há endpoint oficial público documentado para saldo com a chave de inferência; consulte o painel da Cerebras.",
        docs=(
            "https://inference-docs.cerebras.ai/api-reference/models/list-models",
            "https://inference-docs.cerebras.ai/api-reference/models/public-models",
            "https://www.cerebras.ai/pricing",
        ),
    ),
    ProviderSpec(
        slug="mistral",
        name="Mistral",
        aliases=("MISTRAL_API_KEY", "mistral_api_key_context"),
        strategy="models",
        models_url="https://api.mistral.ai/v1/models",
        balance_note="A chave comum não expõe créditos. Uso e limites da organização exigem Admin API Key; saldo de créditos fica no painel.",
        docs=(
            "https://docs.mistral.ai/api/endpoint/models",
            "https://docs.mistral.ai/admin/admin-api/usage-metrics",
            "https://docs.mistral.ai/admin/billing-usage/billing",
        ),
    ),
    ProviderSpec(
        slug="deepseek",
        name="DeepSeek",
        aliases=("DEEPSEEK_API_KEY", "deepseek_api_key_context"),
        strategy="deepseek",
        models_url="https://api.deepseek.com/models",
        docs=(
            "https://api-docs.deepseek.com/api/get-user-balance/",
            "https://api-docs.deepseek.com/api/list-models/",
        ),
    ),
    ProviderSpec(
        slug="together",
        name="Together AI",
        aliases=("TOGETHER_API_KEY", "together_api_key_context"),
        strategy="models",
        models_url="https://api.together.ai/v1/models",
        balance_note="O saldo pré-pago e a análise de custos são documentados no painel; não há endpoint público oficial de saldo para a chave comum.",
        docs=(
            "https://docs.together.ai/reference/models",
            "https://docs.together.ai/docs/billing-credits",
            "https://docs.together.ai/docs/billing-usage-limits",
        ),
    ),
    ProviderSpec(
        slug="huggingface",
        name="Hugging Face",
        aliases=("HF_TOKEN", "HUGGINGFACEHUB_API_TOKEN", "huggingface"),
        strategy="huggingface",
        models_url="https://router.huggingface.co/v1/models",
        balance_note="Créditos e uso de Inference Providers são consultados na página de billing; não há endpoint público oficial de saldo documentado.",
        docs=(
            "https://huggingface.co/docs/hub/security-tokens",
            "https://huggingface.co/docs/inference-providers/en/index",
            "https://huggingface.co/docs/inference-providers/pricing",
        ),
    ),
    ProviderSpec(
        slug="replicate",
        name="Replicate",
        aliases=("REPLICATE_API_TOKEN", "replicate_api_token"),
        strategy="replicate",
        models_url="https://api.replicate.com/v1/models",
        model_list_complete=False,
        balance_note="A API oficial expõe conta e modelos, mas não saldo; uso/créditos ficam na página de billing.",
        docs=(
            "https://replicate.com/docs/reference/http/",
            "https://replicate.com/docs/topics/billing",
        ),
    ),
)

PROVIDER_BY_SLUG = {provider.slug: provider for provider in PROVIDERS}


def _auth_headers(spec: ProviderSpec, key: str) -> dict[str, str]:
    if spec.auth_kind == "anthropic":
        return {"x-api-key": key, "anthropic-version": "2023-06-01"}
    return {"Authorization": f"Bearer {key}"}


def _fingerprint(secret: str) -> str:
    return f"sha256:{hashlib.sha256(secret.encode('utf-8')).hexdigest()[:12]}"


def _balance_unavailable(spec: ProviderSpec) -> dict[str, Any]:
    return {
        "reported": False,
        "kind": "not_exposed_by_official_api",
        "note": spec.balance_note,
    }


def _base_result(spec: ProviderSpec, key_source: str, key: str) -> dict[str, Any]:
    return {
        "provider": spec.slug,
        "provider_name": spec.name,
        "configured": True,
        "key_source": key_source,
        "key_fingerprint": _fingerprint(key),
        "status": "checking",
        "authenticated": None,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "models": [],
        "model_count": 0,
        "model_list_complete": spec.model_list_complete,
        "account": None,
        "balance": _balance_unavailable(spec),
        "rate_limits": {},
        "warnings": [],
        "error": None,
        "documentation": list(spec.docs),
    }


def missing_result(spec: ProviderSpec) -> dict[str, Any]:
    return {
        "provider": spec.slug,
        "provider_name": spec.name,
        "configured": False,
        "key_source": None,
        "key_fingerprint": None,
        "status": "missing",
        "authenticated": None,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "models": [],
        "model_count": 0,
        "model_list_complete": False,
        "account": None,
        "balance": _balance_unavailable(spec),
        "rate_limits": {},
        "warnings": [],
        "error": None,
        "documentation": list(spec.docs),
    }


def _status_for_error(error: ApiError) -> str:
    if error.status == 401:
        return "invalid"
    if error.status == 403:
        return "restricted"
    if error.status == 429:
        return "rate_limited"
    return "unavailable"


def _record_primary_error(result: dict[str, Any], error: ApiError) -> None:
    result["status"] = _status_for_error(error)
    result["authenticated"] = False if error.status == 401 else None
    result["error"] = {
        "kind": error.kind,
        "http_status": error.status,
        "message": str(error),
    }


def _record_optional_error(result: dict[str, Any], label: str, error: ApiError) -> None:
    result["status"] = "partial" if result["status"] == "valid" else result["status"]
    status = f"HTTP {error.status}" if error.status else error.kind
    result["warnings"].append(f"{label}: {status}: {error}")


def _extract_models(payload: Any) -> tuple[list[Mapping[str, Any]], bool]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)], True
    if not isinstance(payload, Mapping):
        return [], False
    for field in ("data", "models", "results"):
        value = payload.get(field)
        if isinstance(value, list):
            complete = not bool(payload.get("has_more")) and not bool(payload.get("next"))
            return [item for item in value if isinstance(item, Mapping)], complete
    return [], False


def _first(mapping: Mapping[str, Any], *paths: str) -> Any:
    for path in paths:
        current: Any = mapping
        for part in path.split("."):
            if not isinstance(current, Mapping) or part not in current:
                current = None
                break
            current = current[part]
        if current is not None:
            return current
    return None


def normalize_model(raw: Mapping[str, Any]) -> dict[str, Any]:
    owner = _first(raw, "owned_by", "organization", "owner")
    model_id = _first(raw, "id", "model_id")
    if not model_id and raw.get("name") and owner:
        model_id = f"{owner}/{raw['name']}"
    if not model_id:
        model_id = raw.get("name") or "unknown"

    model: dict[str, Any] = {
        "id": str(model_id),
        "name": _first(raw, "display_name", "name") or str(model_id),
    }
    optional = {
        "owner": owner,
        "type": _first(raw, "type", "pipeline_tag"),
        "context_length": _first(raw, "context_length", "max_context_length", "max_input_tokens", "limits.max_context_length"),
        "max_output_tokens": _first(raw, "max_tokens", "top_provider.max_completion_tokens", "limits.max_completion_tokens"),
        "pricing": raw.get("pricing"),
        "capabilities": raw.get("capabilities"),
        "architecture": raw.get("architecture"),
        "supported_parameters": raw.get("supported_parameters"),
        "aliases": raw.get("aliases"),
        "license": raw.get("license"),
        "deprecated": raw.get("deprecated"),
        "preview": raw.get("preview"),
    }
    description = raw.get("description")
    if isinstance(description, str) and description:
        optional["description"] = description[:500]
    for key, value in optional.items():
        if value not in (None, "", [], {}):
            model[key] = value
    return model


def _set_models(
    result: dict[str, Any],
    response: ApiResponse,
    *,
    model_limit: int,
    force_complete: bool | None = None,
    enrichment: Mapping[str, Mapping[str, Any]] | None = None,
) -> None:
    raw_models, detected_complete = _extract_models(response.data)
    normalized: list[dict[str, Any]] = []
    for raw in raw_models:
        merged = dict(raw)
        model_id = str(raw.get("id") or "")
        if enrichment and model_id in enrichment:
            merged = {**enrichment[model_id], **merged}
        normalized.append(normalize_model(merged))
    normalized.sort(key=lambda item: item["id"].casefold())
    result["model_count"] = len(normalized)
    result["model_list_complete"] = detected_complete if force_complete is None else force_complete
    result["models"] = normalized if model_limit == 0 else normalized[:model_limit]
    if model_limit and len(normalized) > model_limit:
        result["warnings"].append(
            f"saída de modelos limitada a {model_limit} de {len(normalized)}; use --models-limit 0 para todos"
        )


def _record_limits(result: dict[str, Any], label: str, response: ApiResponse) -> None:
    selected = rate_limit_headers(response.headers)
    if selected:
        result["rate_limits"][label] = selected


def _audit_models(
    spec: ProviderSpec,
    key: str,
    key_source: str,
    client: HttpClient,
    model_limit: int,
) -> dict[str, Any]:
    result = _base_result(spec, key_source, key)
    try:
        response = client.get_json(spec.models_url, headers=_auth_headers(spec, key), secret=key)
    except ApiError as error:
        _record_primary_error(result, error)
        return result
    result["status"] = "valid"
    result["authenticated"] = True
    _set_models(result, response, model_limit=model_limit)
    _record_limits(result, "models", response)
    return result


def _safe_decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _audit_openrouter(
    spec: ProviderSpec,
    key: str,
    key_source: str,
    client: HttpClient,
    model_limit: int,
) -> dict[str, Any]:
    result = _base_result(spec, key_source, key)
    headers = _auth_headers(spec, key)
    try:
        key_response = client.get_json("https://openrouter.ai/api/v1/key", headers=headers, secret=key)
    except ApiError as error:
        _record_primary_error(result, error)
        return result

    result["status"] = "valid"
    result["authenticated"] = True
    _record_limits(result, "key", key_response)
    key_data = key_response.data.get("data", {}) if isinstance(key_response.data, Mapping) else {}
    safe_fields = (
        "label",
        "is_free_tier",
        "is_management_key",
        "is_provisioning_key",
        "limit",
        "limit_remaining",
        "limit_reset",
        "usage",
        "usage_daily",
        "usage_weekly",
        "usage_monthly",
        "byok_usage",
        "expires_at",
    )
    result["account"] = {field: key_data.get(field) for field in safe_fields if field in key_data}
    result["balance"] = {
        "reported": True,
        "kind": "api_key_limit",
        "currency": "USD",
        "limit": key_data.get("limit"),
        "remaining": key_data.get("limit_remaining"),
        "usage": key_data.get("usage"),
        "note": "Isto é o limite da chave, não necessariamente o saldo total da conta.",
    }

    if key_data.get("is_management_key"):
        try:
            credit_response = client.get_json(
                "https://openrouter.ai/api/v1/credits", headers=headers, secret=key
            )
            credit_data = credit_response.data.get("data", {}) if isinstance(credit_response.data, Mapping) else {}
            total_credits = _safe_decimal(credit_data.get("total_credits"))
            total_usage = _safe_decimal(credit_data.get("total_usage"))
            remaining = total_credits - total_usage if total_credits is not None and total_usage is not None else None
            result["balance"] = {
                "reported": True,
                "kind": "account_credits",
                "currency": "USD",
                "total_credits": str(total_credits) if total_credits is not None else None,
                "total_usage": str(total_usage) if total_usage is not None else None,
                "remaining": str(remaining) if remaining is not None else None,
            }
            _record_limits(result, "credits", credit_response)
        except ApiError as error:
            _record_optional_error(result, "saldo da conta", error)

    try:
        models_response = client.get_json(spec.models_url, headers=headers, secret=key)
        _set_models(result, models_response, model_limit=model_limit)
        _record_limits(result, "models", models_response)
    except ApiError as error:
        _record_optional_error(result, "modelos", error)
    return result


def _audit_deepseek(
    spec: ProviderSpec,
    key: str,
    key_source: str,
    client: HttpClient,
    model_limit: int,
) -> dict[str, Any]:
    result = _base_result(spec, key_source, key)
    headers = _auth_headers(spec, key)
    try:
        balance_response = client.get_json("https://api.deepseek.com/user/balance", headers=headers, secret=key)
    except ApiError as error:
        _record_primary_error(result, error)
        return result

    result["status"] = "valid"
    result["authenticated"] = True
    payload = balance_response.data if isinstance(balance_response.data, Mapping) else {}
    infos = payload.get("balance_infos") if isinstance(payload.get("balance_infos"), list) else []
    result["balance"] = {
        "reported": True,
        "kind": "account_balance",
        "is_available": payload.get("is_available"),
        "balances": [
            {
                field: item.get(field)
                for field in ("currency", "total_balance", "granted_balance", "topped_up_balance")
                if field in item
            }
            for item in infos
            if isinstance(item, Mapping)
        ],
    }
    _record_limits(result, "balance", balance_response)
    try:
        models_response = client.get_json(spec.models_url, headers=headers, secret=key)
        _set_models(result, models_response, model_limit=model_limit)
        _record_limits(result, "models", models_response)
    except ApiError as error:
        _record_optional_error(result, "modelos", error)
    return result


def _audit_huggingface(
    spec: ProviderSpec,
    key: str,
    key_source: str,
    client: HttpClient,
    model_limit: int,
) -> dict[str, Any]:
    result = _base_result(spec, key_source, key)
    headers = _auth_headers(spec, key)
    try:
        whoami = client.get_json("https://huggingface.co/api/whoami-v2", headers=headers, secret=key)
    except ApiError as error:
        _record_primary_error(result, error)
        return result

    result["status"] = "valid"
    result["authenticated"] = True
    data = whoami.data if isinstance(whoami.data, Mapping) else {}
    access_token = _first(data, "auth.accessToken")
    orgs = data.get("orgs") if isinstance(data.get("orgs"), list) else []
    account: dict[str, Any] = {
        field: data.get(field)
        for field in ("type", "name", "fullname", "isPro", "canPay", "periodEnd")
        if field in data
    }
    if isinstance(access_token, Mapping):
        account["token"] = {
            field: access_token.get(field)
            for field in ("displayName", "role", "createdAt")
            if field in access_token
        }
    account["organizations"] = [org.get("name") for org in orgs if isinstance(org, Mapping) and org.get("name")]
    result["account"] = account
    _record_limits(result, "account", whoami)
    try:
        models_response = client.get_json(spec.models_url, headers=headers, secret=key)
        _set_models(result, models_response, model_limit=model_limit)
        _record_limits(result, "models", models_response)
    except ApiError as error:
        _record_optional_error(result, "modelos de Inference Providers", error)
    return result


def _audit_replicate(
    spec: ProviderSpec,
    key: str,
    key_source: str,
    client: HttpClient,
    model_limit: int,
) -> dict[str, Any]:
    result = _base_result(spec, key_source, key)
    headers = _auth_headers(spec, key)
    try:
        account_response = client.get_json("https://api.replicate.com/v1/account", headers=headers, secret=key)
    except ApiError as error:
        _record_primary_error(result, error)
        return result

    result["status"] = "valid"
    result["authenticated"] = True
    data = account_response.data if isinstance(account_response.data, Mapping) else {}
    result["account"] = {
        field: data.get(field) for field in ("type", "username", "name", "github_url") if field in data
    }
    _record_limits(result, "account", account_response)
    try:
        models_response = client.get_json(spec.models_url, headers=headers, secret=key)
        _set_models(result, models_response, model_limit=model_limit, force_complete=False)
        _record_limits(result, "models", models_response)
    except ApiError as error:
        _record_optional_error(result, "modelos públicos", error)
    return result


def _audit_cerebras(
    spec: ProviderSpec,
    key: str,
    key_source: str,
    client: HttpClient,
    model_limit: int,
) -> dict[str, Any]:
    result = _base_result(spec, key_source, key)
    headers = _auth_headers(spec, key)
    try:
        models_response = client.get_json(spec.models_url, headers=headers, secret=key)
    except ApiError as error:
        _record_primary_error(result, error)
        return result

    result["status"] = "valid"
    result["authenticated"] = True
    enrichment: dict[str, Mapping[str, Any]] = {}
    try:
        public_response = client.get_json("https://api.cerebras.ai/public/v1/models")
        public_models, _ = _extract_models(public_response.data)
        enrichment = {str(item.get("id")): item for item in public_models if item.get("id")}
    except ApiError as error:
        _record_optional_error(result, "metadados públicos de preço/capacidade", error)
    _set_models(result, models_response, model_limit=model_limit, enrichment=enrichment)
    _record_limits(result, "models", models_response)
    return result


def _redact_structure(value: Any, secret: str) -> Any:
    """Última barreira contra um provedor que ecoe a credencial na resposta."""

    if isinstance(value, str):
        return value.replace(secret, "[REDACTED]") if secret else value
    if isinstance(value, list):
        return [_redact_structure(item, secret) for item in value]
    if isinstance(value, dict):
        return {key: _redact_structure(item, secret) for key, item in value.items()}
    return value


def audit_provider(
    spec: ProviderSpec,
    key: str,
    key_source: str,
    client: HttpClient,
    model_limit: int = 20,
) -> dict[str, Any]:
    if spec.strategy == "openrouter":
        result = _audit_openrouter(spec, key, key_source, client, model_limit)
    elif spec.strategy == "deepseek":
        result = _audit_deepseek(spec, key, key_source, client, model_limit)
    elif spec.strategy == "huggingface":
        result = _audit_huggingface(spec, key, key_source, client, model_limit)
    elif spec.strategy == "replicate":
        result = _audit_replicate(spec, key, key_source, client, model_limit)
    elif spec.strategy == "cerebras":
        result = _audit_cerebras(spec, key, key_source, client, model_limit)
    else:
        result = _audit_models(spec, key, key_source, client, model_limit)
    return _redact_structure(result, key)
